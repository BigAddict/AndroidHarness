# Shared fixtures will be added as modules land.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeDevice:
    serial: str = "FAKE"
    model: str = "FakePixel"
    hierarchy_xml: str = "<hierarchy rotation='0'></hierarchy>"
    screenshot_bytes: bytes = b"PNGFAKE"
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def dump_hierarchy(self) -> str:
        self.calls.append(("dump_hierarchy", {}))
        return self.hierarchy_xml

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot", {}))
        return self.screenshot_bytes

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", {"x": x, "y": y}))

    def long_press(self, x: int, y: int, duration_ms: int) -> None:
        self.calls.append(("long_press", {"x": x, "y": y, "duration_ms": duration_ms}))

    def type_text(self, x: int, y: int, text: str, replace: bool) -> None:
        self.calls.append(("type_text", {"x": x, "y": y, "text": text, "replace": replace}))

    def swipe(self, direction: str, distance: str) -> None:
        self.calls.append(("swipe", {"direction": direction, "distance": distance}))

    def scroll(self, x: int, y: int, direction: str) -> None:
        self.calls.append(("scroll", {"x": x, "y": y, "direction": direction}))

    def press_key(self, name: str) -> None:
        self.calls.append(("press_key", {"name": name}))

    def wait(self, seconds: float) -> None:
        self.calls.append(("wait", {"seconds": seconds}))


@pytest.fixture
def fake_device() -> FakeDevice:
    return FakeDevice()


@dataclass
class _Scripted:
    tool_calls: list  # list[ToolCall-like dicts: {"name": str, "args": dict}]
    index: int = 0


class FakeGeminiClient:
    """Scripted Gemini stand-in. Returns the next pre-canned tool call per generate()."""

    def __init__(self, tool_calls: list[dict]):
        self._script = _Scripted(tool_calls=tool_calls)
        self.generate_calls: list[dict] = []

    def generate(self, *, model, system_instruction, contents, tools):
        self.generate_calls.append(
            {"model": model, "system_instruction": system_instruction,
             "contents": contents, "tools": tools}
        )
        idx = self._script.index
        if idx >= len(self._script.tool_calls):
            raise AssertionError("FakeGeminiClient ran out of scripted tool calls")
        self._script.index += 1
        return self._script.tool_calls[idx]


@pytest.fixture
def fake_gemini():
    def _make(tool_calls):
        return FakeGeminiClient(tool_calls=tool_calls)
    return _make
