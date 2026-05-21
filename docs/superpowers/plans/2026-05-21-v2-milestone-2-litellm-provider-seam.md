# v2 Milestone 2 — LiteLLM Provider Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard dependency on `GoogleGenaiClient` with a provider-agnostic `LLMClient` Protocol and ship a `LiteLLMClient` adapter so the same agent loop can run against Gemini, Anthropic, and OpenAI (and any other provider LiteLLM supports) selected by config — without touching the agent loop.

**Architecture:**

The agent's `GeminiClient` Protocol is renamed to `LLMClient` and moved into a new `androidharness/llm.py` module alongside two concrete implementations: the existing `GoogleGenaiClient` (relocated, otherwise unchanged) and a new `LiteLLMClient` that translates our internal `contents` shape into LiteLLM `messages` + `tools` and back into the `{"name", "args"}` shape the agent already consumes. `ProvidersConfig` is fleshed out with a `default` provider key and per-provider `api_key_env` / `default_model` entries. The CLI selects `LiteLLMClient` by default, falling back to `GoogleGenaiClient` only when a user explicitly opts out via `providers.use_litellm: false` (escape hatch in case LiteLLM has a regression for Gemini). The agent loop and runner are not touched beyond import renames.

**Tech Stack:** `litellm>=1.50.0` (new dep), Pydantic v2 (already), Typer (already), pytest with monkeypatching of `litellm.completion` for the new adapter's unit tests.

**Spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §3 + roadmap item #2.

---

## File Structure

| Path | Purpose |
|---|---|
| `pyproject.toml` | Modify — add `litellm>=1.50.0` runtime dep. |
| `androidharness/llm.py` | **New.** Holds the `LLMClient` Protocol, the relocated `GoogleGenaiClient`, the new `LiteLLMClient`, and small private helpers (`_contents_to_openai_messages`, `_tools_to_openai_tools`). |
| `androidharness/agent.py` | Modify — drop the local `GeminiClient` Protocol and `GoogleGenaiClient` class; import `LLMClient` from `androidharness.llm`; keep `GeminiClient = LLMClient` alias inside agent.py so existing callers' imports still resolve. The `Agent` dataclass field `client: GeminiClient` becomes `client: LLMClient`. |
| `androidharness/runner.py` | Modify — replace `from androidharness.agent import Agent, GeminiClient` with `from androidharness.agent import Agent; from androidharness.llm import LLMClient`. The `run_task(client: LLMClient, ...)` annotation updates accordingly. |
| `androidharness/config.py` | Modify — flesh out `ProvidersConfig`: a `default` provider name, a `use_litellm: bool = True` escape hatch, and a nested `providers: dict[str, ProviderEntry]` (`api_key_env`, `default_model`). |
| `androidharness/cli.py` | Modify — at `run` command entry, select the client based on `cfg.providers`; default behavior changes from "always `GoogleGenaiClient`" to "always `LiteLLMClient`". Env-var existence check switches from hard-coded `GOOGLE_API_KEY` to the selected provider's `api_key_env`. |
| `tests/test_llm.py` | **New.** Unit tests for `LiteLLMClient.generate` end-to-end with `litellm.completion` monkeypatched: message translation, tool translation, screenshot inlining, tool-call extraction, no-tool-call fallback. Also tests for `_contents_to_openai_messages` and `_tools_to_openai_tools` helpers directly. |
| `tests/test_config.py` | Modify — extend existing tests to cover the new `ProvidersConfig` fields (defaults, `extra="forbid"` rejects junk, unknown `default` provider rejected at validation). |
| `tests/test_cli_run_config.py` | Modify — assert `run` picks `LiteLLMClient` by default; with `providers.use_litellm: false` it falls back to `GoogleGenaiClient`. |
| `tests/test_agent.py` | Modify — only one tiny change: a comment/import update if `GeminiClient` symbol moves; the `fake_gemini` fixture's structural type still satisfies `LLMClient` (same `.generate(...)` signature) so the bulk of tests are unchanged. |

Existing `androidharness/device.py`, `androidharness/perception.py`, `androidharness/tools.py`, `androidharness/imaging.py`, and `androidharness/logging_setup.py` are **untouched** by this milestone.

