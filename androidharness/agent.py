from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from androidharness.imaging import quantize_png
from androidharness.llm import LLMClient
from androidharness.perception import parse_hierarchy
from androidharness.policy import AlwaysRejectConfirmer, Confirmer, Policy
from androidharness.tools import (
    GEMINI_FUNCTION_DECLARATIONS,
    ToolCall,
    ToolError,
    ToolResult,
    execute,
)

# Back-compat alias: callers that still import `GeminiClient` from this module
# (e.g. the runner, tests) keep working. New code should use `LLMClient`.
GeminiClient = LLMClient

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
  * If a tool returns ok=False, try a different approach to the same goal before
    navigating elsewhere. Examples: if type() fails on a lock-screen or secure
    input, tap the digit/character buttons one at a time and then tap OK; if
    tap() fails because an id is stale, look for a node with the same label or
    resource-id in the current observation and use that id instead.
  * If a previous tool returned a NO_PROGRESS warning, do NOT repeat the same call.
    Switch tactics: call show_screen() if the tree is unclear, pick a different element,
    swap scroll for swipe (or vice versa), or press_key('back') to escape.
  * To write a long body of text (a note, a message, a paragraph): send ONE type() call
    with the full content. Chunking across multiple type() calls wastes turns and the
    field's observable text may lag, making it hard to track what's already there. Use
    replace=true when you want to rewrite a field; default behavior appends.
  * If type() returns ok=False with a message about maxLength or a toast, the field
    silently truncated the input — Android toasts float above the accessibility tree,
    so the Observation can never show them. The message contains the field's actual
    end-state. Adapt: shorten the text, switch to a different field, or accept the
    truncated value. Do NOT retry the same long input expecting a different result.
  * When the task is complete (or definitively impossible), call done(success, reason).
  * Prefer the smallest sequence of actions that achieves the task."""

_NO_PROGRESS_WINDOW = 3  # warn after this many identical calls with no UI change


def _format_exception(e: BaseException) -> str:
    """Render a tool-dispatch exception as a short, model-readable string.

    `str(AssertionError())` is empty — gives the model nothing to act on. When
    the message is missing, fall back to the originating frame so the model
    sees `at .../uiautomator2/__init__.py:157 in _convert` instead of a bare
    `AssertionError:`.
    """
    import traceback

    name = type(e).__name__
    msg = str(e).strip()
    if msg:
        return f"{name}: {msg}"
    tb = traceback.extract_tb(e.__traceback__)
    if tb:
        last = tb[-1]
        return f"{name} at {last.filename}:{last.lineno} in {last.name}"
    return f"{name}()"


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
    client: LLMClient
    model: str = "gemini-2.5-flash"
    max_turns: int = 40
    wall_clock_s: float = 600.0
    quantize_screenshots: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False
    policy: Policy = field(default_factory=Policy)
    # AlwaysRejectConfirmer: fail-closed default. If a caller enables `confirm`
    # mode without injecting a real confirmer, the call is rejected rather than
    # silently approved.
    confirmer: Confirmer = field(default_factory=AlwaysRejectConfirmer)

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

            # Dump hierarchy and screenshot (when requested) concurrently —
            # each is a 1-2s ADB round-trip on a real device.
            if needs_screenshot:
                with ThreadPoolExecutor(max_workers=2) as ex:
                    xml_future = ex.submit(self.device.dump_hierarchy)
                    ss_future = ex.submit(self.device.screenshot)
                    xml = xml_future.result()
                    screenshot_bytes = ss_future.result()
                if self.quantize_screenshots:
                    screenshot_bytes = quantize_png(screenshot_bytes)
            else:
                xml = self.device.dump_hierarchy()
                screenshot_bytes = None

            obs = parse_hierarchy(xml, viewport_filter=self.viewport_filter)
            obs_payload: dict[str, Any] = {
                "role": "observation",
                "text": obs.render(with_resource_ids=self.resource_id_in_render),
            }
            if screenshot_bytes is not None:
                obs_payload["screenshot"] = screenshot_bytes
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

            def _run_tool(
                c: ToolCall,
                _obs=obs,
                _turn_idx=turn_idx,
            ) -> ToolResult | ToolError:
                # Keep the original exception-to-ToolError shielding around
                # the device call; policy.apply will receive the result either
                # way and forward it to the model.
                try:
                    return execute(self.device, c, _obs)
                except Exception as e:
                    _log.exception("turn %d: tool dispatch raised", _turn_idx)
                    return ToolError(f"tool {c.name} raised {_format_exception(e)}")

            result = self.policy.apply(call, _run_tool, self.confirmer)
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


