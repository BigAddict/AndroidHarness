from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class ProvidersConfig(BaseModel):
    """Placeholder — fleshed out in milestone 2 (LiteLLM provider seam)."""
    model_config = _STRICT


class ThrottlerConfig(BaseModel):
    """Placeholder — fleshed out in milestone 3 (token bucket + Router)."""
    model_config = _STRICT

    enabled: bool = False
    buckets: dict[str, dict] = Field(default_factory=dict)


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
