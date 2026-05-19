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
        return ToolError(f"id {node_id} not in current tree; valid ids are {valid}")
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
        return ToolResult(
            message="screenshot will be attached to next observation",
            requests_screenshot=True,
        )

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
