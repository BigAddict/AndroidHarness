# AndroidHarness v1 — Design Spec

**Date:** 2026-05-19
**Status:** Approved for planning

## 1. Goal

Give an LLM a real Android phone and a natural-language task, and let it work the task to completion by reading the device's UI tree and issuing UI actions over ADB.

Scope of this spec is **v1**: single-task interactive runs against one ADB-connected device.

## 2. Non-goals (v1)

- Benchmarking / batch task suites.
- Parallel execution across multiple devices.
- Cross-device coordination within a single task.
- App install/uninstall management — target apps are assumed preinstalled.
- Run replay or record-playback.
- Reflection / critic / multi-agent setups — single-agent loop only.
- Web dashboard. Logs are JSONL + a small text reporter.
- LLM-as-judge scoring of task success.

## 3. Architecture

```
            ┌─────────────────────────────────────────────┐
            │              Agent Loop                     │
            │                                             │
   ┌──►  Observe  ──►  Think (Gemini)  ──►  Act  ──┐      │
   │       │                                    │  │      │
   │   compact UI tree                       tool │      │
   │   (numbered nodes)                      call │      │
   │   prev tool result                           │      │
   │   (optional: screenshot                      │      │
   │    when model requested)                     │      │
   │                                              │      │
   └────────────────── new device state ◄─────────┘      │
                                                         │
            └─────────────────────────────────────────────┘
                              │
                       done() | budget exhausted
```

Four units, each independently testable:

| Unit | Responsibility | Depends on |
|---|---|---|
| `device/` | uiautomator2 wrapper. Connect by serial, screenshot, dump_hierarchy, primitive actions. | uiautomator2 |
| `perception/` | XML hierarchy → compact numbered list of interactable nodes. Maintains id→node map for the current turn. Optional screenshot fetcher. | `device`, lxml |
| `agent/` | Gemini function-calling loop. Tool schema, observation formatter, tool-call validation, turn budget, retry on transient errors. | `google-genai`, `perception` |
| `runner/` | CLI entry point. Single-task interactive run. Per-run directory with turn-by-turn log. | all of the above |

## 4. Perception layer

**UI-tree-first.** Each turn the harness calls `device.dump_hierarchy()` and produces a compact representation that strips noise:

- Keep nodes that are `clickable`, `long-clickable`, `scrollable`, or `editable`.
- Keep nodes with non-empty `text` or `content-desc` even if not interactable (labels matter for context).
- Drop pure layout containers with no text/interaction.
- For each kept node, assign a per-turn integer id starting at 1.
- Serialize as a compact list, e.g.:

  ```
  [1] Button "Settings" (clickable)
  [2] Button "Wi-Fi" (clickable)
  [3] EditText placeholder="Search" (editable)
  ...
  ```

The harness keeps an internal `id → (xpath | bounds | resource-id)` map for resolving tool calls back to a concrete uiautomator2 selector. Ids are not stable across turns — that's fine because the agent only acts on the current turn's tree.

**Screenshots are an escape hatch.** The agent does not get a screenshot every turn. It can call `show_screen()` to request one when the tree is insufficient (canvas-rendered apps, games, webviews, visual-layout questions). We log how often this is invoked as a quality signal.

## 5. Action vocabulary

Exposed to Gemini as function-calling tools:

| Tool | Args | Notes |
|---|---|---|
| `tap` | `id: int` | Resolves id → node → center tap. |
| `long_press` | `id: int, duration_ms: int = 800` | |
| `type` | `id: int, text: str` | Focuses then types; clears existing text if `replace=true`. |
| `swipe` | `direction: "up"\|"down"\|"left"\|"right", distance: "short"\|"long" = "short"` | Screen-relative, not node-relative. |
| `scroll` | `id: int, direction: "up"\|"down"\|"left"\|"right"` | Scrolls a specific scrollable node. |
| `press_key` | `name: "back"\|"home"\|"recents"\|"enter"` | Hardware/system keys only — whitelist enforced. |
| `wait` | `seconds: float` (max 10) | For loading states. |
| `show_screen` |  | Returns the next observation with a screenshot attached. |
| `done` | `success: bool, reason: str` | Terminates the loop. |

**Validation:** every tool call is validated before execution.
- Any `id` arg must exist in the current turn's id map; otherwise the harness returns a structured error turn (`"id 47 not in current tree; ids are 1..23"`) instead of executing.
- `press_key.name` is whitelisted.
- `wait.seconds` is clamped.

This is the layer that turns model hallucinations into recoverable error turns instead of garbage actions on the device.

## 6. Agent loop

