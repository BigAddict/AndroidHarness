from __future__ import annotations

from androidharness.llm import GoogleGenaiClient, LLMClient, _tools_to_openai_tools


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