---

## Task 1: Add the LiteLLM dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `litellm` to `dependencies`**

Edit the `dependencies` list in `pyproject.toml` so it ends up as (preserve order of surrounding entries; insert `litellm` after `pyyaml`):

```toml
dependencies = [
    "uiautomator2>=3.5.0",
    "uiautodev>=0.14.0",
    "google-genai>=0.3.0",
    "lxml>=5.0.0",
    "pillow>=10.0.0",
    "typer>=0.12.0",
    "adbutils[apk]>=2.12.0",
    "pydantic>=2.7.0",
    "pyyaml>=6.0.1",
    "litellm>=1.50.0",
]
```

- [ ] **Step 2: Sync the venv**

Run: `uv sync`
Expected: lockfile updates, `litellm` installs along with its transitive deps, exit code 0.

- [ ] **Step 3: Sanity-check import**

Run: `uv run python -c "import litellm; print(litellm.__version__)"`
Expected: prints a version string `>=1.50.0`, exit 0. (If LiteLLM ever changes its public symbol, this catches it before any code change.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): add litellm for v2 provider seam"
```

---

## Task 2: Create `androidharness/llm.py` skeleton with the relocated Protocol

**Files:**
- Create: `androidharness/llm.py`
- Modify: `androidharness/agent.py:101-104, 119, 256-339` (drop Protocol + concrete client, re-import as alias)
- Modify: `androidharness/runner.py:11-12`
- Test: existing `tests/test_agent.py` and `tests/test_runner.py` must keep passing (no production change yet).

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm.py` with the very first test that pins the module's public surface:

```python
from __future__ import annotations

from androidharness.llm import GoogleGenaiClient, LLMClient


def test_llm_module_exports_protocol_and_google_client():
    """The Protocol and the relocated Google client both live in androidharness.llm.
    GoogleGenaiClient must structurally satisfy the LLMClient Protocol — i.e. it
    exposes a `generate(*, model, system_instruction, contents, tools) -> dict`
    method. We don't need to instantiate it; just check the attribute is there."""
    assert hasattr(GoogleGenaiClient, "generate")
    # Protocol check at the type level — runtime structural check is enough here:
    assert callable(getattr(GoogleGenaiClient, "generate"))
    # LLMClient is a Protocol; importing it should succeed.
    assert LLMClient is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'androidharness.llm'`.

- [ ] **Step 3: Create `androidharness/llm.py` with the Protocol and a relocated `GoogleGenaiClient`**

Write the file. Copy `GoogleGenaiClient` verbatim from `androidharness/agent.py:256-338`. Add the `LLMClient` Protocol (same shape as the old `GeminiClient`). New file content:

```python
from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Provider-agnostic chat client. Implementations translate our internal
    `contents` shape into provider-native messages, send a tool-required
    completion, and return the first function call as a `{"name", "args"}`
    dict matching what the agent loop expects.

    Concrete impls:
      * `LiteLLMClient` — default; provider gateway via litellm.completion.
      * `GoogleGenaiClient` — direct google-genai SDK; kept as an escape hatch
        and as the reference implementation our v1 agent loop was developed
        against.
    """

    def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: list,
        tools: list,
    ) -> dict: ...


class GoogleGenaiClient:
    """Adapter over google-genai that returns the first function call from a response."""

    def __init__(self, api_key: str | None = None):
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def generate(self, *, model, system_instruction, contents, tools):
        from google.genai import types

        parts: list[Any] = []
        for entry in contents:
            role = entry.get("role", "context")
            if role == "user":
                parts.append(types.Part.from_text(text=f"Task: {entry.get('task', '')}"))
            elif role == "observation":
                parts.append(
                    types.Part.from_text(text=f"Observation:\n{entry.get('text', '')}")
                )
                shot = entry.get("screenshot")
                if shot:
                    parts.append(types.Part.from_bytes(data=shot, mime_type="image/png"))
            elif role == "tool_result":
                parts.append(
                    types.Part.from_text(
                        text=(
                            f"Previous tool {entry.get('tool')} -> "
                            f"{'ok' if entry.get('ok') else 'error'}: {entry.get('message', '')}"
                        )
                    )
                )

        gemini_tools = [
            types.Tool(function_declarations=[types.FunctionDeclaration(**fd) for fd in tools])
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        )
        import time as _time

        from google.genai import errors as _errors

        _TRANSIENT_INDICATORS = ("429", "500", "502", "503", "504")
        last_exc: Exception | None = None
        response = None
        for attempt in range(4):
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=config,
                )
                break
            except _errors.APIError as exc:
                msg = str(exc)
                if any(code in msg for code in _TRANSIENT_INDICATORS):
                    last_exc = exc
                    _time.sleep(2**attempt)
                else:
                    raise
            except Exception:
                raise
        else:
            raise last_exc  # type: ignore[misc]

        for cand in response.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    return {"name": fc.name, "args": dict(fc.args or {})}

        return {"name": "done", "args": {"success": False, "reason": "model did not call a tool"}}
```

