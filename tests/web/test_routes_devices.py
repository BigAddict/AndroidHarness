from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from androidharness.device import DeviceInfo
from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_devices_lists_live_adb_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "androidharness.web.routes.list_adb_devices",
        lambda: [DeviceInfo(serial="ABC123", model="Pixel 9")],
    )
    client, _ = _client(tmp_path)
    resp = client.get("/panel/devices")
    assert resp.status_code == 200
    assert "ABC123" in resp.text
    assert "Pixel 9" in resp.text


def test_get_panel_devices_handles_no_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("androidharness.web.routes.list_adb_devices", lambda: [])
    client, _ = _client(tmp_path)
    resp = client.get("/panel/devices")
    assert resp.status_code == 200
    assert "no devices" in resp.text.lower()


def test_patch_config_devices_sets_default_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "androidharness.web.routes.list_adb_devices",
        lambda: [DeviceInfo(serial="ABC123", model="Pixel 9")],
    )
    client, cfg_path = _client(tmp_path)
    resp = client.patch("/config/devices", data={"device_serial": "ABC123"})
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.device_serial == "ABC123"


def test_patch_config_devices_empty_clears_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("androidharness.web.routes.list_adb_devices", lambda: [])
    client, cfg_path = _client(tmp_path)
    # Pre-seed a default
    pre = ConfigStore(cfg_path).load()
    pre.defaults.device_serial = "OLD"
    ConfigStore(cfg_path).write(pre)

    resp = client.patch("/config/devices", data={"device_serial": ""})
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.device_serial is None
