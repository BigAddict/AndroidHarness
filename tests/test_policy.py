from __future__ import annotations

from io import StringIO

import pytest

from androidharness.config import PolicyConfig
from androidharness.policy import (
    AlwaysApproveConfirmer,
    AlwaysRejectConfirmer,
    CliConfirmer,
    Policy,
    PolicyDecision,
    RecordingConfirmer,
)
from androidharness.tools import ToolCall, ToolError, ToolResult

# ---------------------------------------------------------------------------
# Part A — enum + confirmers
# ---------------------------------------------------------------------------


def test_policy_decision_values_match_config_mode_strings():
    """The enum's string values must equal what users write in YAML, so
    `PolicyDecision(cfg_mode_string)` round-trips cleanly."""
    assert PolicyDecision.AUTO.value == "auto"
    assert PolicyDecision.CONFIRM.value == "confirm"
    assert PolicyDecision.DRY_RUN.value == "dry-run"
    assert PolicyDecision.DENY.value == "deny"


def test_always_approve_confirmer_returns_true():
    assert AlwaysApproveConfirmer().ask(ToolCall(name="tap", args={"id": 1})) is True


def test_always_reject_confirmer_returns_false():
    assert AlwaysRejectConfirmer().ask(ToolCall(name="tap", args={"id": 1})) is False


def test_recording_confirmer_logs_each_call_and_returns_scripted_answers():
    """Useful when a test wants to assert ordering, args, and a sequence of
    yes/no decisions in the same run."""
    c = RecordingConfirmer(answers=[True, False])
    c1 = ToolCall(name="tap", args={"id": 1})
    c2 = ToolCall(name="type", args={"id": 2, "text": "hi"})
    assert c.ask(c1) is True
    assert c.ask(c2) is False
    assert c.calls == [c1, c2]


def test_recording_confirmer_raises_when_script_runs_out():
    c = RecordingConfirmer(answers=[True])
    c.ask(ToolCall(name="tap", args={"id": 1}))
    with pytest.raises(IndexError):
        c.ask(ToolCall(name="tap", args={"id": 2}))


# ---------------------------------------------------------------------------
# Part B — Policy class
# ---------------------------------------------------------------------------


def test_policy_decide_returns_default_mode_for_unknown_tool():
    p = Policy.from_config(PolicyConfig(default_mode="auto"))
    assert p.decide("tap") == PolicyDecision.AUTO


def test_policy_decide_returns_per_tool_override():
    p = Policy.from_config(PolicyConfig(default_mode="auto", per_tool={"type": "deny"}))
    assert p.decide("type") == PolicyDecision.DENY


def test_policy_apply_auto_calls_execute_and_returns_its_result():
    p = Policy.from_config(PolicyConfig())
    seen: list[ToolCall] = []

    def fake_execute(call: ToolCall) -> ToolResult:
        seen.append(call)
        return ToolResult(message="ok")

    out = p.apply(ToolCall(name="tap", args={"id": 1}), fake_execute, AlwaysRejectConfirmer())
    assert isinstance(out, ToolResult)
    assert out.message == "ok"
    assert seen == [ToolCall(name="tap", args={"id": 1})]


def test_policy_apply_confirm_approved_calls_execute():
    p = Policy.from_config(PolicyConfig(per_tool={"type": "confirm"}))
    seen: list[ToolCall] = []

    def fake_execute(call: ToolCall) -> ToolResult:
        seen.append(call)
        return ToolResult(message="typed")

    out = p.apply(
        ToolCall(name="type", args={"id": 1, "text": "hi"}),
        fake_execute,
        AlwaysApproveConfirmer(),
    )
    assert isinstance(out, ToolResult)
    assert seen and seen[0].name == "type"


def test_policy_apply_confirm_rejected_skips_execute_and_returns_tool_error():
    p = Policy.from_config(PolicyConfig(per_tool={"type": "confirm"}))
    called = False

    def fake_execute(call: ToolCall) -> ToolResult:  # noqa: ARG001
        nonlocal called
        called = True
        return ToolResult(message="should not run")

    out = p.apply(
        ToolCall(name="type", args={"id": 1, "text": "hi"}),
        fake_execute,
        AlwaysRejectConfirmer(),
    )
    assert called is False
    assert isinstance(out, ToolError)
    assert "user rejected" in out.message.lower()


