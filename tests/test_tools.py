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
