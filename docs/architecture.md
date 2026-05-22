# Architecture

## Overview

```
CLI (cli.py)
  └── run_task (runner.py)
        ├── Agent (agent.py)
        │     ├── parse_hierarchy (perception.py)   ← XML → typed Observation
        │     ├── Renderer (render.py)               ← Observation → text the LLM sees
        │     ├── LLMClient (llm.py)                 ← Protocol; LiteLLMClient / LiteLLMRouterClient / GoogleGenaiClient
        │     ├── Policy (policy.py)                 ← auto / confirm / dry-run / deny gate
        │     └── execute (tools.py)                 ← dispatches tool calls to device
        └── UIAutomatorDevice (device.py)            ← ADB wrapper
```

Each module has a clean interface. `device.py` exposes a `Device` Protocol so tests substitute `FakeDevice` without any mocking framework.

---

## Module reference

### `androidharness/cli.py`

Entry point for every user-facing command. Registered as the `androidharness` script in `pyproject.toml`.

Commands:
- `androidharness devices` — lists connected devices (serial + model name via `getprop`)
- `androidharness run <task>` — resolves config, selects device, builds the per-run `Policy` (config + `--policy` override) and `CliConfirmer`, builds `Agent` + the configured `LLMClient` (`LiteLLMClient` by default; `LiteLLMRouterClient` when `throttler.enabled`; `GoogleGenaiClient` when `providers.use_litellm=false`), calls `run_task`
- `androidharness peek` — read-only dump of what the model would see on the connected device's current screen. Runs the same `dump_hierarchy → parse_hierarchy → DEFAULT_RENDERER.observation` path the agent uses, prints the rendered Observation (or raw XML with `--raw-xml`). Flags `--viewport-filter/--no-viewport-filter` and `--with-resource-ids/--no-resource-ids` override the config per invocation. No LLM call, no tool fires, no device state change.
- `androidharness config path|init|show|validate` — config file utilities

The `run` command is the main path. It resolves all defaults from `AndroidHarnessConfig`, validates the environment (API key, device presence), then delegates to `runner.run_task`. Exit code is 0 on `success=True`, 1 otherwise.

### `androidharness/config.py`

Pydantic v2 schema for `~/.androidharness/config.yaml`.

Top-level model: `AndroidHarnessConfig` (version-locked to `1`). Sub-models:
- `DefaultsConfig` — per-run defaults (model, turns, dirs, device serial)
- `ProvidersConfig` — selects which provider (`gemini` / `anthropic` / `openai`) the CLI uses, and whether to route via LiteLLM or the v1 direct-Gemini client
- `ThrottlerConfig` — rate limiting, deployments fallback list, cooldown, retries
- `PolicyConfig` — auto/confirm/dry-run/deny gate per tool; default-mode + confirm_timeout_s; spec-mandated `type:confirm` and `long_press:confirm` defaults
- `MemoryConfig` — placeholder for milestone 12 (chromadb)
- `PerceptionConfig` — feature flags (sibling_collapse, viewport_filter, resource_id_in_render, screenshot_quantized)
- `LoggingConfig` — log level and rotation size

`load_config(path)` returns defaults when the file is absent. `save_config` writes YAML with a header comment. The `ANDROIDHARNESS_CONFIG` env var overrides the default path.

See `androidharness/config.py:98` for `default_config_path()`.

### `androidharness/device.py`

Two things:
1. `Device` Protocol (`device.py:14`) — the interface every device implementation must satisfy. Methods: `dump_hierarchy`, `screenshot`, `tap`, `long_press`, `type_text`, `swipe`, `scroll`, `press_key`, `wait`, `open_notifications`, `close_notifications`.
2. `UIAutomatorDevice` (`device.py:68`) — the real implementation backed by `uiautomator2`. Connects with `UIAutomatorDevice.connect(serial)`.

Notable details:
- `type_text` writes through the focused node's accessibility `set_text` — no IME swap, no shell-out. `replace=False` reads the field first and concatenates so multiple calls genuinely append. After every write the device reads the field back and raises `TypeFieldMismatchError` if it disagrees with what was requested (typical cause: `maxLength` constraint with an Android toast — toasts float above the accessibility tree and are invisible to `dump_hierarchy`, so the model otherwise can't perceive the truncation). The agent's exception shield turns this into an `ok=False` `tool_result` with the field's real end-state.
- `swipe` and `scroll` both use `uiautomator2`'s `swipe` primitive under the hood; `scroll` centers the gesture on the resolved node (`device.py:147`).
- `open_notifications` / `close_notifications` use `adb shell cmd statusbar expand-notifications|collapse` (Android 9+, no root required).
- `list_devices()` runs `adb devices` and resolves model names via `getprop ro.product.model`.

