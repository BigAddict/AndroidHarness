# AndroidHarness v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive, UI-tree-first AI harness that lets Gemini 2.5 Flash drive a real Android device over ADB to completion of a natural-language task.

**Architecture:** Four independently-testable Python modules — `device` (uiautomator2 wrapper), `perception` (XML hierarchy → compact numbered node list), `tools` (action vocabulary, validation, execution), `agent` (Gemini function-calling loop) — composed by a `runner` and exposed through a `cli`. UI tree is the primary observation; screenshots are an opt-in escape hatch the model requests via `show_screen()`.

**Tech Stack:** Python 3.11, uv (project + run), uiautomator2 (device automation), lxml (hierarchy parsing), google-genai (Gemini SDK), typer (CLI), Pillow (only for screenshot bytes), pytest (tests), ruff (lint+format), hatchling (build backend for the `androidharness` console script).

**Spec:** `docs/superpowers/specs/2026-05-19-android-ai-harness-design.md`

---

## File Structure

Created or modified by this plan:

| Path | Purpose |
|---|---|
| `pyproject.toml` | Modified — add build backend, runtime deps, dev deps, console script. |
| `main.py` | Deleted — replaced by package + CLI. |
| `androidharness/__init__.py` | Package marker + version. |
| `androidharness/perception.py` | XML hierarchy → `Observation` (compact node list + id→node map). Pure functions. |
| `androidharness/device.py` | `Device` protocol + `UIAutomatorDevice` (uiautomator2 wrapper) + `list_devices()`. |
| `androidharness/tools.py` | Tool dataclasses, validation, Gemini function-declaration schemas, `execute(device, tool_call, observation)`. |
| `androidharness/agent.py` | `Agent` — builds observations, calls Gemini, parses tool calls, drives the loop. |
| `androidharness/runner.py` | Orchestrates a single run: run-dir setup, JSONL turn logging, final result writing. |
| `androidharness/cli.py` | `androidharness devices` / `androidharness run`. |
| `tests/conftest.py` | Shared fixtures: `FakeDevice`, `FakeGeminiClient`. |
| `tests/test_perception.py` | Unit tests for hierarchy → observation. |
| `tests/test_tools.py` | Unit tests for validation + execution against `FakeDevice`. |
| `tests/test_agent.py` | Unit tests for the loop with `FakeGeminiClient`. |
| `tests/test_runner.py` | Tests run-dir artifacts. |
| `tests/test_device_integration.py` | Real-device integration tests, skipped without `ANDROIDHARNESS_DEVICE_SERIAL`. |
| `tests/fixtures/hierarchy_settings.xml` | Realistic uiautomator2 dump used by perception tests. |
| `tests/fixtures/hierarchy_minimal.xml` | Tiny hierarchy used by simpler tests. |

---

## Task 1: Project skeleton, deps, and tooling

**Files:**
- Modify: `pyproject.toml`
- Delete: `main.py`
- Create: `androidharness/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` (minimal — just imports for now)

- [ ] **Step 1: Replace `pyproject.toml`**

Overwrite with:

```toml
[project]
name = "androidharness"
version = "0.1.0"
description = "AI harness for driving Android devices via uiautomator2 + Gemini"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "uiautomator2>=3.5.0",
    "uiautodev>=0.14.0",
    "google-genai>=0.3.0",
    "lxml>=5.0.0",
    "pillow>=10.0.0",
    "typer>=0.12.0",
]

[project.scripts]
androidharness = "androidharness.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["androidharness"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 2: Delete the stub entry point**

Run: `rm main.py`

- [ ] **Step 3: Create the package and tests directories**

Create `androidharness/__init__.py` with:

```python
__version__ = "0.1.0"
```

Create `tests/__init__.py` empty (zero bytes).

Create `tests/conftest.py` with:

```python
# Shared fixtures will be added as modules land.
```

- [ ] **Step 4: Sync deps and verify pytest runs**

Run: `uv sync`
Run: `uv run pytest`
Expected: pytest exits 0 with "no tests ran" (or "collected 0 items").

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock androidharness tests
git rm main.py
git commit -m "chore: package skeleton, build backend, deps for v1"
```

---

## Task 2: Perception — hierarchy XML → Observation

**Files:**
- Create: `androidharness/perception.py`
- Create: `tests/test_perception.py`
- Create: `tests/fixtures/hierarchy_minimal.xml`
- Create: `tests/fixtures/hierarchy_settings.xml`

- [ ] **Step 1: Add the minimal fixture**

Create `tests/fixtures/hierarchy_minimal.xml`:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" content-desc="" clickable="true" long-clickable="false" scrollable="false" focusable="true" resource-id="com.example:id/settings_btn"/>
    <node bounds="[40,360][520,480]" class="android.widget.Button" text="Wi-Fi" content-desc="" clickable="true" long-clickable="false" scrollable="false" focusable="true" resource-id="com.example:id/wifi_btn"/>
    <node bounds="[40,520][1040,640]" class="android.widget.EditText" text="" content-desc="Search" clickable="true" long-clickable="false" scrollable="false" focusable="true" resource-id="com.example:id/search"/>
    <node bounds="[40,680][1040,800]" class="android.widget.TextView" text="Welcome back" content-desc="" clickable="false" long-clickable="false" scrollable="false" focusable="false"/>
    <node bounds="[40,820][1040,820]" class="android.widget.FrameLayout" clickable="false" long-clickable="false" scrollable="false"/>
  </node>