- [ ] **Step 4: Modify `androidharness/agent.py` to import the Protocol from `llm.py` and drop the duplicate**

Remove the local `GeminiClient` Protocol declaration (lines 101-104) and the `GoogleGenaiClient` class (lines 256-338). Add at the top of the file (under existing imports):

```python
from androidharness.llm import LLMClient

# Back-compat alias: callers that still import `GeminiClient` from this module
# (e.g. tests, the runner) keep working. New code should use `LLMClient`.
GeminiClient = LLMClient
```

Change the `Agent` dataclass annotation from `client: GeminiClient` to `client: LLMClient`.

- [ ] **Step 5: Modify `androidharness/runner.py` to take its Protocol from `llm.py`**

Change `androidharness/runner.py:12` from:
```python
from androidharness.agent import Agent, GeminiClient
```
to:
```python
from androidharness.agent import Agent
from androidharness.llm import LLMClient
```

And change the `run_task` signature: `client: GeminiClient,` → `client: LLMClient,`.

- [ ] **Step 6: Run the test from Step 1**

Run: `uv run pytest tests/test_llm.py -v`
Expected: PASS.

- [ ] **Step 7: Run the existing suite to verify nothing regressed**

Run: `uv run pytest -q`
Expected: all green. Particularly `tests/test_agent.py` (the `FakeGeminiClient` is structurally compatible — still satisfies `LLMClient`). Note: the CLI still imports `from androidharness.agent import GoogleGenaiClient` — this still works because the next step rewires it, but if a test happens to fail here flagging `GoogleGenaiClient` is missing from `agent`, jump to Step 8 first.

- [ ] **Step 8: Rewire the CLI's `GoogleGenaiClient` import**

Change `androidharness/cli.py:10` from:
```python
from androidharness.agent import GoogleGenaiClient
```
to:
```python
from androidharness.llm import GoogleGenaiClient
```

- [ ] **Step 9: Re-run the full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add androidharness/llm.py androidharness/agent.py androidharness/runner.py androidharness/cli.py tests/test_llm.py
git commit -m "refactor(llm): move LLMClient Protocol + GoogleGenaiClient into androidharness.llm"
```

---

## Task 3: Add `_tools_to_openai_tools` helper

The Gemini function-declaration shape we feed into `tools=` uses uppercase type names (`"OBJECT"`, `"STRING"`, `"INTEGER"`, `"BOOLEAN"`, `"NUMBER"`). OpenAI / LiteLLM use JSON-schema lowercase. The helper lives in `androidharness/llm.py` and is private (`_`-prefixed) so it can be reused by other adapters later without becoming public surface.

**Files:**
- Modify: `androidharness/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm.py`:

```python
from androidharness.llm import _tools_to_openai_tools


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
    # If someone adds a new Gemini-style type, lowercasing should still produce
    # valid JSON schema for the common types and just lowercase the rest.
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 3 failures with `ImportError: cannot import name '_tools_to_openai_tools'`.

- [ ] **Step 3: Add the helper to `androidharness/llm.py`**

Append (under `GoogleGenaiClient`, before any future class definitions):

