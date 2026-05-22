from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_throttler_renders_current_values(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/throttler")
    assert resp.status_code == 200
    assert "enabled" in resp.text
    assert "cooldown_seconds" in resp.text


def test_patch_config_throttler_enables_with_one_bucket(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={
            "enabled": "true",
            "cooldown_seconds": "30",
            "num_retries": "3",
            "bucket_keys": "gemini/gemini-2.5-flash",
            "bucket.gemini/gemini-2.5-flash.rpm": "60",
            "bucket.gemini/gemini-2.5-flash.tpm": "100000",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.throttler.enabled is True
    assert reloaded.throttler.cooldown_seconds == 30
    assert reloaded.throttler.buckets["gemini/gemini-2.5-flash"].rpm == 60
    assert reloaded.throttler.buckets["gemini/gemini-2.5-flash"].tpm == 100000


def test_patch_config_throttler_empty_caps_become_none(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={
            "enabled": "false",
            "cooldown_seconds": "60",
            "num_retries": "2",
            "bucket_keys": "openai/gpt-4o-mini",
            "bucket.openai/gpt-4o-mini.rpm": "",
            "bucket.openai/gpt-4o-mini.tpm": "",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.throttler.buckets["openai/gpt-4o-mini"].rpm is None
    assert reloaded.throttler.buckets["openai/gpt-4o-mini"].tpm is None


def test_patch_config_throttler_invalid_cooldown_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={"enabled": "true", "cooldown_seconds": "0", "num_retries": "2"},
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.throttler.cooldown_seconds == 60  # default
