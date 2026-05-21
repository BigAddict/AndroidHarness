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

    def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: list,
        tools: list,
    ) -> dict:
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
