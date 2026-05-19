# AndroidHarness

AI harness for driving real Android phones over ADB with Gemini 2.5 Flash.

## Quickstart

```bash
# 1. Connect a device and confirm adb sees it
adb devices

# 2. Set your Gemini key
export GOOGLE_API_KEY=...

# 3. Install
uv sync

# 4. Run a task
uv run androidharness run "Open Settings and toggle Wi-Fi off"
```

Use `uv run androidharness devices` to list attached devices, and `--serial`/`--device-index` to choose between multiples.

Each run writes artifacts to `./runs/<timestamp>-<short-id>/`:

- `meta.json` — task, model, device.
- `turns.jsonl` — observation + tool call + result per turn.
- `result.json` — final status, success, reason.
- `screenshots/turn-<n>.png` — only when the model requested `show_screen()` that turn.

## Architecture

See `docs/superpowers/specs/2026-05-19-android-ai-harness-design.md`.
