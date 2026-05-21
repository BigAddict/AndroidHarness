from __future__ import annotations

import logging
import select
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from androidharness.tools import ToolCall, ToolError, ToolResult

if TYPE_CHECKING:
    from androidharness.config import PolicyConfig

_log = logging.getLogger("androidharness.policy")


class PolicyDecision(StrEnum):
    """Resolved policy for one tool call. String values match the YAML mode
    strings so `PolicyDecision(cfg_mode)` round-trips."""

    AUTO = "auto"
    CONFIRM = "confirm"
    DRY_RUN = "dry-run"
    DENY = "deny"


class Confirmer(Protocol):
    """Inject this into the agent to handle `confirm`-mode tool calls.
    Implementations:
      * `CliConfirmer` — interactive y/N on stdin with a timeout.
      * `AlwaysApproveConfirmer` / `AlwaysRejectConfirmer` — for tests.
      * `RecordingConfirmer` — scripted answers + per-call log for tests."""

    def ask(self, call: ToolCall) -> bool: ...


class AlwaysApproveConfirmer:
    def ask(self, call: ToolCall) -> bool:  # noqa: ARG002 (Protocol signature)
        return True


class AlwaysRejectConfirmer:
    def ask(self, call: ToolCall) -> bool:  # noqa: ARG002
        return False


@dataclass
class RecordingConfirmer:
    """Test helper: returns the next scripted answer and records every call."""

    answers: list[bool]
    calls: list[ToolCall] = field(default_factory=list)
    _idx: int = field(default=0, init=False)

    def ask(self, call: ToolCall) -> bool:
        self.calls.append(call)
        answer = self.answers[self._idx]  # raises IndexError when exhausted
        self._idx += 1
        return answer


ExecuteFn = Callable[[ToolCall], "ToolResult | ToolError"]


@dataclass
class Policy:
    """Gates every tool call. Owns the per-tool decision lookup and the
    `auto / confirm / dry-run / deny` dispatch."""

    default: PolicyDecision = PolicyDecision.AUTO
    per_tool: dict[str, PolicyDecision] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: PolicyConfig) -> Policy:
        return cls(
            default=PolicyDecision(cfg.default_mode),
            per_tool={name: PolicyDecision(mode) for name, mode in cfg.per_tool.items()},
        )

    def decide(self, tool_name: str) -> PolicyDecision:
        return self.per_tool.get(tool_name, self.default)

    def apply(
        self,
        call: ToolCall,
        execute_fn: ExecuteFn,
        confirmer: Confirmer,
    ) -> ToolResult | ToolError:
        decision = self.decide(call.name)
        _log.info("policy: %s -> %s", call.name, decision.value)

        if decision == PolicyDecision.AUTO:
            return execute_fn(call)

        if decision == PolicyDecision.CONFIRM:
            if confirmer.ask(call):
                # Tag the message so the run artifact distinguishes a
                # user-approved confirm call from a pure auto call. Errors
                # pass through untouched — the failure mode is more useful.
                out = execute_fn(call)
                if isinstance(out, ToolResult):
                    return ToolResult(
                        message=f"[confirmed] {out.message}",
                        is_done=out.is_done,
                        done_success=out.done_success,
                        done_reason=out.done_reason,
                        requests_screenshot=out.requests_screenshot,
                    )
                return out
            return ToolError(f"user rejected: {call.name}({call.args})")

        if decision == PolicyDecision.DRY_RUN:
            return ToolResult(message=f"dry-run: would have called {call.name}({call.args})")

        # DENY
        return ToolError(f"policy=deny: refused {call.name}({call.args})")


class CliConfirmer:
    """Interactive `y/N` confirmer for the CLI. Reads stdin with a timeout
    so unattended runs auto-reject rather than block forever.

    Uses `select.select` for the timeout, which is Linux/macOS-only — the
    rest of the project already assumes a POSIX environment via ADB.
    """

    def __init__(self, timeout_s: int = 30) -> None:
        self._timeout_s = timeout_s

    def ask(self, call: ToolCall) -> bool:
        prompt = (
            f"\n[policy] approve {call.name}({call.args})? "
            f"[y/N, {int(self._timeout_s)}s timeout] "
        )
        # Write to stderr so the prompt doesn't pollute any captured stdout.
        sys.stderr.write(prompt)
        sys.stderr.flush()

        rlist, _, _ = select.select([sys.stdin], [], [], self._timeout_s)
        if not rlist:
            sys.stderr.write("[policy] timeout — rejecting\n")
            sys.stderr.flush()
            return False

        answer = sys.stdin.readline().strip().lower()
        return answer in {"y", "yes"}
