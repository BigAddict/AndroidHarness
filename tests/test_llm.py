from __future__ import annotations

import json

from androidharness.config import AndroidHarnessConfig
from androidharness.llm import (
    GoogleGenaiClient,
    LiteLLMClient,
    LiteLLMRouterClient,
    LLMClient,
    _build_router_kwargs,
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


class _StubMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _StubFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _StubToolCall:
    def __init__(self, name: str, arguments_json):
        self.function = _StubFunction(name, arguments_json)


class _StubChoice:
    def __init__(self, message: _StubMessage):
        self.message = message


class _StubResponse:
    def __init__(self, choices):
        self.choices = choices


def _patch_completion(monkeypatch, *, response: _StubResponse):
    """Patch litellm.completion to return `response` regardless of args. Returns
    the list it captures into so tests can assert on `model=`, `messages=`,
    `tools=` it was called with."""
    captured: list[dict] = []

    def fake_completion(**kwargs):
        captured.append(kwargs)
        return response

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return captured


def test_litellm_client_returns_first_tool_call_with_parsed_args(monkeypatch):
    tool_call = _StubToolCall("tap", json.dumps({"id": 7}))
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])
    captured = _patch_completion(monkeypatch, response=resp)

    client = LiteLLMClient()
    out = client.generate(
        model="gemini/gemini-2.5-flash",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "open settings"}],
        tools=[
            {
                "name": "tap",
                "description": "Tap.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"id": {"type": "INTEGER"}},
                    "required": ["id"],
                },
            }
        ],
    )
    assert out == {"name": "tap", "args": {"id": 7}}

    assert captured[0]["model"] == "gemini/gemini-2.5-flash"
    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["messages"][0] == {"role": "system", "content": "SYS"}
    assert captured[0]["tools"][0]["function"]["name"] == "tap"
    assert captured[0]["tools"][0]["function"]["parameters"]["type"] == "object"


def test_litellm_client_handles_dict_arguments_already_parsed(monkeypatch):
    """LiteLLM normally returns `arguments` as a JSON string, but some providers
    surface it pre-parsed. Accept both."""
    tool_call = _StubToolCall("tap", {"id": 3})
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])
    _patch_completion(monkeypatch, response=resp)

    client = LiteLLMClient()
    out = client.generate(
        model="gemini/gemini-2.5-flash",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[
            {"name": "tap", "description": "", "parameters": {"type": "OBJECT", "properties": {}}},
        ],
    )
    assert out == {"name": "tap", "args": {"id": 3}}


def test_litellm_client_falls_back_to_done_when_no_tool_call(monkeypatch):
    resp = _StubResponse([_StubChoice(_StubMessage(content="just chatting", tool_calls=[]))])
    _patch_completion(monkeypatch, response=resp)

    client = LiteLLMClient()
    out = client.generate(
        model="gemini/gemini-2.5-flash",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[
            {"name": "tap", "description": "", "parameters": {"type": "OBJECT", "properties": {}}},
        ],
    )
    assert out == {
        "name": "done",
        "args": {"success": False, "reason": "model did not call a tool"},
    }


def test_litellm_client_falls_back_to_done_when_choices_empty(monkeypatch):
    """Some providers return zero choices on safety blocks. Don't crash — emit
    a definitive done(success=False) so the run terminates cleanly."""
    resp = _StubResponse([])
    _patch_completion(monkeypatch, response=resp)

    client = LiteLLMClient()
    out = client.generate(
        model="gemini/gemini-2.5-flash",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert out["name"] == "done"
    assert out["args"]["success"] is False


def test_litellm_client_forwards_num_retries_for_transient_errors(monkeypatch):
    """LiteLLM has built-in retry logic; we set num_retries=3 so transient
    429 / 5xx errors get retried at the SDK level. Verify the kwarg is sent."""
    tool_call = _StubToolCall("done", json.dumps({"success": True, "reason": "ok"}))
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])
    captured = _patch_completion(monkeypatch, response=resp)

    LiteLLMClient().generate(
        model="gemini/gemini-2.5-flash",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert captured[0]["num_retries"] == 3


def _cfg_with(throttler: dict | None = None, providers: dict | None = None):
    """Build an AndroidHarnessConfig from partial overrides."""
    base = AndroidHarnessConfig().model_dump(mode="json")
    if throttler:
        base["throttler"].update(throttler)
    if providers:
        base["providers"].update(providers)
    return AndroidHarnessConfig.model_validate(base)


def test_build_router_kwargs_emits_one_entry_per_logical_chain_member():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": [
            "gemini/gemini-2.5-flash",
            "anthropic/claude-haiku-4-5",
        ]}},
    )
    kw = _build_router_kwargs(cfg)
    names = [m["model_name"] for m in kw["model_list"]]
    targets = [m["litellm_params"]["model"] for m in kw["model_list"]]
    assert "fast" in names
    assert "gemini/gemini-2.5-flash" in targets
    assert "anthropic/claude-haiku-4-5" in targets


