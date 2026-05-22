# Configuration

## Editing the config

Two ways:

* **Settings UI:** `uv run androidharness serve` (requires the `[web]` extra), then open <http://127.0.0.1:8000>. Inline validation, atomic writes; runs started after the save pick up the new values.
* **Direct YAML:** edit `~/.androidharness/config.yaml` (or `$ANDROIDHARNESS_CONFIG`). Runs read config at start, so re-run after editing.

The Settings UI and the CLI both write the same file. API keys are referenced by env-var name only — the UI never reads or stores the key itself.

## Config file location

Default: `~/.androidharness/config.yaml`

Override with the `ANDROIDHARNESS_CONFIG` environment variable:

```bash
export ANDROIDHARNESS_CONFIG=/path/to/my-config.yaml
```

Or per-command with `--config`:

```bash
uv run androidharness run "..." --config ./local-config.yaml
```

If the file does not exist, all defaults apply automatically. The file is only required when you want to change a default.

## The `config` subcommand

```bash
androidharness config path             # print the resolved path (no file I/O)
androidharness config init             # write a default config to that path
androidharness config init --force     # overwrite an existing file
androidharness config show             # print the loaded config as YAML
androidharness config validate         # exits 0 on valid, 1 with error message
```

`config show` merges file values with hardcoded defaults and prints the result — useful for seeing the effective config even before `init`.

## Schema reference

All fields use `extra="forbid"` — unknown keys cause a validation error.

### Top level

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | `1` (literal) | `1` | Schema version. Only `1` is valid. |
| `defaults` | `DefaultsConfig` | see below | Per-run defaults |
| `providers` | `ProvidersConfig` | see below | Which LLM provider the CLI uses |
| `throttler` | `ThrottlerConfig` | see below | Rate-limit budgets + Router fallback chains |
| `policy` | `PolicyConfig` | see below | Destructive-action gating (confirm/dry-run/deny) |
| `memory` | `MemoryConfig` | see below | Episodic memory — milestone 12 |
| `perception` | `PerceptionConfig` | see below | Perception feature flags |
| `logging` | `LoggingConfig` | see below | Log level and rotation |

### `defaults`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"gemini-2.5-flash"` | Model id passed to the Gemini API |
| `max_turns` | int > 0 | `40` | Hard turn limit before `max_turns` termination |
| `wall_clock_s` | float > 0 | `600.0` | Seconds before `timeout` termination |
| `runs_dir` | string | `"./runs"` | Root directory for run artifact directories |
| `logs_dir` | string | `"./logs"` | Directory for the rotating log file |
| `device_serial` | string or null | `null` | Pre-select a device; bypasses ambiguity check when set |

### `providers`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `use_litellm` | bool | `true` | When `true`, routes all calls through `LiteLLMClient`. Set `false` to fall back to the v1 direct-Gemini `GoogleGenaiClient` (escape hatch if LiteLLM misbehaves). |
| `default` | string | `"gemini"` | Key into `entries`; selects which provider's `api_key_env` is required and which prefix is added to bare model names. |
| `entries` | dict[str, `ProviderEntry`] | gemini / anthropic / openai built-ins | Per-provider record: `api_key_env` (env var name holding the key) and `default_model` (LiteLLM-shaped `provider/model` id). |

The default `entries` map ships with three providers — `gemini` (`GEMINI_API_KEY`, `gemini/gemini-2.5-flash`), `anthropic` (`ANTHROPIC_API_KEY`, `anthropic/claude-haiku-4-5`), and `openai` (`OPENAI_API_KEY`, `openai/gpt-4o-mini`). To use Claude or GPT, set `providers.default` to `anthropic` or `openai` and export the matching API key.

Bare model names (e.g. `gemini-2.5-flash`, set via `defaults.model` or `--model`) are automatically prefixed with `providers.default` before they reach LiteLLM — so the user rarely needs to type the prefix by hand. Fully-qualified names (`anthropic/claude-haiku-4-5`) pass through unchanged.

#### Logical models (fallback chains)

`providers.logical_models` defines alias names that resolve to an ordered chain of concrete deployments. The first entry is the primary; on rate-limit / quota errors the Router falls through to the next entry.

```yaml
providers:
  logical_models:
    fast:
      - gemini/gemini-2.5-flash
      - anthropic/claude-haiku-4-5
      - openai/gpt-4o-mini
    smart:
      - anthropic/claude-sonnet-4-6
```

