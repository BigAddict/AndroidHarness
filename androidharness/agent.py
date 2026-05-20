from __future__ import annotations

import logging
import time
from collections.abc import Callable
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

_log = logging.getLogger("androidharness.agent")

SYSTEM_PROMPT = """You are controlling a real Android device to complete a user task.
Each turn you receive:
  * The user task (sticky).
  * The previous tool's result (if any).
  * The current UI as a numbered list of interactable nodes (the "Observation").
  * Optionally, a screenshot if you requested it via show_screen() last turn.

Rules:
  * Always act through the provided tools — never describe an action without calling a tool.
  * Refer to UI elements by their [id] from the current Observation only.
    Ids are not stable across turns.
  * If the UI tree does not contain enough information, call show_screen() to get a screenshot
    on the next turn.
  * For whole-screen scrolling (app drawer, long page, settings list) prefer
    swipe(direction='up') over scroll(). Only use scroll(id=N) when the target node's
    class clearly names a scrollable container such as RecyclerView, ListView, or
    ScrollView — never use scroll on a FrameLayout / ViewGroup / launcher root, which
    on many phones is treated as a dismiss gesture rather than a scroll.
  * Prefer answering the user's question without installing new apps. Only install an
    app when there is no on-device path (existing app, settings screen, system info)
    that would produce the answer.
  * If a previous tool returned a NO_PROGRESS warning, do NOT repeat the same call.
    Switch tactics: call show_screen() if the tree is unclear, pick a different element,
    swap scroll for swipe (or vice versa), or press_key('back') to escape.
  * When the task is complete (or definitively impossible), call done(success, reason).
  * Prefer the smallest sequence of actions that achieves the task."""

_NO_PROGRESS_WINDOW = 3  # warn after this many identical calls with no UI change


def _signature(args: dict) -> tuple:
    """Hashable signature of a tool call's args. Args are primitives in v1."""
    return tuple(sorted(args.items(), key=lambda kv: kv[0]))


def _is_stalled(turn_log: list[dict], current_obs_render: str) -> bool:
    """Return True if the last N turns made the same call AND the observation
    hasn't changed across that window."""
    if len(turn_log) < _NO_PROGRESS_WINDOW:
        return False
    recent = turn_log[-_NO_PROGRESS_WINDOW:]
    first_sig = (
        recent[0]["tool_call"]["name"],
        _signature(recent[0]["tool_call"]["args"]),
    )
    same_call = all(
        (t["tool_call"]["name"], _signature(t["tool_call"]["args"])) == first_sig
        for t in recent
    )
    same_obs = all(t["observation_summary"] == current_obs_render for t in recent)
    return same_call and same_obs


class GeminiClient(Protocol):
    def generate(
        self, *, model: str, system_instruction: str, contents: list, tools: list
    ) -> dict: ...


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

    def run(
        self,
        task: str,
        *,
        on_turn: Callable[[dict], None] | None = None,
    ) -> RunResult:
        contents: list[dict] = [{"role": "user", "task": task}]
        turn_log: list[dict] = []
        needs_screenshot = False
        started = time.monotonic()
        _log.info("run start: task=%r model=%s max_turns=%d", task, self.model, self.max_turns)

        for turn_idx in range(1, self.max_turns + 1):
            if time.monotonic() - started > self.wall_clock_s:
                _log.warning("wall-clock timeout after %d turns", turn_idx - 1)
                return RunResult(
                    status="timeout",
                    success=None,
                    reason="wall clock",
                    turns=turn_idx - 1,
                    turn_log=turn_log,
                )

            xml = self.device.dump_hierarchy()
            obs = parse_hierarchy(xml)
            obs_payload: dict[str, Any] = {"role": "observation", "text": obs.render()}
            if needs_screenshot:
                obs_payload["screenshot"] = self.device.screenshot()
                needs_screenshot = False
                _log.info("turn %d: screenshot attached (%d bytes)",
                          turn_idx, len(obs_payload["screenshot"]))
            contents.append(obs_payload)
            _log.info("turn %d: observation has %d nodes", turn_idx, len(obs.nodes))

            if _is_stalled(turn_log, obs.render()):
                last = turn_log[-1]["tool_call"]
                warning = (
                    f"NO_PROGRESS: the last {_NO_PROGRESS_WINDOW} turns all called "
                    f"{last['name']}({last['args']}) and the Observation did not change. "
                    "Switch tactics — try show_screen(), a different element id, swap "
                    "scroll for swipe (or vice versa), or press_key('back') to escape."
                )
                contents.append({
                    "role": "tool_result", "tool": "system",
                    "ok": False, "message": warning,
                })
                _log.warning("no-progress loop at turn %d (%dx %s, obs unchanged)",
                             turn_idx, _NO_PROGRESS_WINDOW, last["name"])

            raw = self.client.generate(
                model=self.model,
                system_instruction=SYSTEM_PROMPT,
                contents=contents,
                tools=GEMINI_FUNCTION_DECLARATIONS,
            )
            call = ToolCall(name=raw["name"], args=dict(raw.get("args", {})))
            _log.info("turn %d: model called %s(%s)", turn_idx, call.name, call.args)

            try:
                result = execute(self.device, call, obs)
            except Exception as e:
                # Device drivers can raise transport errors, assertion errors,
                # etc. mid-call. Surface as ToolError so the agent gets a chance
                # to react instead of crashing the whole run.
                _log.exception("turn %d: tool dispatch raised", turn_idx)
                result = ToolError(f"tool {call.name} raised {type(e).__name__}: {e}")
            _log.info("turn %d: result ok=%s msg=%s",
                      turn_idx, isinstance(result, ToolResult), result.message)

            tool_result_payload = {
                "role": "tool_result",
                "tool": call.name,
                "ok": isinstance(result, ToolResult),
                "message": result.message,
            }
            contents.append(tool_result_payload)

            turn_log.append(
                {
                    "turn": turn_idx,
                    "observation_summary": obs.render(),
                    "observation_payload": dict(obs_payload),  # shallow copy; runner may mutate
                    "tool_call": {"name": call.name, "args": call.args},
                    "tool_result": tool_result_payload,
                }
            )
            if on_turn is not None:
                on_turn(turn_log[-1])

            if isinstance(result, ToolResult):
                if result.is_done:
                    _log.info("run done: success=%s reason=%r turns=%d",
                              result.done_success, result.done_reason, turn_idx)
                    return RunResult(
                        status="done",
                        success=result.done_success,
                        reason=result.done_reason,
                        turns=turn_idx,
                        turn_log=turn_log,
                    )
                if result.requests_screenshot:
                    needs_screenshot = True

        _log.warning("max turns (%d) reached without done()", self.max_turns)
        return RunResult(
            status="max_turns",
            success=None,
            reason="max turns reached",
            turns=self.max_turns,
            turn_log=turn_log,
        )


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

        # Find the first function call in the response.
        for cand in response.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    return {"name": fc.name, "args": dict(fc.args or {})}

        # Model spoke without calling a tool — surface as done(success=False).
        return {"name": "done", "args": {"success": False, "reason": "model did not call a tool"}}