### `androidharness/perception.py`

Converts the raw uiautomator2 XML hierarchy into a typed `Observation` of `Node` dataclasses. Pure parse + filter — no rendering, no text output.

Key types:
- `Node` — immutable dataclass for one UI node. Attributes: `id`, `class_name`, `text`, `content_desc`, `resource_id`, `bounds`, `clickable`, `long_clickable`, `scrollable`, `editable`, plus state flags `enabled` (default True), `focused`, `checked`, `password` (default False). Computed: `center`, `short_class`. `format()` and `summary` are back-compat shims that delegate to `render.DEFAULT_RENDERER`.
- `Observation` — holds the node list for one turn. `resolve(id)` returns the node or raises `KeyError`. `render()` is a back-compat shim that delegates to `render.DEFAULT_RENDERER.observation(...)`.

`parse_hierarchy(xml, viewport_filter=False)` does the work:
- Keeps nodes that are interactable (clickable, long-clickable, scrollable, editable) or have non-empty text/content-desc.
- Drops pure structural containers.
- Assigns sequential integer ids starting at 1 — ids are turn-local, not stable across turns.
- When an interactable node has no own label, it absorbs text from non-interactable descendants (`_collect_descendant_text`).
- With `viewport_filter=True`, drops nodes with degenerate bounds, `visibility="gone"`, or bounds fully outside the screen rect derived from the top-level window node.

### `androidharness/render.py`

The seam between the typed perception layer and the text the LLM actually sees. Lets us experiment with denser formats (TOON, YAML-columnar, JSON-lines, …) without touching perception logic.

- `Renderer` Protocol — `node(n, with_resource_id)` and `observation(obs, with_resource_id)` return strings. Pure functions of the Observation; no I/O.
- `ProseRenderer` — the v1 format. Each node is one line: `[id] ClassName "label" #resource_id (traits)`. Resource-id and traits are optional.
- `DEFAULT_RENDERER = ProseRenderer()` — the singleton every caller resolves through. Replace via DI on the agent when benchmarking alternatives.

Ship a new renderer only after a fixture-driven benchmark proves both a token-count win **and** no tool-call accuracy regression on the existing test set (per v2 spec §7 step 4).

### `androidharness/agent.py`

The agent loop and the Gemini API adapter.

`Agent` dataclass (`agent.py:117`):
- Fields: `device`, `client`, `model`, `max_turns`, `wall_clock_s`, `quantize_screenshots`, `viewport_filter`, `resource_id_in_render`, `policy`, `confirmer`
- `run(task, on_turn=None)` — the main loop. Returns a `RunResult` with `status` (`done`|`max_turns`|`timeout`), `success`, `reason`, `turns`, `turn_log`.

Loop behavior per turn:
1. Check wall-clock timeout.
2. Dump hierarchy (and screenshot concurrently if requested, using `ThreadPoolExecutor`).
3. Parse observation, check no-progress detector.
4. Call `client.generate(...)`.
5. Dispatch via `policy.apply(call, _run_tool, confirmer)` — `auto` passes through to `execute(device, call, obs)`, `confirm`/`dry-run`/`deny` short-circuit. Exceptions from device drivers are caught inside the `_run_tool` closure and surfaced as `ToolError` so the agent can react rather than crash.
6. Append turn to `turn_log`, call `on_turn` callback (used by runner to stream writes).
7. If result is `done`, return immediately.

No-progress detector (`agent.py:89`): if the last 3 turns all issued the identical tool call AND the observation render is unchanged, a `NO_PROGRESS` warning is injected into `contents` before the next model call.

`LLMClient` Protocol + adapters live in `androidharness/llm.py`. Three concrete clients implement it: `LiteLLMClient` (default — direct `litellm.completion` per call), `LiteLLMRouterClient` (selected when `throttler.enabled` — wraps `litellm.Router` for per-deployment rate limiting and ordered fallback on 429 errors), and `GoogleGenaiClient` (escape hatch — direct `google-genai` SDK with its own retry/backoff). All three flatten the agent's internal `contents` list and fall back to `done(success=False)` when the model returns no function call. Two private helpers in the same module translate the agent's tool declarations and contents into OpenAI-shaped schemas, and a third (`_build_router_kwargs`) translates `AndroidHarnessConfig` into the kwargs `litellm.Router(...)` expects.

