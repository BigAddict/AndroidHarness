# Configuration

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
| `throttler` | `ThrottlerConfig` | see below | Rate-limit config — milestone 3 |
| `policy` | `PolicyConfig` | see below | Destructive-action gating — milestone 4 |
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

### `throttler`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Whether throttling is active |
| `buckets` | dict | `{}` | Per-(provider, model) bucket config — fleshed out in milestone 3 |

### `policy`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_mode` | `"auto"` \| `"confirm"` \| `"dry-run"` \| `"deny"` | `"auto"` | Fallback mode for tools not in `per_tool` |
| `per_tool` | dict[str, mode] | `{}` | Override mode per tool name — fleshed out in milestone 4 |

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
