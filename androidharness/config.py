from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_STRICT = ConfigDict(extra="forbid")

PolicyMode = Literal["auto", "confirm", "dry-run", "deny"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DefaultsConfig(BaseModel):
    model_config = _STRICT

    model: str = "gemini-2.5-flash"
    max_turns: int = Field(default=40, gt=0)
    wall_clock_s: float = Field(default=600.0, gt=0)
    runs_dir: str = "./runs"
    logs_dir: str = "./logs"
    device_serial: str | None = None


class ProviderEntry(BaseModel):
    model_config = _STRICT

    api_key_env: str
    default_model: str


def _default_provider_entries() -> dict[str, ProviderEntry]:
    return {
        "gemini": ProviderEntry(
            api_key_env="GEMINI_API_KEY",
            default_model="gemini/gemini-2.5-flash",
        ),
        "anthropic": ProviderEntry(
            api_key_env="ANTHROPIC_API_KEY",
            default_model="anthropic/claude-haiku-4-5",
        ),
        "openai": ProviderEntry(
            api_key_env="OPENAI_API_KEY",
            default_model="openai/gpt-4o-mini",
        ),
    }


class ProvidersConfig(BaseModel):
    """Provider seam config (milestone 2).

    * `use_litellm` is an escape hatch — set False to fall back to the v1
      `GoogleGenaiClient` while LiteLLM is still bedding in.
    * `default` selects which entry of `entries` the CLI uses when the user
      doesn't pass --model.
    * Each entry names the env var holding the API key and the LiteLLM-shaped
      model identifier (`provider/model`).
    """

    model_config = _STRICT

    use_litellm: bool = True
    default: str = "gemini"
    entries: dict[str, ProviderEntry] = Field(default_factory=_default_provider_entries)
    logical_models: dict[str, list[str]] = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:  # noqa: D401  (pydantic hook)
        if self.default not in self.entries:
            raise ValueError(
                f"providers.default={self.default!r} is not a key in providers.entries "
                f"(have: {sorted(self.entries)})"
            )
        for name, chain in self.logical_models.items():
            if not chain:
                raise ValueError(
                    f"providers.logical_models[{name!r}] is empty — a logical model must "
                    "have at least one concrete model entry"
                )
            for entry in chain:
                if "/" not in entry:
                    raise ValueError(
                        f"providers.logical_models[{name!r}] entry {entry!r} is not in "
                        "`provider/model` form (e.g. 'gemini/gemini-2.5-flash')"
                    )


class BucketConfig(BaseModel):
    """Per-(provider, model) rate-limit budget. None means 'no limit'."""
    model_config = _STRICT

    rpm: int | None = Field(default=None, gt=0)
    tpm: int | None = Field(default=None, gt=0)


class ThrottlerConfig(BaseModel):
    """Token-bucket + fallback config (milestone 3).

    Routes every LLM call through `litellm.Router` when `enabled`. Each entry
    in `buckets` is keyed by the concrete LiteLLM-shaped model id
    (`provider/model`) and gives that deployment's RPM / TPM budget. The
    Router cools a deployment down for `cooldown_seconds` after a rate-limit
    error, retrying via the next entry in the matching `logical_models` chain.
    """

    model_config = _STRICT

    enabled: bool = False
    cooldown_seconds: int = Field(default=60, gt=0)
    num_retries: int = Field(default=2, ge=0)
    buckets: dict[str, BucketConfig] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    """Placeholder — fleshed out in milestone 4 (destructive-action gating)."""
    model_config = _STRICT

    default_mode: PolicyMode = "auto"
    per_tool: dict[str, PolicyMode] = Field(default_factory=dict)


class MemoryConfig(BaseModel):
    """Placeholder — fleshed out in milestone 12 (chromadb episodic memory)."""
    model_config = _STRICT

    enabled: bool = False
    embedding_model: str = "gemini-text-embedding-004"
    retention_days: int = Field(default=60, gt=0)


class PerceptionConfig(BaseModel):
    """Placeholder — toggles flip on as milestones 6, 11, 16 land."""
    model_config = _STRICT

    sibling_collapse: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False
    screenshot_quantized: bool = False


class LoggingConfig(BaseModel):
    model_config = _STRICT

    level: LogLevel = "INFO"
    rotation_mb: int = Field(default=10, gt=0)


class AndroidHarnessConfig(BaseModel):
    model_config = _STRICT

    version: Literal[1] = 1
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    throttler: ThrottlerConfig = Field(default_factory=ThrottlerConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


CONFIG_HEADER = (
    "# AndroidHarness config — see docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md\n"
    "# Generated by `androidharness config init`. Edit by hand or via the Settings UI (v2.0).\n"
    "---\n"
)


class ConfigError(RuntimeError):
    """Raised when a config file is malformed or fails schema validation."""


def default_config_path() -> Path:
    """Resolve the config path, honoring the `ANDROIDHARNESS_CONFIG` env var override."""
    override = os.environ.get("ANDROIDHARNESS_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("HOME", "~")).expanduser() / ".androidharness" / "config.yaml"


def load_config(path: Path | None = None) -> AndroidHarnessConfig:
    """Load config from disk. Missing file → defaults. Malformed → ConfigError."""
    p = Path(path) if path is not None else default_config_path()
    if not p.exists():
        return AndroidHarnessConfig()
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"failed to parse YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config at {p} must be a YAML mapping at the top level")
    try:
        return AndroidHarnessConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"config at {p} failed validation:\n{e}") from e


def save_config(config: AndroidHarnessConfig, path: Path | None = None) -> Path:
    """Serialize config to YAML with a header comment. Creates parent dirs."""
    p = Path(path) if path is not None else default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        config.model_dump(mode="json"),
        sort_keys=False,
        default_flow_style=False,
    )
    p.write_text(CONFIG_HEADER + body)
    return p