`SYSTEM_PROMPT` (`agent.py:28`): the static instruction block prepended to every model call. Covers id stability, scroll vs. swipe guidance, no-progress recovery, install avoidance, and the done() contract.

### `androidharness/tools.py`

Two things:
1. `execute(device, call, obs)` (`tools.py:49`) — dispatches a `ToolCall` to the device. All validation happens here before any device call is made. Returns `ToolResult` or `ToolError`.
2. `GEMINI_FUNCTION_DECLARATIONS` (`tools.py:144`) — the function schema list passed to Gemini on every turn.

Validation rules enforced in `execute`:
- Any `id` argument is looked up in `obs` before use; missing id returns a structured error message naming the valid range.
- `press_key.name` is checked against `{"back", "home", "recents", "enter"}`.
- `swipe.direction` and `swipe.distance` are checked against allowed enums.
- `wait.seconds` is clamped to `[0, 10]`.

### `androidharness/runner.py`

Orchestrates a single task run: creates the run directory, streams turn data to `turns.jsonl` via the `on_turn` callback, writes `meta.json` before the loop starts (so the run is discoverable on crash), and writes `result.json` on completion.

`run_task(...)` (`runner.py:37`) — the single public function. Returns `RunOutcome`.

Run directory naming: `<YYYYMMDDTHHMMSSz>-<6 hex chars>` (e.g. `20260520T174908Z-7dfe2c`). Created under `runs_root`, which defaults to `./runs`.

Screenshots are written to `screenshots/turn-NNN.png` and their relative path is added to the turn's JSONL record.

If `agent.run()` raises (e.g., device disconnect), the runner sets `meta["status"] = "crashed"` and re-raises.

### `androidharness/policy.py`

The policy gate the agent consults before every tool call.

- `PolicyDecision` — `Enum(AUTO|CONFIRM|DRY_RUN|DENY)`. String values match the YAML mode strings so `PolicyDecision(cfg_mode)` round-trips.
- `Policy` — owns the per-tool decision lookup. `decide(name)` returns the resolved `PolicyDecision`; `apply(call, execute_fn, confirmer)` dispatches: `auto` passes through to `execute_fn`; `confirm` asks the injected `Confirmer` and returns the answer-shaped result; `dry-run` returns `ToolResult(message="dry-run: ...")` without touching the device; `deny` returns `ToolError(message="policy=deny: ...")`.
- `Confirmer` Protocol — single method `ask(call: ToolCall) -> bool`. `CliConfirmer` (default in the CLI) prompts on stderr and reads stdin with a `select`-based timeout. `AlwaysApproveConfirmer` / `AlwaysRejectConfirmer` / `RecordingConfirmer` are test helpers.

The agent loop (`agent.py`) wraps the `tools.execute(...)` call in a closure and hands it to `policy.apply(...)`; the policy's return value is what reaches the agent's turn log.

### `androidharness/imaging.py`

`quantize_png(png_bytes)` — converts a PNG to a 256-color palette PNG using Pillow. Typical size reduction: 30–50% for app UI screenshots. Used when `perception.screenshot_quantized = true` in config.

### `androidharness/logging_setup.py`

`setup_logging(logs_dir)` — attaches a `RotatingFileHandler` (max 10 MB per file, 5 backups, ~60 MB ceiling) AND a `StreamHandler(sys.stderr)` to the `androidharness` logger. The file is the durable record; stderr is the live feed the terminal user watches while a run is in progress. The structured stdout summary (run dir / status / success / reason / turns) stays uncluttered. Idempotent — safe to call multiple times in the same process. A back-compat `setup_file_logging` alias exists for now.

### `androidharness/web/`

Settings UI subpackage (v2 milestone 5). FastAPI app behind a lazy import from `cli.py serve`, so the `[web]` extra (`fastapi`, `jinja2`, `uvicorn`, `python-multipart`, `pydantic-settings`) stays optional. `web/store.py` does atomic load/write of `config.yaml`; `web/routes.py` registers one `GET /panel/<name>` + `PATCH /config/<section>` per panel (providers, models, throttler, policy, devices, logging, general); `web/secrets.py` exposes `ProviderSecrets.is_set(env_var_name)` for the env-presence badges. Form bodies use dotted keys (`policy.per_tool.tap`) that `web/forms.py:unflatten` converts to nested dicts before Pydantic validation. The throttler / models / providers handlers consume the raw form directly because their keys contain `/`. Validation runs the full `AndroidHarnessConfig` end-to-end so cross-section invariants (e.g. `providers.default in providers.entries`) are caught before writing.