def test_build_router_kwargs_applies_buckets_to_matching_entries():
    cfg = _cfg_with(
        throttler={
            "enabled": True,
            "buckets": {
                "gemini/gemini-2.5-flash": {"rpm": 10, "tpm": 250000},
            },
        },
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    kw = _build_router_kwargs(cfg)
    primary = next(m for m in kw["model_list"] if m["model_name"] == "fast")
    assert primary["rpm"] == 10
    assert primary["tpm"] == 250000


def test_build_router_kwargs_emits_fallbacks_map_in_chain_order():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": [
            "gemini/gemini-2.5-flash",
            "anthropic/claude-haiku-4-5",
            "openai/gpt-4o-mini",
        ]}},
    )
    kw = _build_router_kwargs(cfg)
    assert kw["fallbacks"] == [{
        "fast": ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"],
    }]


def test_build_router_kwargs_no_fallbacks_when_single_entry_chain():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"only": ["gemini/gemini-2.5-flash"]}},
    )
    kw = _build_router_kwargs(cfg)
    assert kw["fallbacks"] == []


def test_build_router_kwargs_adds_bare_buckets_as_concrete_entries():
    """If a bucket names a concrete model that isn't in any logical chain,
    expose it under its own model_name so a direct `--model gemini/gemini-2.5-flash`
    call still gets throttled."""
    cfg = _cfg_with(
        throttler={
            "enabled": True,
            "buckets": {"gemini/gemini-2.5-flash": {"rpm": 10}},
        },
    )
    kw = _build_router_kwargs(cfg)
    assert any(
        m["model_name"] == "gemini/gemini-2.5-flash"
        and m["litellm_params"]["model"] == "gemini/gemini-2.5-flash"
        and m["rpm"] == 10
        for m in kw["model_list"]
    )


def test_build_router_kwargs_forwards_cooldown_and_retries():
    cfg = _cfg_with(throttler={"enabled": True, "cooldown_seconds": 90, "num_retries": 5})
    kw = _build_router_kwargs(cfg)
    assert kw["cooldown_time"] == 90
    assert kw["num_retries"] == 5


def test_litellm_router_client_routes_via_router_completion(monkeypatch):
    """LiteLLMRouterClient calls self._router.completion(...) — verify the
    kwargs forwarded (model, messages, tools, tool_choice) and the response
    parsing follow the same contract as LiteLLMClient."""
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )

    tool_call = _StubToolCall("tap", json.dumps({"id": 7}))
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])

    client = LiteLLMRouterClient(cfg)

    captured: list[dict] = []

    def fake_router_completion(**kwargs):
        captured.append(kwargs)
        return resp

    monkeypatch.setattr(client._router, "completion", fake_router_completion)

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "open settings"}],
        tools=[
            {
                "name": "tap",
                "description": "Tap.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"id": {"type": "INTEGER"}},
                    "required": ["id"],
                },
            }
        ],
    )
    assert out == {"name": "tap", "args": {"id": 7}}
    assert captured[0]["model"] == "fast"
    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["messages"][0] == {"role": "system", "content": "SYS"}


def test_litellm_router_client_falls_back_to_done_on_empty_choices(monkeypatch):
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    client = LiteLLMRouterClient(cfg)
    monkeypatch.setattr(client._router, "completion", lambda **kw: _StubResponse([]))

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert out["name"] == "done"
    assert out["args"]["success"] is False


def test_litellm_router_client_handles_pre_parsed_dict_args(monkeypatch):
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    client = LiteLLMRouterClient(cfg)
    tool_call = _StubToolCall("tap", {"id": 3})
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])
    monkeypatch.setattr(client._router, "completion", lambda **kw: resp)

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert out == {"name": "tap", "args": {"id": 3}}
