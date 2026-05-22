from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_general_renders_current_defaults(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/general")
    assert resp.status_code == 200
    body = resp.text
    assert "max_turns" in body
    assert "40" in body  # the default
    assert "gemini-2.5-flash" in body


def test_patch_config_general_valid_writes_and_returns_success(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/general",
        data={
            "model": "gemini-2.5-pro",
            "max_turns": "20",
            "wall_clock_s": "300",
            "runs_dir": "./runs",
            "logs_dir": "./logs",
        },
    )
    assert resp.status_code == 200
    assert "saved" in resp.text.lower() or "banner-ok" in resp.text

    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.model == "gemini-2.5-pro"
    assert reloaded.defaults.max_turns == 20


def test_patch_config_general_invalid_does_not_write_and_shows_field_error(
    tmp_path: Path,
):
    client, cfg_path = _client(tmp_path)
    # max_turns must be > 0
    resp = client.patch(
        "/config/general",
        data={
            "model": "gemini-2.5-pro",
            "max_turns": "0",
            "wall_clock_s": "300",
            "runs_dir": "./runs",
            "logs_dir": "./logs",
        },
    )
    assert resp.status_code == 200  # 200 with error markup, not 4xx — HTMX swaps the body
    assert "banner-err" in resp.text
    assert "max_turns" in resp.text

    # File untouched (or never created)
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.defaults.max_turns == 40