</hierarchy>
```

- [ ] **Step 2: Add the settings fixture**

Create `tests/fixtures/hierarchy_settings.xml`:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[0,0][1080,160]" class="android.widget.LinearLayout" clickable="false">
      <node bounds="[40,40][400,120]" class="android.widget.TextView" text="Settings" clickable="false"/>
    </node>
    <node bounds="[0,160][1080,2400]" class="androidx.recyclerview.widget.RecyclerView" clickable="false" scrollable="true" resource-id="com.android.settings:id/main_content">
      <node bounds="[40,200][1040,360]" class="android.widget.LinearLayout" clickable="true" resource-id="com.android.settings:id/network_row">
        <node bounds="[80,240][1000,320]" class="android.widget.TextView" text="Network &amp; internet" clickable="false"/>
      </node>
      <node bounds="[40,380][1040,540]" class="android.widget.LinearLayout" clickable="true" resource-id="com.android.settings:id/display_row">
        <node bounds="[80,420][1000,500]" class="android.widget.TextView" text="Display" clickable="false"/>
      </node>
      <node bounds="[40,560][1040,720]" class="android.widget.LinearLayout" clickable="true" long-clickable="true" resource-id="com.android.settings:id/about_row">
        <node bounds="[80,600][1000,680]" class="android.widget.TextView" text="About phone" clickable="false"/>
      </node>
    </node>
  </node>
</hierarchy>
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_perception.py`:

```python
from pathlib import Path

import pytest

from androidharness.perception import Node, Observation, parse_hierarchy

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_hierarchy_keeps_interactable_and_text_nodes():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    summaries = [n.summary for n in obs.nodes]
    assert summaries == [
        '[1] Button "Settings" (clickable)',
        '[2] Button "Wi-Fi" (clickable)',
        '[3] EditText placeholder="Search" (editable)',
        '[4] TextView "Welcome back"',
    ]


def test_parse_hierarchy_assigns_dense_ids_starting_at_one():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    assert [n.id for n in obs.nodes] == [1, 2, 3, 4]


def test_observation_resolve_returns_node_for_known_id():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    node = obs.resolve(1)
    assert isinstance(node, Node)
    assert node.text == "Settings"


def test_observation_resolve_raises_for_unknown_id():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    with pytest.raises(KeyError):
        obs.resolve(99)


def test_node_center_is_midpoint_of_bounds():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    node = obs.resolve(1)  # bounds=[40,200][520,320]
    assert node.center == (280, 260)


def test_settings_fixture_drops_pure_layout_containers():
    obs = parse_hierarchy(_load("hierarchy_settings.xml"))
    summaries = [n.summary for n in obs.nodes]
    assert summaries == [
        '[1] TextView "Settings"',
        '[2] RecyclerView (scrollable)',
        '[3] LinearLayout "Network & internet" (clickable)',
        '[4] LinearLayout "Display" (clickable)',
        '[5] LinearLayout "About phone" (clickable, long-clickable)',
    ]


def test_observation_render_is_newline_joined_summaries():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    rendered = obs.render()
    assert rendered.splitlines() == [n.summary for n in obs.nodes]


def test_empty_hierarchy_produces_empty_observation():
    xml = "<hierarchy rotation='0'></hierarchy>"
    obs = parse_hierarchy(xml)
    assert obs.nodes == []
    assert obs.render() == ""
```

- [ ] **Step 4: Run tests — confirm they fail**

Run: `uv run pytest tests/test_perception.py -v`
Expected: ImportError / collection error on `androidharness.perception`.

- [ ] **Step 5: Implement `perception.py`**

Create `androidharness/perception.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from lxml import etree

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass(frozen=True)
class Node:
    id: int
    class_name: str
    text: str
    content_desc: str
    resource_id: str
    bounds: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    clickable: bool
    long_clickable: bool
    scrollable: bool
    editable: bool

    @property
    def short_class(self) -> str:
        return self.class_name.rsplit(".", 1)[-1] if self.class_name else ""

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def summary(self) -> str:
        traits: list[str] = []
        if self.clickable:
            traits.append("clickable")
        if self.long_clickable:
            traits.append("long-clickable")
        if self.scrollable:
            traits.append("scrollable")
        if self.editable:
            traits.append("editable")
        traits_str = f" ({', '.join(traits)})" if traits else ""

        label_source = self.text or self.content_desc
        if self.editable and not self.text:
            label = f'placeholder="{self.content_desc}"' if self.content_desc else "(empty)"
        elif label_source:
            label = f'"{label_source}"'
        else:
            label = ""

        parts = [f"[{self.id}]", self.short_class]
        if label:
            parts.append(label)
        return (" ".join(parts) + traits_str).rstrip()


@dataclass
class Observation:
    nodes: list[Node] = field(default_factory=list)

    def resolve(self, node_id: int) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def render(self) -> str:
        return "\n".join(n.summary for n in self.nodes)


def _parse_bounds(raw: str) -> tuple[int, int, int, int]:
    m = _BOUNDS_RE.match(raw or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(v) for v in m.groups())  # type: ignore[return-value]


def _attr_bool(elem: etree._Element, name: str) -> bool:
    return elem.get(name, "false") == "true"


def _is_editable(elem: etree._Element) -> bool:
    cls = elem.get("class", "")
    return "EditText" in cls or cls.endswith(".EditText")


def _walk(root: etree._Element) -> Iterator[etree._Element]:
    for elem in root.iter("node"):
        yield elem


def parse_hierarchy(xml: str) -> Observation:
    root = etree.fromstring(xml.encode("utf-8"))
    obs = Observation()
    next_id = 1
    for elem in _walk(root):
        clickable = _attr_bool(elem, "clickable")
        long_clickable = _attr_bool(elem, "long-clickable")
        scrollable = _attr_bool(elem, "scrollable")
        editable = _is_editable(elem)
        text = elem.get("text", "") or ""
        content_desc = elem.get("content-desc", "") or ""

        is_interactable = clickable or long_clickable or scrollable or editable
        has_label = bool(text or content_desc)
        if not (is_interactable or has_label):
            continue

        node = Node(
            id=next_id,
            class_name=elem.get("class", ""),
            text=text,
            content_desc=content_desc,
            resource_id=elem.get("resource-id", "") or "",
            bounds=_parse_bounds(elem.get("bounds", "")),
            clickable=clickable,
            long_clickable=long_clickable,
            scrollable=scrollable,
            editable=editable,
        )
        obs.nodes.append(node)
        next_id += 1
    return obs
```

