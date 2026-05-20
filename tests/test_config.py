from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from androidharness.config import (
    CONFIG_HEADER,
    AndroidHarnessConfig,
    ConfigError,
    DefaultsConfig,
    LoggingConfig,
    MemoryConfig,
    PerceptionConfig,
    PolicyConfig,
    ProvidersConfig,
    ThrottlerConfig,
    default_config_path,
    load_config,
    save_config,
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
    assert pc.screenshot_quantized is False


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


def test_default_config_path_is_under_home_androidharness(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    assert default_config_path() == tmp_path / ".androidharness" / "config.yaml"


def test_default_config_path_respects_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom.yaml"
    monkeypatch.setenv("ANDROIDHARNESS_CONFIG", str(custom))
    assert default_config_path() == custom


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "does_not_exist.yaml")
    assert cfg == AndroidHarnessConfig()


def test_load_config_empty_file_returns_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg == AndroidHarnessConfig()


def test_load_config_partial_yaml_merges_with_defaults(tmp_path):
    p = tmp_path / "partial.yaml"
    p.write_text("defaults:\n  model: gemini-2.5-pro\n  max_turns: 80\n")
    cfg = load_config(p)
    assert cfg.defaults.model == "gemini-2.5-pro"
    assert cfg.defaults.max_turns == 80
    # Unspecified fields keep their defaults
    assert cfg.defaults.wall_clock_s == 600.0
    assert cfg.policy.default_mode == "auto"


def test_load_config_malformed_yaml_raises_config_error(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("defaults: : : oops\n")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert str(p) in str(exc.value)


def test_load_config_validation_failure_raises_config_error(tmp_path):
    p = tmp_path / "bad_schema.yaml"
    p.write_text("defaults:\n  max_turns: -3\n")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "max_turns" in str(exc.value)


def test_save_then_load_round_trip(tmp_path):
    src = AndroidHarnessConfig(
        defaults={"model": "gemini-2.5-pro", "max_turns": 25},
        policy={"default_mode": "confirm"},
    )
    p = tmp_path / "config.yaml"
    save_config(src, p)
    loaded = load_config(p)
    assert loaded == src


def test_save_config_creates_parent_directories(tmp_path):
    p = tmp_path / "nested" / "subdir" / "config.yaml"
    save_config(AndroidHarnessConfig(), p)
    assert p.exists()


def test_save_config_writes_header_comment(tmp_path):
    p = tmp_path / "with_header.yaml"
    save_config(AndroidHarnessConfig(), p)
    text = p.read_text()
    assert text.startswith(CONFIG_HEADER)
    body = text[len(CONFIG_HEADER):]
    # Body must be valid YAML that round-trips through pydantic
    parsed = yaml.safe_load(body)
    assert parsed["version"] == 1
