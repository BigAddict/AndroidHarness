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
                "observation_payload": obs_payload,
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