- [ ] **Step 6: Run tests — confirm they pass**

Run: `uv run pytest tests/test_perception.py -v`
Expected: all 8 tests pass.

- [ ] **Step 7: Commit**

```bash
git add androidharness/perception.py tests/test_perception.py tests/fixtures
git commit -m "feat(perception): hierarchy XML to compact Observation"
```

---

## Task 3: Device layer — protocol, fake, and uiautomator2 wrapper

**Files:**
- Create: `androidharness/device.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_device_integration.py`

- [ ] **Step 1: Sketch the test that pins the protocol**

Append to `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the integration test (skipped by default)**

Create `tests/test_device_integration.py`:

```python
import os

import pytest

SERIAL = os.environ.get("ANDROIDHARNESS_DEVICE_SERIAL")

pytestmark = pytest.mark.skipif(
    not SERIAL,
    reason="set ANDROIDHARNESS_DEVICE_SERIAL to run device integration tests",
)


def test_list_devices_includes_target_serial():
    from androidharness.device import list_devices

    serials = [d.serial for d in list_devices()]
    assert SERIAL in serials


def test_dump_hierarchy_returns_non_empty_xml():
    from androidharness.device import UIAutomatorDevice

    device = UIAutomatorDevice.connect(SERIAL)
    xml = device.dump_hierarchy()
    assert xml.strip().startswith("<")
    assert "<hierarchy" in xml
```

- [ ] **Step 3: Run tests — fake fixture should import-fail device module**

Run: `uv run pytest tests/test_device_integration.py -v`
Expected: SKIPPED (no env var). That's pass-equivalent for this step.

- [ ] **Step 4: Implement `device.py`**

Create `androidharness/device.py`:

```python
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


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    model: str


def list_devices() -> list[DeviceInfo]:
    out = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, check=True
    ).stdout
    serials = [
        line.split("\t", 1)[0]
        for line in out.splitlines()[1:]
        if line.strip() and line.endswith("device")
    ]
    infos: list[DeviceInfo] = []
    for serial in serials:
        try:
            model = subprocess.run(
                ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                capture_output=True, text=True, check=True,
            ).stdout.strip() or "unknown"
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
    def connect(cls, serial: str) -> "UIAutomatorDevice":
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
        self._d.click(x, y)
        if replace:
            self._d.clear_text()
        self._d.send_keys(text)

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
```

- [ ] **Step 5: Re-run all tests**

Run: `uv run pytest -v`
Expected: perception tests pass; device-integration skipped; total green.

- [ ] **Step 6: Commit**

```bash
git add androidharness/device.py tests/conftest.py tests/test_device_integration.py
git commit -m "feat(device): Device protocol, uiautomator2 wrapper, FakeDevice fixture"
```

---

## Task 4: Tools — action vocabulary, validation, execution

**Files:**
- Create: `androidharness/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools.py`:

```python
import pytest

from androidharness.perception import parse_hierarchy
from androidharness.tools import (
    GEMINI_FUNCTION_DECLARATIONS,
    ToolCall,
    ToolError,
    ToolResult,
    execute,
)

MINIMAL = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true"/>
    <node bounds="[40,360][520,480]" class="android.widget.EditText" content-desc="Search" clickable="true"/>
    <node bounds="[40,520][1040,2000]" class="androidx.recyclerview.widget.RecyclerView" scrollable="true"/>
  </node>
