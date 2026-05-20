from __future__ import annotations

import pytest
from pydantic import ValidationError

from androidharness.config import (
    AndroidHarnessConfig,
    DefaultsConfig,
    LoggingConfig,
    MemoryConfig,
    PerceptionConfig,
    PolicyConfig,
    ProvidersConfig,
    ThrottlerConfig,
)


def test_default_config_is_constructable_with_no_args():
    cfg = AndroidHarnessConfig()
    assert cfg.version == 1
    assert isinstance(cfg.defaults, DefaultsConfig)
    assert isinstance(cfg.providers, ProvidersConfig)
    assert isinstance(cfg.throttler, ThrottlerConfig)
    assert isinstance(cfg.policy, PolicyConfig)
    assert isinstance(cfg.memory, MemoryConfig)
    assert isinstance(cfg.perception, PerceptionConfig)
    assert isinstance(cfg.logging, LoggingConfig)


def test_defaults_section_field_values():
    d = DefaultsConfig()
    assert d.model == "gemini-2.5-flash"
    assert d.max_turns == 40
    assert d.wall_clock_s == 600.0
    assert d.runs_dir == "./runs"
    assert d.logs_dir == "./logs"
    assert d.device_serial is None


def test_policy_default_mode_and_per_tool_empty():
    p = PolicyConfig()
    assert p.default_mode == "auto"
    assert p.per_tool == {}


def test_throttler_disabled_by_default_with_empty_buckets():
    t = ThrottlerConfig()
    assert t.enabled is False
    assert t.buckets == {}


def test_memory_disabled_by_default_with_60_day_retention():
    m = MemoryConfig()
    assert m.enabled is False
    assert m.embedding_model == "gemini-text-embedding-004"
    assert m.retention_days == 60


def test_perception_all_compression_steps_off_by_default():
    pc = PerceptionConfig()
    assert pc.sibling_collapse is False
    assert pc.viewport_filter is False
    assert pc.resource_id_in_render is False


def test_logging_defaults():
    log = LoggingConfig()
    assert log.level == "INFO"
    assert log.rotation_mb == 10


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValidationError) as exc:
        AndroidHarnessConfig(unknown_section={})
    assert "unknown_section" in str(exc.value)


def test_unknown_field_in_subsection_rejected():
    with pytest.raises(ValidationError) as exc:
        AndroidHarnessConfig(defaults={"typo_field": 1})
    assert "typo_field" in str(exc.value)


def test_invalid_log_level_rejected():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(logging={"level": "TOTALLY_INVALID"})


def test_invalid_policy_mode_rejected():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(policy={"default_mode": "explode"})


def test_max_turns_must_be_positive():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(defaults={"max_turns": 0})


def test_wall_clock_must_be_positive():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(defaults={"wall_clock_s": -1})


def test_version_must_be_one():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(version=2)