With this config, `androidharness run "..." --model fast` starts on Gemini and falls back to Claude then GPT-4o-mini on rate-limit errors. Every entry must be in `provider/model` form. When `throttler.enabled` is true, every distinct provider in any chain must have its `api_key_env` set; the CLI checks this up-front.

### `throttler`

Routes every LLM call through `litellm.Router` when enabled, adding proactive rate limiting and reactive fallback on 429 / quota errors.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | When true, the CLI uses `LiteLLMRouterClient` instead of the direct `LiteLLMClient`. |
| `cooldown_seconds` | int > 0 | `60` | How long Router waits before re-trying a rate-limited deployment. |
| `num_retries` | int >= 0 | `2` | Retries against the same deployment before consulting the fallback list. |
| `buckets` | dict[str, `BucketConfig`] | `{}` | Per-deployment rate-limit budget. Keys are LiteLLM-shaped `provider/model` ids; values are `{rpm: int?, tpm: int?}`. Both rpm and tpm are optional — `None` means no limit. |

Example:

```yaml
throttler:
  enabled: true
  cooldown_seconds: 60
  num_retries: 2
  buckets:
    gemini/gemini-2.5-flash:
      rpm: 10
      tpm: 250000
    anthropic/claude-haiku-4-5:
      rpm: 30
```

### `policy`

Gates every tool call. Lets you point the agent at your personal phone without worrying that one bad model decision wipes a chat thread or buys a subscription. The agent consults the policy between the LLM's tool choice and the device call.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_mode` | `"auto"` \| `"confirm"` \| `"dry-run"` \| `"deny"` | `"auto"` | Mode applied to any tool not named in `per_tool`. |
| `confirm_timeout_s` | int > 0 | `30` | Seconds the CLI confirm prompt waits before auto-rejecting. |
| `per_tool` | dict[str, mode] | `{type: confirm, long_press: confirm}` | Per-tool overrides. The defaults come from spec §4 — typing and long-press require explicit confirmation on personal devices. |

Modes:
- `auto` — call the tool as usual.
- `confirm` — prompt on the CLI (`[y/N]`); rejection returns `ok=False` to the agent, which can react.
- `dry-run` — skip the device call; return `ok=True` with a `"dry-run: would have called X"` message so the agent can walk a plan end-to-end without touching the phone.
- `deny` — skip the call; return `ok=False`.

Example:

```yaml
policy:
  default_mode: auto
  confirm_timeout_s: 15
  per_tool:
    type: deny           # never type anywhere unattended
    long_press: confirm  # ask before destructive long-presses
    tap: auto            # taps are fine
```

CLI override for a single run:

```bash
uv run androidharness run "..." --policy "tap=confirm,type=deny"
```

`--policy` is parsed as a comma-separated `tool=mode` list and merges over `policy.per_tool` for that single run. Modes outside `{auto, confirm, dry-run, deny}` are rejected.

### `memory`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Whether episodic memory is active |
| `embedding_model` | string | `"gemini-text-embedding-004"` | Embedding model for indexing |
| `retention_days` | int > 0 | `60` | Memories older than this are deprioritized on retrieval |

### `perception`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sibling_collapse` | bool | `false` | Collapse long runs of identical siblings (milestone 6) |
| `viewport_filter` | bool | `false` | Drop off-screen and `visibility="gone"` nodes (milestone 11 step 2, but available now — the code is shipped) |
| `resource_id_in_render` | bool | `false` | Append resource-id suffix to node summaries (milestone 11 step 3) |
| `screenshot_quantized` | bool | `false` | Quantize screenshots to 256 colors before sending to Gemini |

### `logging`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | `"DEBUG"` \| `"INFO"` \| `"WARNING"` \| `"ERROR"` \| `"CRITICAL"` | `"INFO"` | Log level for the `androidharness` logger |
| `rotation_mb` | int > 0 | `10` | Max size per log file in megabytes |

> Note: `logging.level` is stored in config but `logging_setup.py` currently hardcodes `INFO` and does not read this field. `logging.rotation_mb` is similarly not yet wired — the setup module hardcodes 10 MB. Both fields are placeholders that will be connected when the Settings UI (milestone 5) lands.

## Example config

```yaml
version: 1
defaults:
  model: gemini-2.5-flash
  max_turns: 60
  wall_clock_s: 900.0
  runs_dir: ./runs
  logs_dir: ./logs
  device_serial: R92XA0AB89Y
perception:
  viewport_filter: true
  screenshot_quantized: true
```
