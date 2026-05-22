from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_policy_renders_default_mode_and_timeout(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/policy")
    assert resp.status_code == 200
    body = resp.text
    assert "default_mode" in body
    assert "confirm_timeout_s" in body
    # The spec-mandated confirm defaults must show up.
    assert "per_tool.type" in body
    assert "per_tool.long_press" in body


def test_patch_config_policy_valid_writes(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "confirm",
            "confirm_timeout_s": "15",
            "per_tool.tap": "auto",
            "per_tool.type": "deny",
            "per_tool.long_press": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.policy.default_mode == "confirm"
    assert reloaded.policy.confirm_timeout_s == 15
    assert reloaded.policy.per_tool["type"] == "deny"


def test_patch_config_policy_invalid_timeout_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "auto",
            "confirm_timeout_s": "0",  # must be > 0
            "per_tool.type": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.policy.confirm_timeout_s == 30


def test_patch_config_policy_invalid_mode_does_not_write(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "bogus",
            "confirm_timeout_s": "30",
            "per_tool.type": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
