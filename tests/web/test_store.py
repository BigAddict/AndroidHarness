from __future__ import annotations

from pathlib import Path

import pytest

from androidharness.config import AndroidHarnessConfig, ConfigError
from androidharness.web.store import ConfigStore


def test_load_missing_file_returns_defaults(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    cfg = store.load()
    assert isinstance(cfg, AndroidHarnessConfig)
    assert cfg.version == 1
    assert cfg.providers.default == "gemini"


def test_round_trip_preserves_user_edits(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    cfg = store.load()
    cfg.policy.confirm_timeout_s = 7
    store.write(cfg)

    reloaded = ConfigStore(tmp_path / "config.yaml").load()
    assert reloaded.policy.confirm_timeout_s == 7


def test_write_is_atomic_no_tmp_file_left_behind(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    store.write(store.load())

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"atomic write leaked tmp files: {leftovers}"


def test_write_replaces_existing_file_atomically(tmp_path: Path, monkeypatch):
    """If os.replace is interrupted, the original file must still be intact."""
    config_path = tmp_path / "config.yaml"
    store = ConfigStore(config_path)

    original = store.load()
    original.policy.confirm_timeout_s = 5
    store.write(original)
    original_bytes = config_path.read_bytes()

    # Simulate a crash inside os.replace — the tmp must exist with new content
    # but the real file must keep its old content.
    def boom(src, dst):
        raise RuntimeError("simulated power loss")

    monkeypatch.setattr("os.replace", boom)

    updated = store.load()
    updated.policy.confirm_timeout_s = 99
    with pytest.raises(RuntimeError, match="simulated power loss"):
        store.write(updated)

    assert config_path.read_bytes() == original_bytes


def test_malformed_yaml_raises_config_error(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("policy: : :\n  not yaml\n")
    store = ConfigStore(path)
    with pytest.raises(ConfigError):
        store.load()


def test_unknown_top_level_key_raises_config_error(tmp_path: Path):
    """Pydantic extra='forbid' must catch typos so we don't silently drop them."""
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\nbogus_key: 42\n")
    store = ConfigStore(path)
    with pytest.raises(ConfigError):
        store.load()
