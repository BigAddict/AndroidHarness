# Getting started

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11 | Pinned in `.python-version`; `uv` handles this automatically |
| [uv](https://github.com/astral-sh/uv) | Package manager — replaces pip+venv |
| ADB (Android Debug Bridge) | Part of the Android SDK Platform Tools |
| Android device or emulator | USB debugging enabled; confirmed visible in `adb devices` |
| `GOOGLE_API_KEY` | A Gemini API key from [Google AI Studio](https://aistudio.google.com) |

## Install

```bash
git clone <repo>
cd AndroidHarness
uv sync          # creates .venv, installs all deps
```

## First run

```bash
# 1. Confirm ADB sees your device
adb devices

# 2. Set your key
export GOOGLE_API_KEY=sk-...

# 3. Run a task
uv run androidharness run "Open Settings and show the About Phone screen"
```

The CLI prints the run directory, final status, and exits 0 on success, 1 on failure.

```
logs: logs/androidharness.log
run dir: runs/20260520T174908Z-7dfe2c
status:  done
success: True
reason:  Reached the About Phone screen successfully.
turns:   6
```

## Multiple devices

With more than one device attached, pass `--serial` or `--device-index`:

```bash
uv run androidharness devices          # list all connected devices
uv run androidharness run "..." --serial R92XA0AB89Y
uv run androidharness run "..." --device-index 1
```

Passing both flags is an error. With a single device attached, no flag is needed.

## Key CLI flags for `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `gemini-2.5-flash` | Any model id accepted by `google-genai` |
| `--max-turns` | `40` | Hard cap on agent turns before `max_turns` termination |
| `--wall-clock` | `600` | Seconds before `timeout` termination |
| `--run-dir` | `./runs` | Root directory for run artifacts |
| `--logs-dir` | `./logs` | Directory for the rotating log file |
| `--config` | `~/.androidharness/config.yaml` | Override the config file path |

All defaults come from the config file; CLI flags override them for a single run.

## Troubleshooting

**`no devices connected (check 'adb devices')`**
Run `adb devices`. If the list is empty, ensure USB debugging is on and the device is authorized.

**`GOOGLE_API_KEY env var is not set`**
Export the variable before running, or add it to your shell profile.

**`config already exists at ~/.androidharness/config.yaml`**
`androidharness config init --force` to regenerate defaults.

**The agent hits `max_turns` without calling `done()`**
Increase `--max-turns` or examine `turns.jsonl` to see where it stalled. The no-progress detector in the agent will inject a `NO_PROGRESS` warning and suggest alternate tactics, but some tasks genuinely need more turns.