def test_policy_apply_dry_run_skips_execute_and_returns_ok_tool_result():
    """Dry-run keeps the agent moving — ok=True with a clear note so the agent
    can walk a plan without ever touching the device."""
    p = Policy.from_config(PolicyConfig(per_tool={"tap": "dry-run"}))
    called = False

    def fake_execute(call: ToolCall) -> ToolResult:  # noqa: ARG001
        nonlocal called
        called = True
        return ToolResult(message="real call")

    out = p.apply(
        ToolCall(name="tap", args={"id": 1}),
        fake_execute,
        AlwaysRejectConfirmer(),
    )
    assert called is False
    assert isinstance(out, ToolResult)
    assert "dry-run" in out.message.lower()
    assert "tap" in out.message  # the message names the tool that was skipped


def test_policy_apply_deny_skips_execute_and_returns_tool_error():
    p = Policy.from_config(PolicyConfig(per_tool={"tap": "deny"}))

    def fake_execute(call: ToolCall) -> ToolResult:  # noqa: ARG001
        raise AssertionError("execute must not be called")

    out = p.apply(
        ToolCall(name="tap", args={"id": 1}),
        fake_execute,
        AlwaysRejectConfirmer(),
    )
    assert isinstance(out, ToolError)
    assert "policy" in out.message.lower() and "deny" in out.message.lower()


def test_policy_apply_propagates_done_through_auto_branch():
    """A tool that returns is_done=True must keep that signal through the
    policy layer — the agent depends on it to terminate."""
    p = Policy.from_config(PolicyConfig())
    done_result = ToolResult(message="finished", is_done=True, done_success=True, done_reason="ok")
    out = p.apply(
        ToolCall(name="done", args={"success": True, "reason": "ok"}),
        lambda call: done_result,  # noqa: ARG005
        AlwaysRejectConfirmer(),
    )
    assert isinstance(out, ToolResult)
    assert out.is_done is True
    assert out.done_success is True


# ---------------------------------------------------------------------------
# Part C — CliConfirmer
# ---------------------------------------------------------------------------


def test_cli_confirmer_accepts_y_as_approval(monkeypatch, capsys):
    """User types 'y' + Enter — the call is approved. stdin is fed via a
    StringIO, and select is patched to report 'ready immediately'."""

    monkeypatch.setattr("sys.stdin", StringIO("y\n"))
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: (r, [], []),  # always ready
    )

    out = CliConfirmer(timeout_s=5).ask(ToolCall(name="type", args={"text": "hi"}))
    assert out is True


def test_cli_confirmer_accepts_yes_case_insensitive(monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("YES\n"))
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: (r, [], []),
    )
    assert CliConfirmer(timeout_s=5).ask(ToolCall(name="tap", args={"id": 1})) is True


def test_cli_confirmer_rejects_n(monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("n\n"))
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: (r, [], []),
    )
    assert CliConfirmer(timeout_s=5).ask(ToolCall(name="tap", args={"id": 1})) is False


def test_cli_confirmer_rejects_anything_that_is_not_yes(monkeypatch):
    """Defensive default — any unexpected input is treated as rejection."""
    monkeypatch.setattr("sys.stdin", StringIO("maybe\n"))
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: (r, [], []),
    )
    assert CliConfirmer(timeout_s=5).ask(ToolCall(name="tap", args={"id": 1})) is False


def test_cli_confirmer_times_out_and_rejects(monkeypatch):
    """select returns empty lists when nothing is ready within timeout."""
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: ([], [], []),
    )
    # stdin doesn't matter — select says it's not ready.
    monkeypatch.setattr("sys.stdin", StringIO(""))
    assert CliConfirmer(timeout_s=0.01).ask(ToolCall(name="tap", args={"id": 1})) is False


def test_cli_confirmer_writes_a_visible_prompt(monkeypatch, capsys):
    """The prompt is part of the contract — the user must see what they're
    being asked to approve, including the tool name and args."""
    monkeypatch.setattr("sys.stdin", StringIO("y\n"))
    monkeypatch.setattr(
        "androidharness.policy.select.select",
        lambda r, w, x, t: (r, [], []),
    )
    CliConfirmer(timeout_s=5).ask(ToolCall(name="type", args={"id": 7, "text": "secret"}))
    captured = capsys.readouterr()
    # Tool name and args must both appear so the user knows what to approve.
    assert "type" in captured.out + captured.err
    assert "secret" in captured.out + captured.err