```python
def run(task: str, device: Device, max_turns: int = 40, wall_clock_s: int = 600):
    history = [system_prompt(), user_task(task)]
    for turn in range(max_turns):
        if elapsed() > wall_clock_s: return TimeoutResult()
        obs = build_observation(device, include_screenshot=needs_screenshot)
        needs_screenshot = False
        response = gemini.generate(history + [obs], tools=TOOL_SCHEMA)
        tool_call = parse_tool_call(response)
        if tool_call.name == "done":
            return DoneResult(success=tool_call.success, reason=tool_call.reason)
        if tool_call.name == "show_screen":
            needs_screenshot = True
            result = ToolResult.ok("screenshot will be attached to next observation")
        else:
            result = execute(device, tool_call)  # also returns validation errors
        history.append(response); history.append(result_to_turn(result))
        log_turn(turn, obs, tool_call, result)
    return MaxTurnsResult()
```

**Stop conditions:** explicit `done()`, `max_turns` (default 40), `wall_clock_s` (default 600), or unrecoverable infra error (e.g., device disconnect that retries fail to recover).

**Retries:** Gemini transient errors (5xx, rate limits) → exponential backoff up to N attempts within a turn. ADB connection blips → `device` layer auto-reconnects.

## 7. Multi-device handling

`adb devices` enumeration drives device selection. v1 only runs one task at a time, but the CLI must behave sanely when multiple devices are attached:

- `androidharness run "<task>"` with **no device flag**:
  - 0 devices → exit with `no devices connected (check 'adb devices')`.
  - 1 device → use it.
  - 2+ devices → exit with a numbered list and a hint to pass `--serial` or `--device-index`. No silent pick.
- `--serial <SERIAL>` and `--device-index <N>` are mutually exclusive overrides.
- `androidharness devices` lists everything `adb devices` sees, with model name from `getprop ro.product.model`.

## 8. CLI

```
androidharness devices
androidharness run "<task>" [--serial S | --device-index N]
                            [--model gemini-2.5-flash]
                            [--max-turns 40]
                            [--wall-clock 600]
                            [--run-dir ./runs]
```

`gemini-2.5-flash` is the default model. `--model` accepts any model id supported by `google-genai`.

## 9. Run artifacts

Every run creates `./runs/<timestamp>-<short-id>/` containing:

- `meta.json` — task prompt, device serial+model, harness version, model id, start/end timestamps, final status.
- `turns.jsonl` — one line per turn: `{turn, observation_summary, tool_call, tool_result, latency_ms}`. Observation includes the compact node list (not the raw XML) for grep-ability.
- `screenshots/turn-<n>.png` — only when the model called `show_screen()` that turn.
- `result.json` — final `{status: done|max_turns|timeout|infra_error, success: bool|null, reason: str}`.

## 10. Configuration / secrets

- Gemini API key from `GOOGLE_API_KEY` env var (matches `google-genai` default). No key file, no config file in v1.
- No persistent state between runs.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tree blind to canvas/overlay apps | `show_screen()` escape hatch; log usage frequency as a signal. |
| Model hallucinates ids not in the tree | Validate every tool call against the per-turn id map; return structured error turns. |
| ADB connection drops mid-task | `device` layer auto-reconnects with bounded retries; permanent loss → `infra_error` (not a model failure). |
| Loops where the model repeats the same failing action | v1 logs it; user spots it via `turns.jsonl`. A "no progress" detector is a v2 follow-up, not a v1 blocker. |
| Long tasks blow the model context | Per-turn observation is compact (numbered list, not raw XML). Older turns can be summarized if context pressure shows up — keep simple-FIFO until that happens. |

## 12. Testing strategy

- `device/` — integration tests against a real connected device or an emulator (gated by env var; skip when no device present).
- `perception/` — pure unit tests with fixture XML hierarchies → expected compact node lists.
- `agent/` — unit tests with a fake Gemini client returning canned tool calls; verify loop control flow, validation errors, stop conditions.
- `runner/` — smoke test: assemble all layers with fakes, run a 3-turn scripted task end to end, assert artifacts written correctly.

## 13. Dependencies to add

- `google-genai` (Gemini SDK)
- `lxml` (faster, more robust XML parsing than stdlib for hierarchy dumps)
- `pillow` (only used when screenshots are requested)
- `typer` or `click` for the CLI (pick one in the plan; nothing in the spec depends on which)
- Dev: `pytest`, `pytest-asyncio` if any async creeps in, `ruff` for lint+format.

## 14. Open questions deferred to implementation plan

- Exact compact-node-list format (whitespace, attribute order) — pick once, lock in.
- Whether to send the previous turn's full tool result or just status in the observation.
- Whether `type` auto-clears the field or has a `replace` flag.
- Concrete retry/backoff numbers for Gemini and ADB.