```python
def _lowercase_schema(schema: Any) -> Any:
    """Recursively lowercase any `"type"` field in a JSON-schema-ish dict.
    Gemini's function declarations use upper-case JSON Schema type names
    (`"OBJECT"`, `"STRING"`, …). OpenAI / LiteLLM expect lower-case. Leave
    all other keys untouched."""
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            else:
                out[k] = _lowercase_schema(v)
        return out
    if isinstance(schema, list):
        return [_lowercase_schema(x) for x in schema]
    return schema


def _tools_to_openai_tools(tools: list[dict]) -> list[dict]:
    """Translate Gemini-style function declarations to OpenAI / LiteLLM tool
    schema. The agent's `GEMINI_FUNCTION_DECLARATIONS` are the single source
    of truth; this helper exists so we don't have to maintain a parallel
    OpenAI-shaped copy."""
    out: list[dict] = []
    for fd in tools:
        params = _lowercase_schema(fd.get("parameters", {"type": "object", "properties": {}}))
        out.append(
            {
                "type": "function",
                "function": {
                    "name": fd["name"],
                    "description": fd.get("description", ""),
                    "parameters": params,
                },
            }
        )
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v`
Expected: all 4 tests pass (the earlier `test_llm_module_exports_protocol_and_google_client` from Task 2 plus the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): _tools_to_openai_tools helper (Gemini fd -> OpenAI tool schema)"
```

---

## Task 4: Add `_contents_to_openai_messages` helper

This is the big translation: our internal `contents` list (a flat sequence of `user` / `observation` / `tool_result` dicts) becomes OpenAI-style chat messages. We flatten into mostly user-role text messages — the same lossy-but-faithful approach `GoogleGenaiClient` already uses — because the agent's `contents` doesn't record the assistant's tool-call ids, so we can't reconstruct an OpenAI-strict `assistant tool_calls / tool` pair. LiteLLM accepts the flattened form against every supported provider.

**Files:**
- Modify: `androidharness/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py`:

```python
from androidharness.llm import _contents_to_openai_messages


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
    # System + the observation as a user message.
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
    # Multi-part content list.
    parts = msg["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "Observation:\n[1] Button Settings"}
    assert parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    # Make sure the bytes are actually base64'd in.
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
    # System + user task, nothing else.
    assert len(out) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 5 new failures with `ImportError: cannot import name '_contents_to_openai_messages'`.

- [ ] **Step 3: Add the helper to `androidharness/llm.py`**

Append:

```python
def _contents_to_openai_messages(
    *,
    system_instruction: str,
    contents: list[dict],
) -> list[dict]:
    """Flatten the agent's internal contents into OpenAI chat messages.

    Translation rules:
      * system_instruction → `{"role": "system", "content": ...}` at index 0.
      * `{"role": "user", "task": T}` → `{"role": "user", "content": "Task: T"}`.
      * `{"role": "observation", "text": O}` →
            `{"role": "user", "content": "Observation:\n" + O}`,
        plus an inlined `image_url` part when a `"screenshot"` (bytes) is
        present — uses the OpenAI vision `data:image/png;base64,…` form.
      * `{"role": "tool_result", "tool": T, "ok": B, "message": M}` →
            `{"role": "user", "content": "Previous tool T -> ok|error: M"}`.
      * Unknown roles are dropped silently — keeps the flattener resilient as
        new roles are added during development.

    We do not emit OpenAI-strict `assistant tool_calls` / `tool` pairs because
    the agent's contents doesn't carry tool-call ids. The flattened form
    works against every LiteLLM-supported provider.
    """
    import base64

    out: list[dict] = [{"role": "system", "content": system_instruction}]
    for entry in contents:
        role = entry.get("role", "")
        if role == "user":
            out.append({"role": "user", "content": f"Task: {entry.get('task', '')}"})
        elif role == "observation":
            text = f"Observation:\n{entry.get('text', '')}"
            shot = entry.get("screenshot")
            if shot:
                data_url = "data:image/png;base64," + base64.b64encode(shot).decode("ascii")
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": text},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                )
            else:
                out.append({"role": "user", "content": text})
        elif role == "tool_result":
            verdict = "ok" if entry.get("ok") else "error"
            out.append(
                {
                    "role": "user",
                    "content": (
                        f"Previous tool {entry.get('tool')} -> "
                        f"{verdict}: {entry.get('message', '')}"
                    ),
                }
            )
        # else: drop unknown roles silently.
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): _contents_to_openai_messages helper (agent contents -> OpenAI chat)"
```

---

## Task 5: Implement `LiteLLMClient.generate`

The end-to-end adapter. Uses LiteLLM's `completion()` with `tool_choice="required"` (analog of Gemini's `mode="ANY"`) and pulls the first function call out of `response.choices[0].message.tool_calls`. Falls back to `done(success=False)` when the model spoke without calling a tool — same contract `GoogleGenaiClient` already honors so the agent loop sees no difference.

