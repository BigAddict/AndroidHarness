# Run artifacts

Every `androidharness run` creates a directory under `runs_dir` (default `./runs`) named:

```
runs/<YYYYMMDDTHHMMSSz>-<6 hex chars>/
```

Example: `runs/20260520T174908Z-7dfe2c/`

Contents:

```
meta.json          — task, device, model, start/end times, final status
turns.jsonl        — one JSON object per line, one line per agent turn
result.json        — final outcome (status, success, reason, turn count)
screenshots/       — PNG files, only present when show_screen() was called
  turn-003.png
  turn-011.png
  ...
```

---

## `meta.json`

Written before the agent loop starts (so the run is discoverable even if it crashes), then updated with `ended_at` and final `status` on completion.

```json
{
  "harness_version": "0.1.0",
  "task": "See if you can reach whatsapp and text myself",
  "model": "gemini-2.5-flash",
  "device": {
    "serial": "R92XA0AB89Y",
    "model": "a05mxx"
  },
  "started_at": 1779299348.1695347,
  "max_turns": 40,
  "wall_clock_s": 600.0,
  "status": "done",
  "ended_at": 1779299432.6295907
}
```

| Field | Type | Description |
|-------|------|-------------|
| `harness_version` | string | `androidharness.__version__` at run time |
| `task` | string | The task prompt passed to `run` |
| `model` | string | The Gemini model id used |
| `device.serial` | string | ADB serial |
| `device.model` | string | `ro.product.model` from `getprop` |
| `started_at` | float | Unix timestamp (`time.time()`) |
| `max_turns` | int | Configured turn budget |
| `wall_clock_s` | float | Configured wall-clock budget (seconds) |
| `status` | string | `"running"` while active; final value is one of `done`, `max_turns`, `timeout`, `crashed` |
| `ended_at` | float | Unix timestamp on completion (absent if crashed before the finally block) |

---

## `turns.jsonl`

One JSON object per line, appended and flushed after each turn. Because it is written incrementally, it is readable mid-run.

```jsonl
{"turn": 1, "observation_summary": "[1] LinearLayout ...\n[2] ...", "observation_payload": {"role": "observation", "text": "..."}, "tool_call": {"name": "swipe", "args": {"direction": "up"}}, "tool_result": {"role": "tool_result", "tool": "swipe", "ok": true, "message": "swiped up short"}}
{"turn": 2, "observation_summary": "[1] GridView (scrollable)\n[2] TextView \"Google\" ...", "observation_payload": {"role": "observation", "text": "..."}, "tool_call": {"name": "scroll", "args": {"direction": "down", "id": 1}}, "tool_result": {"role": "tool_result", "tool": "scroll", "ok": true, "message": "scrolled id 1 down"}}
{"turn": 3, ..., "tool_call": {"name": "swipe", "args": {"direction": "up", "distance": "long"}}, ...}
```

| Field | Type | Description |
|-------|------|-------------|
| `turn` | int | Turn index, 1-based |
| `observation_summary` | string | The compact node list sent to the model (`Observation.render()`) |
| `observation_payload` | object | Internal observation dict; `screenshot` bytes are stripped (saved to file instead) |
| `tool_call.name` | string | Tool name the model called |
| `tool_call.args` | object | Arguments as-received from the model |
| `tool_result.role` | string | Always `"tool_result"` |
| `tool_result.tool` | string | Tool name (or `"system"` for NO_PROGRESS warnings) |
| `tool_result.ok` | bool | `true` if `ToolResult`, `false` if `ToolError` |
| `tool_result.message` | string | Result message or error description |
| `screenshot_path` | string | Relative path to the PNG file, present only when `show_screen()` was called that turn |

The `observation_summary` field is the most useful for grepping: it contains the full node list in human-readable form.

---

## `result.json`

Written on completion (normal exit or crash).

```json
{
  "status": "done",
  "success": false,
  "reason": "Could not find a 'Myself' contact to text.",
  "turns": 22
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `done` — model called `done()`; `max_turns` — turn budget exhausted; `timeout` — wall-clock exceeded; `crashed` — unhandled exception |
| `success` | bool or null | `true`/`false` from the model's `done()` call; `null` when status is `max_turns` or `timeout` |
| `reason` | string | The `reason` arg from `done()`, or an automatic description for other statuses |
| `turns` | int | Number of turns completed |

---

## `screenshots/`

Each file is named `turn-NNN.png` where `NNN` is zero-padded to 3 digits. Files exist only for turns where the model called `show_screen()`. When `perception.screenshot_quantized = true` in config, screenshots are 256-color palette PNGs rather than full-color.
