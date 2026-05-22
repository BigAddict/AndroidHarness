from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

import uiautomator2 as u2


class Device(Protocol):
    serial: str
    model: str

    def dump_hierarchy(self) -> str: ...
    def screenshot(self) -> bytes: ...
    def tap(self, x: int, y: int) -> None: ...
    def long_press(self, x: int, y: int, duration_ms: int) -> None: ...
    def type_text(self, x: int, y: int, text: str, replace: bool) -> None: ...
    def swipe(self, direction: str, distance: str) -> None: ...
    def scroll(self, x: int, y: int, direction: str) -> None: ...
    def press_key(self, name: str) -> None: ...
    def wait(self, seconds: float) -> None: ...
    def open_notifications(self) -> None: ...
    def close_notifications(self) -> None: ...


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    model: str


def list_devices() -> list[DeviceInfo]:
    out = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, check=True, timeout=5
    ).stdout
    serials = [
        line.split("\t", 1)[0]
        for line in out.splitlines()[1:]
        if line.strip() and line.endswith("device")
    ]
    infos: list[DeviceInfo] = []
    for serial in serials:
        try:
            model = (
                subprocess.run(
                    ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                ).stdout.strip()
                or "unknown"
            )
        except subprocess.CalledProcessError:
            model = "unknown"
        infos.append(DeviceInfo(serial=serial, model=model))
    return infos


_KEY_WHITELIST = {"back", "home", "recents", "enter"}


class UIAutomatorDevice:
    def __init__(self, serial: str, u2_device: u2.Device, model: str):
        self.serial = serial
        self.model = model
        self._d = u2_device

    @classmethod
    def connect(cls, serial: str) -> UIAutomatorDevice:
        d = u2.connect(serial)
        model = d.info.get("productName") or d.shell("getprop ro.product.model").output.strip()
        return cls(serial=serial, u2_device=d, model=model or "unknown")

    def dump_hierarchy(self) -> str:
        return self._d.dump_hierarchy()

    def screenshot(self) -> bytes:
        import io

        buf = io.BytesIO()
        self._d.screenshot().save(buf, format="PNG")
        return buf.getvalue()

    def tap(self, x: int, y: int) -> None:
        self._d.click(x, y)

    def long_press(self, x: int, y: int, duration_ms: int) -> None:
        self._d.long_click(x, y, duration=duration_ms / 1000)

    def type_text(self, x: int, y: int, text: str, replace: bool) -> None:
        # Use the accessibility API (set_text) rather than send_keys, which
        # requires uiautomator2 to swap the active IME to FastInputIME and
        # commonly fails on lock screens / secure windows — the user's prior
        # incident chain. set_text writes directly through the focused
        # AccessibilityNode; no IME swap, no shell-out to adb.
        #
        # set_text always overwrites the field's full content, so to honor
        # the `replace=False` (append) contract we have to read the existing
        # text and concatenate ourselves. Otherwise an agent issuing several
        # `type` calls to build up a long body sees each call silently wipe
        # the field.
        self._d.click(x, y)
        focused = self._d(focused=True)
        if replace:
            focused.set_text(text)
        else:
            existing = focused.get_text() or ""
            focused.set_text(existing + text)

    def swipe(self, direction: str, distance: str) -> None:
        w, h = self._d.window_size()
        cx, cy = w // 2, h // 2
        frac = 0.4 if distance == "short" else 0.8
        dx = int(w * frac / 2)
        dy = int(h * frac / 2)
        # Swipe direction == finger direction; content moves opposite.
        moves = {
            "up": (cx, cy + dy, cx, cy - dy),
            "down": (cx, cy - dy, cx, cy + dy),
            "left": (cx + dx, cy, cx - dx, cy),
            "right": (cx - dx, cy, cx + dx, cy),
        }
        if direction not in moves:
            raise ValueError(f"unknown swipe direction: {direction}")
        x1, y1, x2, y2 = moves[direction]
        self._d.swipe(x1, y1, x2, y2, duration=0.2)

    def scroll(self, x: int, y: int, direction: str) -> None:
        # Reuse swipe centered on the node.
        w, h = self._d.window_size()
        dx = w // 4
        dy = h // 4
        moves = {
            "up": (x, y + dy, x, y - dy),
            "down": (x, y - dy, x, y + dy),
            "left": (x + dx, y, x - dx, y),
            "right": (x - dx, y, x + dx, y),
        }
        if direction not in moves:
            raise ValueError(f"unknown scroll direction: {direction}")
        x1, y1, x2, y2 = moves[direction]
        self._d.swipe(x1, y1, x2, y2, duration=0.2)

    def press_key(self, name: str) -> None:
        if name not in _KEY_WHITELIST:
            raise ValueError(f"key not allowed: {name}")
        self._d.press(name)

    def wait(self, seconds: float) -> None:
        time.sleep(min(seconds, 10.0))

    def open_notifications(self) -> None:
        # `cmd statusbar expand-notifications` works on Android 9+ without root.
        subprocess.run(
            ["adb", "-s", self.serial, "shell", "cmd", "statusbar", "expand-notifications"],
            capture_output=True, text=True, check=True, timeout=5,
        )

    def close_notifications(self) -> None:
        subprocess.run(
            ["adb", "-s", self.serial, "shell", "cmd", "statusbar", "collapse"],
            capture_output=True, text=True, check=True, timeout=5,
        )