**Files:**
- Modify: `androidharness/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py`:

```python
import json
import types as _types

import pytest

from androidharness.llm import LiteLLMClient


class _StubMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _StubFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _StubToolCall:
    def __init__(self, name: str, arguments_json: str):
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

    # And let's verify the kwargs that were forwarded to litellm.completion.
    assert captured[0]["model"] == "gemini/gemini-2.5-flash"
    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["messages"][0] == {"role": "system", "content": "SYS"}
    assert captured[0]["tools"][0]["function"]["name"] == "tap"
    assert captured[0]["tools"][0]["function"]["parameters"]["type"] == "object"


def test_litellm_client_handles_dict_arguments_already_parsed(monkeypatch):
    """LiteLLM normally returns `arguments` as a JSON string, but some providers
    surface it pre-parsed. Accept both."""
    tool_call = _StubToolCall("tap", {"id": 3})  # type: ignore[arg-type]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 5 new failures with `ImportError: cannot import name 'LiteLLMClient'`.

- [ ] **Step 3: Implement `LiteLLMClient` in `androidharness/llm.py`**

Append (after the two helpers):

```python
import json as _json
import logging as _logging

_llm_log = _logging.getLogger("androidharness.llm")


class LiteLLMClient:
    """LiteLLM-backed `LLMClient`. One adapter, many providers.

    Caller passes `model` in LiteLLM's `provider/model` form
    (`gemini/gemini-2.5-flash`, `anthropic/claude-haiku-4-5`,
    `openai/gpt-4o-mini`, …) — see https://docs.litellm.ai/docs/providers.
    API keys are read from env vars by LiteLLM itself; we don't carry them
    in the client.
    """

    def __init__(self, *, num_retries: int = 3) -> None:
        # Import inside __init__ so importing the module is cheap and tests
        # that monkeypatch `litellm.completion` work whether they patch before
        # or after instantiation.
        import litellm

        self._litellm = litellm
        self._num_retries = num_retries

    def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: list,
        tools: list,
    ) -> dict:
        messages = _contents_to_openai_messages(
            system_instruction=system_instruction,
            contents=contents,
        )
        openai_tools = _tools_to_openai_tools(tools)

        response = self._litellm.completion(
            model=model,
            messages=messages,
            tools=openai_tools,
            tool_choice="required",
            num_retries=self._num_retries,
        )

        # Safety-blocked / empty-response: definitive done(success=False).
        if not response.choices:
            _llm_log.warning("litellm returned zero choices for model=%s", model)
            return {
                "name": "done",
                "args": {"success": False, "reason": "model did not call a tool"},
            }

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            _llm_log.info("litellm: no tool_calls in response; falling back to done()")
            return {
                "name": "done",
                "args": {"success": False, "reason": "model did not call a tool"},
            }

        first = tool_calls[0]
        name = first.function.name
        raw_args = first.function.arguments
        if isinstance(raw_args, str):
            try:
                args = _json.loads(raw_args) if raw_args else {}
            except _json.JSONDecodeError:
                _llm_log.warning("litellm: tool args were not valid JSON: %r", raw_args)
                args = {}
        else:
            # Some providers / LiteLLM versions return a pre-parsed dict.
            args = dict(raw_args or {})

        return {"name": name, "args": args}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v`
Expected: all 14 tests pass (4 from Tasks 2–3, plus 5 from Task 4, plus 5 from Task 5).

- [ ] **Step 5: Commit**

```bash
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): LiteLLMClient — provider-agnostic LLMClient via litellm.completion"
```

---

## Task 6: Flesh out `ProvidersConfig`

Give the providers section enough shape for the CLI to pick the right client and surface a sensible env-var-missing error. Stay minimal: this is roadmap item #2, not the throttler / Router (#3) or the Settings UI (#5).

**Shape on disk:**

```yaml
providers:
  use_litellm: true             # escape hatch: set false to use GoogleGenaiClient
  default: gemini               # key into the `entries` map below
  entries:
    gemini:
      api_key_env: GEMINI_API_KEY
      default_model: gemini/gemini-2.5-flash
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
      default_model: anthropic/claude-haiku-4-5
    openai:
      api_key_env: OPENAI_API_KEY
      default_model: openai/gpt-4o-mini
