# Agent tool vocabulary

These are the functions exposed to Gemini on every turn via `GEMINI_FUNCTION_DECLARATIONS` (`androidharness/tools.py:144`). The agent calls exactly one per turn.

All `id` arguments refer to node ids from the **current turn's** Observation. Ids are not stable across turns — using an id from a previous turn will produce a structured error rather than a crash.

---

## `tap`

Tap a UI element by node id.

| Arg | Type | Required | Notes |
|-----|------|----------|-------|
| `id` | integer | yes | Must exist in the current Observation |

The id is resolved to the node's center coordinates, then `device.tap(x, y)` is called.

**When the model uses it:** tapping buttons, list items, toggles, icons.

---

## `long_press`

Long-press a UI element by node id.

| Arg | Type | Required | Default |
|-----|------|----------|---------|
| `id` | integer | yes | |
| `duration_ms` | integer | no | 800 |

**When the model uses it:** context menus, drag handles, widget configuration.

---

## `type`

Focus an editable field and type text.

| Arg | Type | Required | Notes |
|-----|------|----------|-------|
| `id` | integer | yes | Should be an `editable` node |
| `text` | string | yes | Text to type |
| `replace` | boolean | no | If `true`, clears the field before typing |

The implementation taps the node center to focus it, optionally calls `device.clear_text()`, then sends the text via uiautomator2's FastInputIME. The user's original IME is restored afterward.

**When the model uses it:** search boxes, text fields, form inputs.

---

## `swipe`

Whole-screen gesture. Direction names the way the **finger travels**, not the direction content moves.

| Arg | Type | Required | Values | Default |
|-----|------|----------|--------|---------|
| `direction` | string | yes | `up`, `down`, `left`, `right` | |
| `distance` | string | no | `short` (40% of screen), `long` (80% of screen) | `short` |

Practical mapping:
- `up` — scroll down through a list (finger drags up, content follows)
- `down` — dismiss app drawer, return to previous home page
- `left` / `right` — switch home screen pages

Use `scroll` instead when you want to scroll inside one specific scrollable container rather than the whole screen.

**When the model uses it:** opening the app drawer (`swipe up`), navigating home screens, scrolling long pages when no scrollable container id is available.

---

## `scroll`

Scroll inside a specific scrollable node.

| Arg | Type | Required | Values |
|-----|------|----------|--------|
| `id` | integer | yes | Must be a scrollable node |
| `direction` | string | yes | `up`, `down`, `left`, `right` |

Same finger-direction convention as `swipe`. The gesture is centered on the node.

Only use this for containers whose class clearly names a scrollable container (RecyclerView, ListView, ScrollView). On many devices, using `scroll` on a FrameLayout or ViewGroup root triggers a dismiss gesture instead of a scroll.

**When the model uses it:** scrolling a settings list, a contacts list, a RecyclerView feed.

---

## `press_key`

Press a hardware or system key.

| Arg | Type | Required | Allowed values |
|-----|------|----------|----------------|
| `name` | string | yes | `back`, `home`, `recents`, `enter` |

Any value outside this whitelist returns an error without touching the device.

**When the model uses it:** navigating back, returning to the home screen, submitting a form via the enter key, opening the recents/multitask screen.

---

## `wait`

Pause execution.

| Arg | Type | Required | Notes |
|-----|------|----------|-------|
| `seconds` | number | yes | Clamped to [0, 10] regardless of the value passed |

**When the model uses it:** waiting for a loading spinner, an animation to complete, or a network operation before the next observation.

---

## `show_screen`

Request a screenshot attached to the next observation.

No arguments.

The current turn returns immediately with `"screenshot will be attached to next observation"`. On the next turn, `dump_hierarchy` and `screenshot` are fetched concurrently, and the screenshot is sent as an inline PNG part alongside the Observation text.

Screenshots are written to `screenshots/turn-NNN.png` in the run directory.

**When the model uses it:** canvas-rendered apps, games, WebViews, situations where the UI tree lacks enough context to decide the next action.

---

## `open_notifications`

Pull down the system notification shade.

No arguments.

Uses `adb shell cmd statusbar expand-notifications` (Android 9+, no root).

After this call, the next `dump_hierarchy` will include the notification shade contents in the Observation.

**When the model uses it:** tasks involving notifications, ongoing alerts, or status-bar information.

---

## `close_notifications`

Collapse the notification shade.

No arguments.

Uses `adb shell cmd statusbar collapse`.

**When the model uses it:** after inspecting notifications, to return to the previous screen.

---

## `done`

End the task run.

| Arg | Type | Required | Notes |
|-----|------|----------|-------|
| `success` | boolean | yes | `true` if the task was completed, `false` otherwise |
| `reason` | string | yes | Human-readable explanation |

Calling `done` terminates the agent loop immediately. The `reason` is written to `result.json` and printed to the terminal.

**When the model uses it:** every run ends here — either successful completion or an explicit statement that the task is impossible or failed.