</hierarchy>
"""


@pytest.fixture
def obs():
    return parse_hierarchy(MINIMAL)


def test_tap_unknown_id_returns_validation_error(fake_device, obs):
    result = execute(fake_device, ToolCall(name="tap", args={"id": 99}), obs)
    assert isinstance(result, ToolError)
    assert "99" in result.message
    assert fake_device.calls == []


def test_tap_known_id_invokes_device_at_node_center(fake_device, obs):
    result = execute(fake_device, ToolCall(name="tap", args={"id": 1}), obs)
    assert isinstance(result, ToolResult)
    # Button bounds [40,200][520,320] → center (280, 260)
    assert fake_device.calls == [("tap", {"x": 280, "y": 260})]


def test_type_uses_node_center_and_default_replace_false(fake_device, obs):
    result = execute(
        fake_device,
        ToolCall(name="type", args={"id": 2, "text": "hello"}),
        obs,
    )
    assert isinstance(result, ToolResult)
    # EditText bounds [40,360][520,480] → center (280, 420)
    assert fake_device.calls == [
        ("type_text", {"x": 280, "y": 420, "text": "hello", "replace": False})
    ]


def test_type_replace_true_passes_through(fake_device, obs):
    execute(
        fake_device,
        ToolCall(name="type", args={"id": 2, "text": "x", "replace": True}),
        obs,
    )
    assert fake_device.calls[-1] == (
        "type_text",
        {"x": 280, "y": 420, "text": "x", "replace": True},
    )


def test_swipe_unknown_direction_is_validation_error(fake_device, obs):
    result = execute(
        fake_device, ToolCall(name="swipe", args={"direction": "diagonal"}), obs
    )
    assert isinstance(result, ToolError)
    assert fake_device.calls == []


def test_swipe_default_distance_is_short(fake_device, obs):
    execute(fake_device, ToolCall(name="swipe", args={"direction": "up"}), obs)
    assert fake_device.calls == [("swipe", {"direction": "up", "distance": "short"})]


def test_scroll_resolves_id_to_center(fake_device, obs):
    execute(
        fake_device,
        ToolCall(name="scroll", args={"id": 3, "direction": "down"}),
        obs,
    )
    # RecyclerView bounds [40,520][1040,2000] → center (540, 1260)
    assert fake_device.calls == [("scroll", {"x": 540, "y": 1260, "direction": "down"})]


def test_press_key_whitelist_rejects_arbitrary(fake_device, obs):
    result = execute(
        fake_device, ToolCall(name="press_key", args={"name": "power"}), obs
    )
    assert isinstance(result, ToolError)
    assert fake_device.calls == []


def test_press_key_allows_back(fake_device, obs):
    execute(fake_device, ToolCall(name="press_key", args={"name": "back"}), obs)
    assert fake_device.calls == [("press_key", {"name": "back"})]


def test_wait_clamps_to_ten_seconds(fake_device, obs):
    execute(fake_device, ToolCall(name="wait", args={"seconds": 99}), obs)
    assert fake_device.calls == [("wait", {"seconds": 10.0})]


def test_show_screen_does_not_call_device(fake_device, obs):
    result = execute(fake_device, ToolCall(name="show_screen", args={}), obs)
    assert isinstance(result, ToolResult)
    assert result.requests_screenshot is True
    assert fake_device.calls == []


def test_done_does_not_call_device(fake_device, obs):
    result = execute(
        fake_device,
        ToolCall(name="done", args={"success": True, "reason": "ok"}),
        obs,
    )
    assert isinstance(result, ToolResult)
    assert result.is_done is True
    assert result.done_success is True
    assert result.done_reason == "ok"
    assert fake_device.calls == []


def test_unknown_tool_is_validation_error(fake_device, obs):
    result = execute(fake_device, ToolCall(name="nuke", args={}), obs)
    assert isinstance(result, ToolError)


def test_gemini_schema_has_all_tools():
    names = {decl["name"] for decl in GEMINI_FUNCTION_DECLARATIONS}
    assert names == {
        "tap", "long_press", "type", "swipe", "scroll",
        "press_key", "wait", "show_screen", "done",
    }
```

- [ ] **Step 2: Run tests — confirm failure**

Run: `uv run pytest tests/test_tools.py -v`
Expected: ImportError on `androidharness.tools`.

- [ ] **Step 3: Implement `tools.py`**

Create `androidharness/tools.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from androidharness.perception import Observation


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    message: str = "ok"
    is_done: bool = False
    done_success: bool = False
    done_reason: str = ""
    requests_screenshot: bool = False


@dataclass
class ToolError:
    message: str


_KEY_WHITELIST = {"back", "home", "recents", "enter"}
_SWIPE_DIRECTIONS = {"up", "down", "left", "right"}
_DISTANCES = {"short", "long"}


def _require_id(args: dict, obs: Observation) -> int | ToolError:
    if "id" not in args:
        return ToolError("missing required arg: id")
    try:
        node_id = int(args["id"])
    except (TypeError, ValueError):
        return ToolError(f"id must be an integer, got {args['id']!r}")
    try:
        obs.resolve(node_id)
    except KeyError:
        valid = [n.id for n in obs.nodes]
        return ToolError(
            f"id {node_id} not in current tree; valid ids are {valid}"
        )
    return node_id


def execute(device, call: ToolCall, obs: Observation):
    name = call.name
    args = call.args

    if name == "done":
        return ToolResult(
            message="done",
            is_done=True,
            done_success=bool(args.get("success", False)),
            done_reason=str(args.get("reason", "")),
        )

    if name == "show_screen":
        return ToolResult(message="screenshot will be attached to next observation",
                          requests_screenshot=True)

    if name == "tap":
        node_id = _require_id(args, obs)
        if isinstance(node_id, ToolError):
            return node_id
        x, y = obs.resolve(node_id).center
        device.tap(x, y)
        return ToolResult(message=f"tapped id {node_id}")

    if name == "long_press":
        node_id = _require_id(args, obs)
        if isinstance(node_id, ToolError):
            return node_id
        duration = int(args.get("duration_ms", 800))
        x, y = obs.resolve(node_id).center
        device.long_press(x, y, duration)
        return ToolResult(message=f"long-pressed id {node_id} for {duration}ms")

    if name == "type":
        node_id = _require_id(args, obs)
        if isinstance(node_id, ToolError):
            return node_id
        if "text" not in args:
            return ToolError("missing required arg: text")
        text = str(args["text"])
        replace = bool(args.get("replace", False))
        x, y = obs.resolve(node_id).center
        device.type_text(x, y, text, replace)
        return ToolResult(message=f"typed into id {node_id}")

    if name == "swipe":
        direction = args.get("direction")
        if direction not in _SWIPE_DIRECTIONS:
            return ToolError(f"swipe direction must be one of {sorted(_SWIPE_DIRECTIONS)}")
        distance = args.get("distance", "short")
        if distance not in _DISTANCES:
            return ToolError(f"swipe distance must be one of {sorted(_DISTANCES)}")
        device.swipe(direction, distance)
        return ToolResult(message=f"swiped {direction} {distance}")

    if name == "scroll":
        node_id = _require_id(args, obs)
        if isinstance(node_id, ToolError):
            return node_id
        direction = args.get("direction")
        if direction not in _SWIPE_DIRECTIONS:
            return ToolError(f"scroll direction must be one of {sorted(_SWIPE_DIRECTIONS)}")
        x, y = obs.resolve(node_id).center
        device.scroll(x, y, direction)
        return ToolResult(message=f"scrolled id {node_id} {direction}")

    if name == "press_key":
        key = args.get("name")
        if key not in _KEY_WHITELIST:
            return ToolError(f"press_key.name must be one of {sorted(_KEY_WHITELIST)}")
        device.press_key(key)
        return ToolResult(message=f"pressed {key}")

    if name == "wait":
        try:
            seconds = float(args.get("seconds", 1.0))
        except (TypeError, ValueError):
            return ToolError("wait.seconds must be a number")
        seconds = max(0.0, min(seconds, 10.0))
        device.wait(seconds)
        return ToolResult(message=f"waited {seconds}s")

    return ToolError(f"unknown tool: {name}")


GEMINI_FUNCTION_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "tap",
        "description": "Tap a UI element by its id from the current observation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"id": {"type": "INTEGER"}},
            "required": ["id"],
        },
    },
    {
        "name": "long_press",
        "description": "Long-press a UI element by id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "id": {"type": "INTEGER"},
                "duration_ms": {"type": "INTEGER"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "type",
        "description": "Focus an editable node and type text. Set replace=true to clear first.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "id": {"type": "INTEGER"},
                "text": {"type": "STRING"},
                "replace": {"type": "BOOLEAN"},
            },
            "required": ["id", "text"],
        },
    },
    {
        "name": "swipe",
        "description": "Swipe the screen. Direction is finger direction.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "direction": {"type": "STRING", "enum": ["up", "down", "left", "right"]},
                "distance": {"type": "STRING", "enum": ["short", "long"]},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll a specific scrollable node by id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "id": {"type": "INTEGER"},
                "direction": {"type": "STRING", "enum": ["up", "down", "left", "right"]},
            },
            "required": ["id", "direction"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a hardware/system key.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "enum": ["back", "home", "recents", "enter"]},
            },
            "required": ["name"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for loading. Clamped to 10s.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"seconds": {"type": "NUMBER"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "show_screen",
        "description": "Request that a screenshot be attached to the next observation.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "done",
        "description": "End the task. Set success=true if completed; reason explains why.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "success": {"type": "BOOLEAN"},
                "reason": {"type": "STRING"},
            },
            "required": ["success", "reason"],
        },
    },
]
```

- [ ] **Step 4: Run tests — confirm pass**

Run: `uv run pytest tests/test_tools.py -v`
Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/tools.py tests/test_tools.py
git commit -m "feat(tools): action vocabulary, validation, Gemini schemas"
```

---

## Task 5: Agent — Gemini loop with a fake client

**Files:**
- Create: `androidharness/agent.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Add a `FakeGeminiClient` to conftest**

Append to `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing agent tests**

Create `tests/test_agent.py`:

```python
import pytest

from androidharness.agent import Agent, RunResult


HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true"/>
  </node>
</hierarchy>
"""