```

**Files:**
- Modify: `androidharness/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
import pytest

from androidharness.config import (
    AndroidHarnessConfig,
    ConfigError,
    ProviderEntry,
    ProvidersConfig,
    load_config,
)


def test_providers_config_defaults_to_gemini_via_litellm():
    cfg = AndroidHarnessConfig()
    p = cfg.providers
    assert p.use_litellm is True
    assert p.default == "gemini"
    assert "gemini" in p.entries
    assert p.entries["gemini"].api_key_env == "GEMINI_API_KEY"
    # The LiteLLM-shaped default model name (provider/model).
    assert p.entries["gemini"].default_model.startswith("gemini/")


def test_providers_config_rejects_unknown_default_provider():
    with pytest.raises(Exception):  # pydantic ValidationError
        ProvidersConfig(default="not-a-provider", entries={"gemini": ProviderEntry(
            api_key_env="GEMINI_API_KEY", default_model="gemini/gemini-2.5-flash",
        )})


def test_providers_config_rejects_unknown_field():
    """extra='forbid' must still hold on the new fields."""
    with pytest.raises(Exception):
        ProvidersConfig(use_litellm=True, default="gemini", entries={}, junk=1)


def test_providers_entry_loads_from_yaml_round_trip(tmp_path):
    yaml_text = """\
version: 1
providers:
  use_litellm: false
  default: anthropic
  entries:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
      default_model: anthropic/claude-haiku-4-5
"""
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = load_config(p)
    assert cfg.providers.use_litellm is False
    assert cfg.providers.default == "anthropic"
    assert cfg.providers.entries["anthropic"].default_model == "anthropic/claude-haiku-4-5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 failures — `ProviderEntry` import missing, plus existing `ProvidersConfig` rejects new fields.

- [ ] **Step 3: Replace `ProvidersConfig` in `androidharness/config.py`**

Replace the existing `ProvidersConfig` block (the 3-line "Placeholder" class) with:

```python
class ProviderEntry(BaseModel):
    model_config = _STRICT

    api_key_env: str
    default_model: str


def _default_provider_entries() -> dict[str, ProviderEntry]:
    return {
        "gemini": ProviderEntry(
            api_key_env="GEMINI_API_KEY",
            default_model="gemini/gemini-2.5-flash",
        ),
        "anthropic": ProviderEntry(
            api_key_env="ANTHROPIC_API_KEY",
            default_model="anthropic/claude-haiku-4-5",
        ),
        "openai": ProviderEntry(
            api_key_env="OPENAI_API_KEY",
            default_model="openai/gpt-4o-mini",
        ),
    }


class ProvidersConfig(BaseModel):
    """Provider seam config (milestone 2).

    * `use_litellm` is an escape hatch — set False to fall back to the v1
      `GoogleGenaiClient` while LiteLLM is still bedding in.
    * `default` selects which entry of `entries` the CLI uses when the user
      doesn't pass --model.
    * Each entry names the env var holding the API key and the LiteLLM-shaped
      model identifier (`provider/model`).
    """

    model_config = _STRICT

    use_litellm: bool = True
    default: str = "gemini"
    entries: dict[str, ProviderEntry] = Field(default_factory=_default_provider_entries)

    def model_post_init(self, __context) -> None:  # noqa: D401  (pydantic hook)
        if self.default not in self.entries:
            raise ValueError(
                f"providers.default={self.default!r} is not a key in providers.entries "
                f"(have: {sorted(self.entries)})"
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: all green.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: all green. Existing CLI / config round-trip tests should pass unchanged — the new fields are additive.

- [ ] **Step 6: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): flesh out ProvidersConfig — use_litellm + per-provider entries"
```

