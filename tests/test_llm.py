from __future__ import annotations

from androidharness.llm import (
    GoogleGenaiClient,
    LLMClient,
    _contents_to_openai_messages,
    _tools_to_openai_tools,
)


def test_llm_module_exports_protocol_and_google_client():
    """The Protocol and the relocated Google client both live in androidharness.llm.
    GoogleGenaiClient must structurally satisfy the LLMClient Protocol — i.e. it
    exposes a `generate(*, model, system_instruction, contents, tools) -> dict`
    method. We don't need to instantiate it; just check the attribute is there."""
    assert hasattr(GoogleGenaiClient, "generate")
    assert callable(GoogleGenaiClient.generate)
    assert LLMClient is not None


def test_tools_to_openai_tools_lowercases_types_and_wraps_in_function_shape():
    src = [
        {
            "name": "tap",
            "description": "Tap a UI element by its id.",
            "parameters": {
                "type": "OBJECT",
                "properties": {"id": {"type": "INTEGER"}},
                "required": ["id"],
            },
        }
    ]
    out = _tools_to_openai_tools(src)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "tap",
                "description": "Tap a UI element by its id.",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
            },
        }
    ]


def test_tools_to_openai_tools_handles_enums_and_nested_properties():
    src = [
        {
            "name": "swipe",
            "description": "Swipe.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "direction": {"type": "STRING", "enum": ["up", "down", "left", "right"]},
                    "distance": {"type": "STRING", "enum": ["short", "long"]},
                },
                "required": ["direction"],
            },
        }
    ]
    out = _tools_to_openai_tools(src)
    params = out[0]["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["direction"] == {
        "type": "string",
        "enum": ["up", "down", "left", "right"],
    }


def test_tools_to_openai_tools_passes_through_unknown_type_as_lowercase():
    src = [
        {
            "name": "exotic",
            "description": "x",
            "parameters": {
                "type": "OBJECT",
                "properties": {"x": {"type": "ARRAY", "items": {"type": "STRING"}}},
            },
        }
    ]
    out = _tools_to_openai_tools(src)
    p = out[0]["function"]["parameters"]["properties"]["x"]
    assert p == {"type": "array", "items": {"type": "string"}}


def test_contents_to_openai_messages_emits_system_then_user_task():
    out = _contents_to_openai_messages(
        system_instruction="SYS",
        contents=[{"role": "user", "task": "open settings"}],
    )
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "Task: open settings"}


def test_contents_to_openai_messages_renders_observation_as_user_text():
    out = _contents_to_openai_messages(
        system_instruction="SYS",
        contents=[{"role": "observation", "text": "[1] Button Settings"}],
    )
    assert out[1] == {"role": "user", "content": "Observation:\n[1] Button Settings"}


def test_contents_to_openai_messages_inlines_screenshot_as_image_part():
    """When an observation has a screenshot, emit a multi-part user message
    with a text part plus a base64-data-URL image part. This is the OpenAI
    vision shape that LiteLLM normalizes to every multi-modal provider."""
    out = _contents_to_openai_messages(
        system_instruction="SYS",
        contents=[
            {
                "role": "observation",
                "text": "[1] Button Settings",
                "screenshot": b"\x89PNG\r\n\x1a\nFAKE",
            }
        ],
    )
    msg = out[1]
    assert msg["role"] == "user"
    parts = msg["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "Observation:\n[1] Button Settings"}
    assert parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    import base64
    payload = url.split(",", 1)[1]
    assert base64.b64decode(payload) == b"\x89PNG\r\n\x1a\nFAKE"


def test_contents_to_openai_messages_renders_tool_result_as_user_text():
    out = _contents_to_openai_messages(
        system_instruction="SYS",
        contents=[
            {"role": "tool_result", "tool": "tap", "ok": True, "message": "ok"},
            {"role": "tool_result", "tool": "type", "ok": False, "message": "no editable field"},
        ],
    )
    assert out[1] == {
        "role": "user",
        "content": "Previous tool tap -> ok: ok",
    }
    assert out[2] == {
        "role": "user",
        "content": "Previous tool type -> error: no editable field",
    }


def test_contents_to_openai_messages_skips_unknown_role_silently():
    """We don't want to crash if the agent introduces a new role mid-development.
    Unknown roles are dropped from the messages list but do not raise."""
    out = _contents_to_openai_messages(
        system_instruction="SYS",
        contents=[
            {"role": "user", "task": "t"},
            {"role": "made-up", "stuff": "x"},
        ],
    )
    assert len(out) == 2