def test_agent_stops_on_done_success(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([
        {"name": "tap", "args": {"id": 1}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert isinstance(result, RunResult)
    assert result.status == "done"
    assert result.success is True
    assert result.reason == "ok"
    assert result.turns == 2


def test_agent_returns_max_turns_when_budget_exhausted(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([{"name": "tap", "args": {"id": 1}}] * 3)
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=3)
    result = agent.run("loop forever")
    assert result.status == "max_turns"
    assert result.success is None
    assert result.turns == 3


def test_agent_validation_error_becomes_tool_result_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([
        {"name": "tap", "args": {"id": 999}},  # invalid
        {"name": "done", "args": {"success": False, "reason": "gave up"}},
    ])
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("try a bad id")
    assert result.status == "done"
    assert result.success is False
    # The validation error must have been surfaced back to the model as a tool result.
    second_call_contents = client.generate_calls[1]["contents"]
    rendered = "\n".join(
        part for turn in second_call_contents for part in [str(turn)]
    )
    assert "999" in rendered


def test_agent_show_screen_attaches_screenshot_next_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    fake_device.screenshot_bytes = b"PNGDATA"
    client = fake_gemini([
        {"name": "show_screen", "args": {}},
        {"name": "done", "args": {"success": True, "reason": "saw screen"}},
    ])
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    agent.run("look")
    # Turn 1 should not have screenshotted yet.
    assert ("screenshot", {}) not in fake_device.calls[:1]
    # By the time of the 2nd generate, a screenshot was taken.
    assert ("screenshot", {}) in fake_device.calls


def test_agent_records_each_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([
        {"name": "tap", "args": {"id": 1}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert len(result.turn_log) == 2
    assert result.turn_log[0]["tool_call"]["name"] == "tap"
    assert result.turn_log[1]["tool_call"]["name"] == "done"
    assert "observation_summary" in result.turn_log[0]
    assert "tool_result" in result.turn_log[0]
```

- [ ] **Step 3: Run tests — confirm failure**

Run: `uv run pytest tests/test_agent.py -v`
Expected: ImportError on `androidharness.agent`.

- [ ] **Step 4: Implement `agent.py`**

Create `androidharness/agent.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from androidharness.perception import parse_hierarchy
from androidharness.tools import (
    GEMINI_FUNCTION_DECLARATIONS,
    ToolCall,
    ToolError,
    ToolResult,
    execute,
)

SYSTEM_PROMPT = """You are controlling a real Android device to complete a user task.
Each turn you receive:
  * The user task (sticky).
  * The previous tool's result (if any).
  * The current UI as a numbered list of interactable nodes (the "Observation").
  * Optionally, a screenshot if you requested it via show_screen() last turn.

Rules:
  * Always act through the provided tools — never describe an action without calling a tool.
  * Refer to UI elements by their [id] from the current Observation only. Ids are not stable across turns.
  * If the UI tree does not contain enough information, call show_screen() to get a screenshot on the next turn.
  * When the task is complete (or definitively impossible), call done(success, reason).
  * Prefer the smallest sequence of actions that achieves the task."""


class GeminiClient(Protocol):
    def generate(self, *, model: str, system_instruction: str,
                 contents: list, tools: list) -> dict: ...


@dataclass
class RunResult:
    status: Literal["done", "max_turns", "timeout"]
    success: bool | None
    reason: str
    turns: int
    turn_log: list[dict] = field(default_factory=list)


@dataclass
class Agent:
    device: Any
    client: GeminiClient
    model: str = "gemini-2.5-flash"
    max_turns: int = 40
    wall_clock_s: float = 600.0

    def run(self, task: str) -> RunResult:
        contents: list[dict] = [{"role": "user", "task": task}]
        turn_log: list[dict] = []
        needs_screenshot = False
        started = time.monotonic()

        for turn_idx in range(1, self.max_turns + 1):
            if time.monotonic() - started > self.wall_clock_s:
                return RunResult(status="timeout", success=None, reason="wall clock",
                                 turns=turn_idx - 1, turn_log=turn_log)

            xml = self.device.dump_hierarchy()
            obs = parse_hierarchy(xml)
            obs_payload: dict[str, Any] = {"role": "observation", "text": obs.render()}
            if needs_screenshot:
                obs_payload["screenshot"] = self.device.screenshot()
                needs_screenshot = False
            contents.append(obs_payload)

            raw = self.client.generate(
                model=self.model,
                system_instruction=SYSTEM_PROMPT,
                contents=contents,
                tools=GEMINI_FUNCTION_DECLARATIONS,
            )
            call = ToolCall(name=raw["name"], args=dict(raw.get("args", {})))

            result = execute(self.device, call, obs)

            tool_result_payload = {
                "role": "tool_result",
                "tool": call.name,
                "ok": isinstance(result, ToolResult),
                "message": result.message,
            }
            contents.append(tool_result_payload)

            turn_log.append({
                "turn": turn_idx,
                "observation_summary": obs.render(),
                "tool_call": {"name": call.name, "args": call.args},
                "tool_result": tool_result_payload,
            })

            if isinstance(result, ToolResult):
                if result.is_done:
                    return RunResult(
                        status="done",
                        success=result.done_success,
                        reason=result.done_reason,
                        turns=turn_idx,
                        turn_log=turn_log,
                    )
                if result.requests_screenshot:
                    needs_screenshot = True

        return RunResult(status="max_turns", success=None, reason="max turns reached",
                         turns=self.max_turns, turn_log=turn_log)
```

- [ ] **Step 5: Run agent tests — confirm pass**

Run: `uv run pytest tests/test_agent.py -v`
Expected: all 5 tests pass.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: perception + tools + agent all green; integration tests skipped.

- [ ] **Step 7: Commit**

```bash
git add androidharness/agent.py tests/conftest.py tests/test_agent.py
git commit -m "feat(agent): Gemini-style loop with validation surfacing and screenshot escape hatch"
```

---

## Task 6: Runner — orchestration and run-dir artifacts

**Files:**
- Create: `androidharness/runner.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runner.py`:

```python
import json
from pathlib import Path

from androidharness.runner import run_task


HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true"/>
  </node>
</hierarchy>
"""


def test_run_task_writes_meta_turns_and_result(tmp_path, fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([
        {"name": "tap", "args": {"id": 1}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
    result = run_task(
        task="open settings",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
    )
    run_dir = Path(result.run_dir)
    assert run_dir.exists()
    assert run_dir.parent == tmp_path

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["task"] == "open settings"
    assert meta["model"] == "gemini-2.5-flash"
    assert meta["device"]["serial"] == "FAKE"
    assert meta["device"]["model"] == "FakePixel"

    final = json.loads((run_dir / "result.json").read_text())
    assert final["status"] == "done"
    assert final["success"] is True
    assert final["reason"] == "ok"

    lines = (run_dir / "turns.jsonl").read_text().splitlines()
    assert len(lines) == 2
    turn0 = json.loads(lines[0])
    assert turn0["tool_call"]["name"] == "tap"


def test_run_task_writes_screenshot_only_when_requested(tmp_path, fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    fake_device.screenshot_bytes = b"PNGDATA"
    client = fake_gemini([
        {"name": "show_screen", "args": {}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
    result = run_task(
        task="look",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
    )
    run_dir = Path(result.run_dir)
    screenshots = list((run_dir / "screenshots").glob("*.png"))
    assert len(screenshots) == 1
    assert screenshots[0].read_bytes() == b"PNGDATA"
```

- [ ] **Step 2: Run tests — confirm failure**

Run: `uv run pytest tests/test_runner.py -v`
Expected: ImportError on `androidharness.runner`.

- [ ] **Step 3: Implement `runner.py`**

Create `androidharness/runner.py`:

```python
from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from androidharness.agent import Agent, GeminiClient


@dataclass
class RunOutcome:
    run_dir: str
    status: str
    success: bool | None
    reason: str
    turns: int


def _new_run_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = secrets.token_hex(3)
    p = root / f"{stamp}-{short}"
    p.mkdir(parents=True, exist_ok=False)
    (p / "screenshots").mkdir()
    return p


def run_task(
    *,
    task: str,
    device: Any,
    client: GeminiClient,
    model: str,
    runs_root: Path,
    max_turns: int = 40,
    wall_clock_s: float = 600.0,
) -> RunOutcome:
    run_dir = _new_run_dir(runs_root)
    start = time.time()

    agent = Agent(
        device=device, client=client, model=model,
        max_turns=max_turns, wall_clock_s=wall_clock_s,
    )

    # Capture screenshots written during the run. We hook into the agent by
    # re-running observation logic here would duplicate state; instead, after
    # the agent runs, walk its turn_log and persist any screenshot it requested
    # by re-asking the device — but that's racy. Simpler and correct: the agent
    # writes the screenshot bytes into the turn record itself.
    result = agent.run(task)

    # Persist turn-by-turn log; pull screenshots out of payloads if present.
    with (run_dir / "turns.jsonl").open("w") as f:
        for turn in result.turn_log:
            screenshot_bytes = None
            obs_payload = turn.get("observation_payload")
            if isinstance(obs_payload, dict):
                screenshot_bytes = obs_payload.pop("screenshot", None)
            if screenshot_bytes:
                ss_path = run_dir / "screenshots" / f"turn-{turn['turn']:03d}.png"
                ss_path.write_bytes(screenshot_bytes)
                turn["screenshot_path"] = str(ss_path.relative_to(run_dir))
            f.write(json.dumps(turn, default=str) + "\n")

    (run_dir / "meta.json").write_text(json.dumps({
        "task": task,
        "model": model,
        "device": {"serial": device.serial, "model": device.model},
        "started_at": start,
        "ended_at": time.time(),
        "max_turns": max_turns,
        "wall_clock_s": wall_clock_s,
    }, indent=2))

    (run_dir / "result.json").write_text(json.dumps({
        "status": result.status,
        "success": result.success,
        "reason": result.reason,
        "turns": result.turns,
    }, indent=2))

    return RunOutcome(
        run_dir=str(run_dir),
        status=result.status,
        success=result.success,
        reason=result.reason,
        turns=result.turns,
    )
```

- [ ] **Step 4: Make the agent surface screenshot bytes into turn_log**

This change pairs with the runner — modify `androidharness/agent.py` so each turn's record includes the observation payload (which may carry screenshot bytes). Replace the `turn_log.append(...)` block with:

```python
            turn_log.append({
                "turn": turn_idx,
                "observation_summary": obs.render(),
                "observation_payload": obs_payload,
                "tool_call": {"name": call.name, "args": call.args},
                "tool_result": tool_result_payload,
            })
```

- [ ] **Step 5: Run runner tests**

Run: `uv run pytest tests/test_runner.py -v`
Expected: both tests pass.

- [ ] **Step 6: Re-run the full suite**

Run: `uv run pytest -v`
Expected: all tests pass; integration tests skipped.

- [ ] **Step 7: Commit**

```bash
git add androidharness/runner.py androidharness/agent.py tests/test_runner.py
git commit -m "feat(runner): per-run artifacts (meta/turns/result/screenshots)"
```

---

## Task 7: Gemini client adapter and CLI

**Files:**
- Modify: `androidharness/agent.py` (no change to behaviour — just add a `GoogleGenaiClient` adapter at the bottom)
- Create: `androidharness/cli.py`

- [ ] **Step 1: Add the real Gemini adapter**

Append to `androidharness/agent.py`:

```python
class GoogleGenaiClient:
    """Adapter over google-genai that returns the first function call from a response."""

    def __init__(self, api_key: str | None = None):
        from google import genai
        self._genai = genai
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def generate(self, *, model, system_instruction, contents, tools):
        from google.genai import types

        # Flatten our internal `contents` (list of dicts) into a simple user message
        # plus any image bytes. v1 keeps this lossy-but-faithful: each entry becomes
        # a labeled text part; screenshots are added as inline_data.
        parts: list[Any] = []
        for entry in contents:
            role = entry.get("role", "context")
            if role == "user":
                parts.append(types.Part.from_text(f"Task: {entry.get('task','')}"))
            elif role == "observation":
                parts.append(types.Part.from_text(f"Observation:\n{entry.get('text','')}"))
                shot = entry.get("screenshot")
                if shot:
                    parts.append(types.Part.from_bytes(data=shot, mime_type="image/png"))
            elif role == "tool_result":
                parts.append(types.Part.from_text(
                    f"Previous tool {entry.get('tool')} -> "
                    f"{'ok' if entry.get('ok') else 'error'}: {entry.get('message','')}"
                ))

        gemini_tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(**fd) for fd in tools
        ])]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        )
        response = self._client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )

        # Find the first function call in the response.
        for cand in response.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    return {"name": fc.name, "args": dict(fc.args or {})}

        # Model spoke without calling a tool — surface as done(success=False).
        return {"name": "done",
                "args": {"success": False,
                         "reason": "model did not call a tool"}}
```

- [ ] **Step 2: Implement the CLI**

Create `androidharness/cli.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from androidharness.agent import GoogleGenaiClient
from androidharness.device import UIAutomatorDevice, list_devices
from androidharness.runner import run_task

app = typer.Typer(add_completion=False, help="AI harness for Android devices.")


@app.command("devices")
def devices_cmd() -> None:
    """List ADB-connected devices."""
    infos = list_devices()
    if not infos:
        typer.echo("no devices connected (check 'adb devices')")
        raise typer.Exit(code=1)
    for i, info in enumerate(infos):
        typer.echo(f"[{i}] {info.serial}  {info.model}")


@app.command("run")
def run_cmd(
    task: str = typer.Argument(..., help="Natural-language task to drive on the device."),
    serial: Optional[str] = typer.Option(None, "--serial", "-s"),
    device_index: Optional[int] = typer.Option(None, "--device-index", "-i"),
    model: str = typer.Option("gemini-2.5-flash", "--model"),
    max_turns: int = typer.Option(40, "--max-turns"),
    wall_clock: float = typer.Option(600.0, "--wall-clock"),
    runs_dir: Path = typer.Option(Path("./runs"), "--run-dir"),
) -> None:
    if serial and device_index is not None:
        typer.echo("error: --serial and --device-index are mutually exclusive", err=True)
        raise typer.Exit(code=2)

    infos = list_devices()
    if not infos:
        typer.echo("no devices connected (check 'adb devices')", err=True)
        raise typer.Exit(code=1)

    if serial:
        if serial not in {i.serial for i in infos}:
            typer.echo(f"serial {serial!r} not in connected devices", err=True)
            raise typer.Exit(code=1)
        chosen = serial
    elif device_index is not None:
        if not 0 <= device_index < len(infos):
            typer.echo(f"--device-index out of range: {device_index}", err=True)
            raise typer.Exit(code=1)
        chosen = infos[device_index].serial
    else:
        if len(infos) == 1:
            chosen = infos[0].serial
        else:
            typer.echo("multiple devices — pass --serial or --device-index:", err=True)
            for i, info in enumerate(infos):
                typer.echo(f"  [{i}] {info.serial}  {info.model}", err=True)
            raise typer.Exit(code=1)

    if not os.environ.get("GOOGLE_API_KEY"):
        typer.echo("error: GOOGLE_API_KEY env var is not set", err=True)
        raise typer.Exit(code=1)

    device = UIAutomatorDevice.connect(chosen)
    client = GoogleGenaiClient()
    runs_dir.mkdir(parents=True, exist_ok=True)

    outcome = run_task(
        task=task,
        device=device,
        client=client,
        model=model,
        runs_root=runs_dir,
        max_turns=max_turns,
        wall_clock_s=wall_clock,
    )
    typer.echo(f"run dir: {outcome.run_dir}")
    typer.echo(f"status:  {outcome.status}")
    typer.echo(f"success: {outcome.success}")
    typer.echo(f"reason:  {outcome.reason}")
    typer.echo(f"turns:   {outcome.turns}")
    sys.exit(0 if outcome.success else 1)


if __name__ == "__main__":
    app()
```

- [ ] **Step 3: Verify the CLI surfaces a help screen**

Run: `uv run androidharness --help`
Expected: Typer prints `devices` and `run` subcommands.

Run: `uv run androidharness run --help`
Expected: shows `--serial`, `--device-index`, `--model`, `--max-turns`, `--wall-clock`, `--run-dir`.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest -v`
Expected: all tests still pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/agent.py androidharness/cli.py
git commit -m "feat(cli+gemini): real Gemini adapter and Typer CLI (devices, run)"
```

---

## Task 8: Lint pass and README quickstart

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run ruff to catch formatting/lint issues**

Run: `uv run ruff format androidharness tests`
Run: `uv run ruff check --fix androidharness tests`
Expected: no remaining diagnostics.

- [ ] **Step 2: Write the README quickstart**

Create `README.md`:

```markdown
# AndroidHarness

AI harness for driving real Android phones over ADB with Gemini 2.5 Flash.

## Quickstart

```bash
# 1. Connect a device and confirm adb sees it
adb devices

# 2. Set your Gemini key
export GOOGLE_API_KEY=...

# 3. Install
uv sync

# 4. Run a task
uv run androidharness run "Open Settings and toggle Wi-Fi off"
```

Use `uv run androidharness devices` to list attached devices, and `--serial`/`--device-index` to choose between multiples.

Each run writes artifacts to `./runs/<timestamp>-<short-id>/`:

- `meta.json` — task, model, device.
- `turns.jsonl` — observation + tool call + result per turn.
- `result.json` — final status, success, reason.
- `screenshots/turn-<n>.png` — only when the model requested `show_screen()` that turn.

## Architecture

See `docs/superpowers/specs/2026-05-19-android-ai-harness-design.md`.
```

- [ ] **Step 3: Run the full suite once more**

Run: `uv run pytest -v`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add README.md androidharness tests
git commit -m "docs: README quickstart; lint pass"
```

---

## Self-Review (already applied)

**Spec coverage**

| Spec §  | Implemented by |
|---|---|
| §3 architecture (four units) | Tasks 2–6 |
| §4 perception (compact node list, id map, ids start at 1, not stable across turns) | Task 2 |
| §4 screenshot escape hatch | `show_screen()` in Task 4, agent flag in Task 5, runner persist in Task 6 |
| §5 action vocabulary (full table) | Task 4 |
| §5 validation against id map / whitelist / clamp | Task 4 (tests + execute) |
| §6 agent loop (max_turns, wall_clock, done) | Task 5 |
| §7 multi-device selection (0 / 1 / 2+) | Task 7 CLI |
| §8 CLI flags | Task 7 |
| §9 run artifacts (meta/turns/result/screenshots) | Task 6 |
| §10 `GOOGLE_API_KEY` | Task 7 CLI |
| §11 ADB drop / hallucinated ids / context | Tasks 3 (auto via uiautomator2), 4 (validation), 5 (per-turn lossy contents) |
| §12 testing strategy | Tasks 2–6 (unit + 6 smoke + 3 integration-skip) |
| §13 deps | Task 1 |

**Placeholders:** none — all steps have concrete code or commands.

**Type consistency:** `ToolCall`, `ToolResult`, `ToolError`, `Observation`, `Node`, `RunResult`, `RunOutcome`, `Device` protocol, `GeminiClient` protocol, and the `FakeDevice` method signatures are all named identically across the tasks that reference them. Task 6 explicitly amends the `turn_log` entry added in Task 5 to carry `observation_payload` (the change is shown in full, not as a reference).