---

## Task 7: Wire the CLI to pick `LiteLLMClient` by default

**Files:**
- Modify: `androidharness/cli.py:161-166` (env-var check + client instantiation)
- Modify: `tests/test_cli_run_config.py`

The relevant block of `androidharness/cli.py` currently reads (lines 161-166):

```python
    if not os.environ.get("GOOGLE_API_KEY"):
        typer.echo("error: GOOGLE_API_KEY env var is not set", err=True)
        raise typer.Exit(code=1)

    device = UIAutomatorDevice.connect(chosen)
    client = GoogleGenaiClient()
```

We replace it with a selection helper plus an env-var check against the chosen provider's `api_key_env`.

- [ ] **Step 1: Write the failing tests**

Look at `tests/test_cli_run_config.py` first to understand how the existing tests stub out the device / client side. Then append:

```python
import os
from unittest.mock import patch

from typer.testing import CliRunner

from androidharness.cli import app
from androidharness.config import AndroidHarnessConfig


def _write_cfg(tmp_path, cfg_dict):
    import yaml
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg_dict, sort_keys=False))
    return p


def test_cli_run_uses_litellm_client_by_default(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    # Patch the *symbols imported into androidharness.cli*, not the original
    # module paths — the CLI binds them at import time.
    with patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = CliRunner().invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    lite.assert_called_once()
    google.assert_not_called()


def test_cli_run_falls_back_to_google_when_use_litellm_false(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["providers"]["use_litellm"] = False
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = CliRunner().invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    google.assert_called_once()
    lite.assert_not_called()


def test_cli_run_errors_when_selected_provider_api_key_env_var_missing(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]):
        result = CliRunner().invoke(app, ["run", "x", "--config", str(cfg_path)])

    assert result.exit_code == 1
    assert "GEMINI_API_KEY" in (result.stdout + (result.stderr or ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_run_config.py -v`
Expected: 3 new failures — `LiteLLMClient` not importable from `androidharness.cli`, and the env-var check still hard-codes `GOOGLE_API_KEY`.

- [ ] **Step 3: Modify `androidharness/cli.py`: import `LiteLLMClient` and pick the client by config**

Top of `androidharness/cli.py`: change the existing import line for `GoogleGenaiClient` to import both:

```python
from androidharness.llm import GoogleGenaiClient, LiteLLMClient
```

If the prior Task 2 left it as `from androidharness.llm import GoogleGenaiClient`, just widen the import.

Then replace the block at lines 161-166 (`if not os.environ.get("GOOGLE_API_KEY"):` … `client = GoogleGenaiClient()`) with:

```python
    # Select which provider's API key to require, based on the configured default.
    providers = cfg.providers
    if providers.default not in providers.entries:
        typer.echo(
            f"error: providers.default={providers.default!r} not found in providers.entries",
            err=True,
        )
        raise typer.Exit(code=1)
    selected = providers.entries[providers.default]
    if not os.environ.get(selected.api_key_env):
        typer.echo(
            f"error: {selected.api_key_env} env var is not set "
            f"(required for providers.default={providers.default!r})",
            err=True,
        )
        raise typer.Exit(code=1)

    # If the user didn't pass --model, fall back to the selected provider's default.
    if model == cfg.defaults.model and providers.use_litellm:
        # Override the bare gemini-2.5-flash from defaults with the provider's
        # litellm-shaped name so LiteLLM routes it correctly.
        model = selected.default_model

    device = UIAutomatorDevice.connect(chosen)
    client = LiteLLMClient() if providers.use_litellm else GoogleGenaiClient()
```

- [ ] **Step 4: Run the new CLI tests**

