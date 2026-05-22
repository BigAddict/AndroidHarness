from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_logging_renders_current_values(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/logging")
    assert resp.status_code == 200
    body = resp.text
    assert "INFO" in body  # default level
    assert "10" in body    # default rotation_mb


def test_patch_config_logging_valid_writes(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "DEBUG", "rotation_mb": "25"},
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.logging.level == "DEBUG"
    assert reloaded.logging.rotation_mb == 25


def test_patch_config_logging_invalid_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "DEBUG", "rotation_mb": "0"},  # must be > 0
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.logging.rotation_mb == 10


def test_patch_config_logging_rejects_unknown_level(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "TRACE", "rotation_mb": "10"},  # not in LogLevel literal
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    assert "level" in resp.text
