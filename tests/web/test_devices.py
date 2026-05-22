from __future__ import annotations

import subprocess

import pytest

from androidharness.device import DeviceInfo
from androidharness.web.devices import list_adb_devices


def test_list_adb_devices_delegates_to_device_module(monkeypatch: pytest.MonkeyPatch):
    fake = [DeviceInfo(serial="ABC123", model="Pixel 9")]
    monkeypatch.setattr("androidharness.web.devices.list_devices", lambda: fake)
    assert list_adb_devices() == fake


def test_list_adb_devices_swallows_adb_failure_and_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    """adb might not be installed on the box running the UI — UI must still load."""

    def boom():
        raise subprocess.CalledProcessError(1, ["adb"])

    monkeypatch.setattr("androidharness.web.devices.list_devices", boom)
    assert list_adb_devices() == []


def test_list_adb_devices_swallows_subprocess_error(monkeypatch: pytest.MonkeyPatch):
    def boom():
        raise FileNotFoundError("adb not found")

    monkeypatch.setattr("androidharness.web.devices.list_devices", boom)
    assert list_adb_devices() == []