Run: `uv run pytest tests/test_cli_run_config.py -v`
Expected: all green (existing + new).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add androidharness/cli.py tests/test_cli_run_config.py
git commit -m "feat(cli): default to LiteLLMClient; env-var check follows providers.default"
```

---

## Task 8: Smoke test against a live provider (manual)

Automated tests cover every translation path, but the first real network call is still load-bearing. Run a tiny end-to-end task against the real Gemini API to confirm LiteLLM routes correctly and the agent loop is content with the responses. This task is one-shot — no commit.

**Pre-reqs:** an ADB-connected device (or emulator) and `GEMINI_API_KEY` set.

- [ ] **Step 1: Verify the API key resolves**

Run: `uv run python -c "import os; print(bool(os.environ.get('GEMINI_API_KEY')))"`
Expected: `True`. If `False`, export the key before continuing.

- [ ] **Step 2: Run a one-turn smoke task**

Run: `uv run androidharness run "press the home button" --max-turns 3 --wall-clock 60`
Expected:
- Exit code 0 or 1 (1 is fine if the model `done(success=False)`'s for some reason — we're checking the wiring, not the agent's IQ).
- `runs/<timestamp>-<hex>/turns.jsonl` exists with at least one turn.
- No `litellm` traceback in stderr.

- [ ] **Step 3: Spot-check the run artifact**

Run: `ls runs | sort | tail -1 | xargs -I{} cat runs/{}/result.json`
Expected: a valid JSON result blob with `status`, `success`, `reason`, `turns`.

- [ ] **Step 4 (only if Step 2 failed): rollback escape hatch**

If LiteLLM blows up against Gemini for any reason, you don't need to revert code — flip the escape hatch:

```bash
uv run androidharness config init --force   # writes a fresh config
# then edit ~/.androidharness/config.yaml and set providers.use_litellm: false
```

This restores the v1 path (`GoogleGenaiClient`) without code changes, and you can file the LiteLLM bug separately.

---

## Self-review

**Spec coverage (§3 + roadmap item #2):**

| Spec line | Where it lands |
|---|---|
| "`LiteLLMClient` implementing the existing `GeminiClient` Protocol (rename to `LLMClient`)" | Task 2 (rename + relocate), Task 5 (implementation) |
| "Returns the same `{"name", "args"}` shape the agent expects" | Task 5, `test_litellm_client_returns_first_tool_call_with_parsed_args` |
| "Throttler wrapper that maintains a token-bucket" | **Deferred to milestone 3.** This plan only wires `num_retries=3` into LiteLLM, which absorbs short transient blips. Out of scope. |
| "Config in `pyproject.toml` extras and an `androidharness.yaml`: ordered fallback list" | Partially: Task 6 ships the entries map; the *ordered fallback list* belongs to LiteLLM's `Router` and lands with the throttler (milestone 3). Captured in the file comment in `config.py`. |
| "Cost ledger: LiteLLM emits per-call cost; we sum into the run's SQLite row" | **Deferred to milestone 7 (`SQLiteSink`).** No SQLite row to sum into yet. |
| "`GoogleGenaiClient` becomes one implementation of `LLMClient`. `LiteLLMClient` becomes the default." | Tasks 2, 6, 7 |
| "Agent code is untouched." | Verified by Task 2 Step 7 — `tests/test_agent.py` passes after only an import-level edit |

**Placeholder scan:** No `TODO`, `TBD`, "add appropriate", "similar to Task N", or "fill in" markers remain. Every code step has the literal code. Every test step has the literal test body. Every run step names the command and the expected outcome.

**Type consistency:**
- `LLMClient.generate(*, model, system_instruction, contents, tools) -> dict` — used identically in Task 2 (Protocol), Task 5 (`LiteLLMClient.generate`), Task 2 Step 3 (`GoogleGenaiClient.generate`).
- `_contents_to_openai_messages(*, system_instruction, contents)` — defined in Task 4, called in Task 5.
- `_tools_to_openai_tools(tools)` — defined in Task 3, called in Task 5.
- `ProviderEntry(api_key_env, default_model)` — defined in Task 6, referenced in Task 7.
- `ProvidersConfig(use_litellm, default, entries)` — defined in Task 6, used in Task 7.

All references match. Plan is self-consistent.

**Deferred items (explicit, not bugs):**
- Throttler / token bucket / Router fallback → milestone 3.
- LiteLLM cost ledger persistence → milestone 7 (needs SQLite).
- Settings UI Providers panel → milestone 5.
