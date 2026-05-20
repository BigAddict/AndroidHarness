# Architecture

## Overview

```
CLI (cli.py)
  └── run_task (runner.py)
        ├── Agent (agent.py)
        │     ├── parse_hierarchy (perception.py)   ← reads UI tree each turn
        │     ├── GeminiClient (agent.py)            ← calls Gemini API
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
- `androidharness run <task>` — resolves config, selects device, builds `Agent` + `GoogleGenaiClient`, calls `run_task`
- `androidharness config path|init|show|validate` — config file utilities

The `run` command is the main path. It resolves all defaults from `AndroidHarnessConfig`, validates the environment (API key, device presence), then delegates to `runner.run_task`. Exit code is 0 on `success=True`, 1 otherwise.

### `androidharness/config.py`

Pydantic v2 schema for `~/.androidharness/config.yaml`.

Top-level model: `AndroidHarnessConfig` (version-locked to `1`). Sub-models:
- `DefaultsConfig` — per-run defaults (model, turns, dirs, device serial)
- `ProvidersConfig` — placeholder for milestone 2 (LiteLLM)
- `ThrottlerConfig` — placeholder for milestone 3
- `PolicyConfig` — placeholder for milestone 4 (destructive-action gating)
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
- `type_text` captures and restores the device's IME after typing so it does not leave FastInputIME active (`device.py:96`).
- `swipe` and `scroll` both use `uiautomator2`'s `swipe` primitive under the hood; `scroll` centers the gesture on the resolved node (`device.py:147`).
- `open_notifications` / `close_notifications` use `adb shell cmd statusbar expand-notifications|collapse` (Android 9+, no root required).
- `list_devices()` runs `adb devices` and resolves model names via `getprop ro.product.model`.

### `androidharness/perception.py`

Converts the raw uiautomator2 XML hierarchy into a compact numbered list of nodes that fits in an LLM prompt.

Key types:
- `Node` (`perception.py:11`) — immutable dataclass for one UI node. Attributes: `id`, `class_name`, `text`, `content_desc`, `resource_id`, `bounds`, `clickable`, `long_clickable`, `scrollable`, `editable`. Computed: `center`, `short_class`, `summary`.
- `Observation` (`perception.py:61`) — holds the node list for one turn. `resolve(id)` returns the node or raises `KeyError`. `render()` returns the newline-joined text sent to the model.

`parse_hierarchy(xml, viewport_filter=False)` does the work:
- Keeps nodes that are interactable (clickable, long-clickable, scrollable, editable) or have non-empty text/content-desc.
- Drops pure structural containers.
- Assigns sequential integer ids starting at 1 — ids are turn-local, not stable across turns.
- When an interactable node has no own label, it absorbs text from non-interactable descendants (`_collect_descendant_text`).
- With `viewport_filter=True`, drops nodes with degenerate bounds, `visibility="gone"`, or bounds fully outside the screen rect derived from the top-level window node.

### `androidharness/agent.py`

The agent loop and the Gemini API adapter.

`Agent` dataclass (`agent.py:112`):
- Fields: `device`, `client`, `model`, `max_turns`, `wall_clock_s`, `quantize_screenshots`, `viewport_filter`
- `run(task, on_turn=None)` — the main loop. Returns a `RunResult` with `status` (`done`|`max_turns`|`timeout`), `success`, `reason`, `turns`, `turn_log`.

Loop behavior per turn:
1. Check wall-clock timeout.
2. Dump hierarchy (and screenshot concurrently if requested, using `ThreadPoolExecutor`).
3. Parse observation, check no-progress detector.
4. Call `client.generate(...)`.
5. Dispatch tool call via `execute(device, call, obs)`. Exceptions from device drivers are caught and surfaced as `ToolError` so the agent can react rather than crash.
6. Append turn to `turn_log`, call `on_turn` callback (used by runner to stream writes).
7. If result is `done`, return immediately.

No-progress detector (`agent.py:78`): if the last 3 turns all issued the identical tool call AND the observation render is unchanged, a `NO_PROGRESS` warning is injected into `contents` before the next model call.

`GoogleGenaiClient` (`agent.py:247`): adapts `google-genai`. Flattens the internal `contents` list into a single multi-part user message. Retries on 429/5xx with exponential backoff (up to 4 attempts). Falls back to `done(success=False)` when the model returns no function call.

`SYSTEM_PROMPT` (`agent.py:22`): the static instruction block prepended to every model call. Covers id stability, scroll vs. swipe guidance, no-progress recovery, install avoidance, and the done() contract.

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

### `androidharness/imaging.py`

`quantize_png(png_bytes)` — converts a PNG to a 256-color palette PNG using Pillow. Typical size reduction: 30–50% for app UI screenshots. Used when `perception.screenshot_quantized = true` in config.

### `androidharness/logging_setup.py`

`setup_file_logging(logs_dir)` — attaches a `RotatingFileHandler` to the `androidharness` logger. Max 10 MB per file, 5 backup files (~60 MB ceiling). Idempotent — safe to call multiple times in the same process.
