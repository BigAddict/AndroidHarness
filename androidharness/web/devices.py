"""Wrap androidharness.device.list_devices for the Settings UI.

Returns an empty list on any adb failure so the Devices panel still renders
when adb is missing or no devices are connected.
"""

from __future__ import annotations

import subprocess

from androidharness.device import DeviceInfo, list_devices


def list_adb_devices() -> list[DeviceInfo]:
    try:
        return list_devices()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


__all__ = ["list_adb_devices"]
