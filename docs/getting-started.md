# Getting started

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11 | Pinned in `.python-version`; `uv` handles this automatically |
| [uv](https://github.com/astral-sh/uv) | Package manager — replaces pip+venv |
| ADB (Android Debug Bridge) | Part of the Android SDK Platform Tools |
| Android device or emulator | USB debugging enabled; confirmed visible in `adb devices` |
| Provider API key | `GEMINI_API_KEY` for the default Gemini provider — get one from [Google AI Studio](https://aistudio.google.com). For Anthropic, set `ANTHROPIC_API_KEY`; for OpenAI, `OPENAI_API_KEY`. The key required is determined by `providers.default` in your config. |

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

# 2. Set your key (this is the default; see configuration.md for other providers)
export GEMINI_API_KEY=...

# 3. Run a task
uv run androidharness run "Open Settings and show the About Phone screen"
```

The CLI streams the agent's progress to stderr in real time — every turn, every tool call, every policy decision — so you can watch the run unfold. The final summary (run directory, status, exit code) is written to stdout once the run completes, which keeps the structured output clean if you pipe it.

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
| `--model` | `gemini-2.5-flash` | Any LiteLLM-supported model id. Bare names get the configured provider prefixed automatically (so `gemini-2.5-flash` becomes `gemini/gemini-2.5-flash`); pass a fully-qualified name like `anthropic/claude-haiku-4-5` to override. |
| `--max-turns` | `40` | Hard cap on agent turns before `max_turns` termination |
| `--wall-clock` | `600` | Seconds before `timeout` termination |
| `--run-dir` | `./runs` | Root directory for run artifacts |
| `--logs-dir` | `./logs` | Directory for the rotating log file |
| `--config` | `~/.androidharness/config.yaml` | Override the config file path |
| `--policy` | _none_ | Per-tool policy override, e.g. `tap=confirm,type=deny` (see the [Policy](#policy--gating-destructive-actions) section). |

All defaults come from the config file; CLI flags override them for a single run.

## Previewing the screen the agent will see

`androidharness peek` is a read-only window into the perception layer — it dumps the connected device's current screen exactly the way the agent would observe it, without invoking the LLM, firing a tool, or changing device state.

```bash
uv run androidharness peek                    # default-rendered Observation
uv run androidharness peek --raw-xml          # the unprocessed uiautomator2 XML
uv run androidharness peek --with-resource-ids
uv run androidharness peek --viewport-filter  # drop off-screen / gone nodes (override config)
```

Use it before a `run` to confirm the screen is in the state you expect, or to debug why the agent is misidentifying a node — what you see in `peek` is byte-for-byte what the model sees.

## Logical model names and the throttler

If you've set up logical model names in your config, pass them as `--model`:

```bash
uv run androidharness run "..." --model fast
```

With `throttler.enabled: true`, calls flow through `litellm.Router` so they respect per-deployment RPM / TPM budgets and fall back to the next entry in the chain on rate-limit errors. See [configuration.md](configuration.md#throttler) for the on-disk shape.

The throttler is off by default — until you've actually hit a rate limit, the direct `LiteLLMClient` is simpler and fine.

## Policy — gating destructive actions

Pointing the agent at your personal phone? The `policy` gate is the safety net. Out of the box, `type` and `long_press` require a `[y/N]` confirmation at the terminal before the call reaches the device; everything else (`tap`, `swipe`, `scroll`, etc.) is `auto`.

```bash
# One-off override: dry-run every tap, deny typing entirely.
uv run androidharness run "..." --policy "tap=dry-run,type=deny"
```

See [configuration.md](configuration.md#policy) for the full mode reference. The confirm prompt auto-rejects after `policy.confirm_timeout_s` (default 30s) so unattended runs can't accidentally approve destructive actions.

## Troubleshooting

**`no devices connected (check 'adb devices')`**
Run `adb devices`. If the list is empty, ensure USB debugging is on and the device is authorized.

**`<PROVIDER>_API_KEY env var is not set`**
Export the variable for whichever provider `providers.default` selects in your config (`GEMINI_API_KEY` by default).

**`config already exists at ~/.androidharness/config.yaml`**
`androidharness config init --force` to regenerate defaults.

**The agent hits `max_turns` without calling `done()`**
Increase `--max-turns` or examine `turns.jsonl` to see where it stalled. The no-progress detector in the agent will inject a `NO_PROGRESS` warning and suggest alternate tactics, but some tasks genuinely need more turns.
