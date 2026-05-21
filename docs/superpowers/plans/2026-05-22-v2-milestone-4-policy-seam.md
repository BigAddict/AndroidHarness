# v2 Milestone 4 — Policy Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate every tool call behind a `Policy` so destructive actions (`type`, `long_press`, future install/settings tools) can be set to `confirm`, `dry-run`, or `deny` — making the harness safe to point at the user's personal phone.

**Architecture:** A new `androidharness/policy.py` module owns the `Policy` object and a `Confirmer` Protocol. The `Agent` loop consults `policy.decide(call.name)` between the model's tool choice and `tools.execute(...)` — `auto` passes through; `confirm` asks the user via the injected `Confirmer` and routes the answer back as a `tool_result`; `dry-run` skips the device call and returns `ok=True` with a "would have called X" message; `deny` skips and returns `ok=False`. The CLI ships a `CliConfirmer` using `select`-based stdin reads (Linux/macOS) with a `confirm_timeout_s` cap that auto-rejects. The `tools.execute()` function itself is not touched — policy lives one layer up.

**Tech Stack:** Pydantic v2 (schema), Typer (`--policy` CLI flag), `select` from stdlib (timeout-bounded stdin read), pytest.

**Spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §4 + roadmap item #4.

**Design decisions (user-confirmed at brainstorming time):**
1. Dry-run → `ok=True` with a "dry-run: would have called X" message (lets the agent walk an entire plan without touching the phone).
2. Confirm prompt → simple `y/n` (no `a`/`A` auto-approve shortcuts — explicit per call).
3. Confirm timeout → auto-reject (safe default for unattended runs).

---

## File Structure

| Path | Purpose |
|---|---|
| `androidharness/policy.py` | **New.** Holds `PolicyDecision` enum, `Confirmer` Protocol, `AlwaysApproveConfirmer` / `AlwaysRejectConfirmer` / `RecordingConfirmer` test helpers, `CliConfirmer`, and the `Policy` class with `decide(name)` and `apply(call, execute_callable)` methods. |
| `androidharness/config.py` | Modify — extend `PolicyConfig` with `confirm_timeout_s` field; set spec-mandated defaults in `per_tool` (`type: confirm`, `long_press: confirm`). |
| `androidharness/agent.py` | Modify — add `policy: Policy` and `confirmer: Confirmer` fields to `Agent` with permissive defaults; consult `policy` between the model's tool choice and `tools.execute(...)`. |
| `androidharness/cli.py` | Modify — add `--policy` CLI flag (parses `tool=mode,tool=mode,...`); build `Policy` from `cfg.policy` + flag override; instantiate `CliConfirmer(timeout_s=...)`; pass both into the `Agent`. The runner's `run_task` gains matching kwargs. |
| `androidharness/runner.py` | Modify — pass `policy` and `confirmer` through to `Agent` constructor. |
| `tests/test_policy.py` | **New.** Unit tests for `PolicyDecision`, the test-helper confirmers, `Policy.decide(name)`, `Policy.apply(call, execute_callable)` for all four modes, and `CliConfirmer` against monkey-patched stdin. |
| `tests/test_config.py` | Modify — extend with tests for the new `PolicyConfig.confirm_timeout_s` field and the new defaulted `per_tool` entries. |
| `tests/test_agent.py` | Modify — extend with tests asserting (a) the agent calls the confirmer for `confirm`-mode tools, (b) `dry-run` short-circuits before reaching the device, (c) `deny` short-circuits and surfaces as `ok=False`. Existing tests must keep passing because the default `Policy()` is permissive (`default_mode="auto"`). |
| `tests/test_cli_run_config.py` | Modify — extend with tests for `--policy tap=confirm,type=deny` override and the `policy.confirm_timeout_s` config path. |
| `docs/configuration.md` | Modify — flesh out the `### policy` section with the new fields + the `--policy` override flag. |
| `docs/architecture.md` | Modify — add a `Policy` paragraph to the module reference; update the run-command bullet to mention the policy gate. |
| `docs/roadmap.md` | Modify — mark milestone 4 Shipped with the new SHAs. |
| `docs/getting-started.md` | Modify — add a short section on `--policy` and the confirm prompt UX. |

Existing `androidharness/tools.py`, `androidharness/perception.py`, `androidharness/device.py`, `androidharness/imaging.py`, `androidharness/logging_setup.py`, `androidharness/llm.py` are **untouched** by this milestone.

---

## Task 1: Flesh out `PolicyConfig`

**Files:**
- Modify: `androidharness/config.py`
- Test: `tests/test_config.py`

Schema additions:
- `confirm_timeout_s: int = 30` (positive int, seconds before auto-reject).
- Default `per_tool` now includes the spec-mandated `type: confirm` and `long_press: confirm`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py`:

```python
from androidharness.config import PolicyConfig


def test_policy_config_defaults_include_spec_mandated_confirm_tools():
    p = PolicyConfig()
    assert p.default_mode == "auto"
    assert p.confirm_timeout_s == 30
    # Spec §4 default policy: type + long_press require confirmation.
    assert p.per_tool["type"] == "confirm"
    assert p.per_tool["long_press"] == "confirm"


def test_policy_config_user_per_tool_overrides_defaults():
    """User-provided per_tool must override the spec defaults, not merge."""
    p = PolicyConfig(per_tool={"type": "auto"})
    assert p.per_tool["type"] == "auto"
    # Nothing else carries over — the user-provided dict is authoritative.
    assert p.per_tool == {"type": "auto"}


def test_policy_config_confirm_timeout_rejects_zero_or_negative():
    with pytest.raises(ValidationError):
        PolicyConfig(confirm_timeout_s=0)
    with pytest.raises(ValidationError):
        PolicyConfig(confirm_timeout_s=-1)


def test_policy_config_round_trips_through_yaml(tmp_path):
    yaml_text = """\
version: 1
policy:
  default_mode: confirm
  confirm_timeout_s: 5
  per_tool:
    tap: auto
    type: deny
"""
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = load_config(p)
    assert cfg.policy.default_mode == "confirm"
    assert cfg.policy.confirm_timeout_s == 5
    assert cfg.policy.per_tool == {"tap": "auto", "type": "deny"}
```

(`PolicyConfig` is already exported from `androidharness.config`; just include it in the import block at the top of the test file if it isn't already.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v -k policy`
Expected: 3 failures (the new defaults aren't set; `confirm_timeout_s` doesn't exist).

- [ ] **Step 3: Update `PolicyConfig` in `androidharness/config.py`**

Find the existing `PolicyConfig` block. Replace with:

```python
def _default_per_tool_policy() -> dict[str, PolicyMode]:
    """Spec §4 default policy: typing + long-press require confirmation on personal devices."""
    return {"type": "confirm", "long_press": "confirm"}


class PolicyConfig(BaseModel):
    """Destructive-action gating (milestone 4).

    The agent consults this before dispatching every tool call. `default_mode`
    applies to any tool not named in `per_tool`. Modes:
      * `auto` — call the tool as usual.
      * `confirm` — block on the injected Confirmer; rejection returns
        ok=False to the agent.
      * `dry-run` — skip the device call; return ok=True with a "would have
        called X" message so the agent can walk a plan without touching the
        phone.
      * `deny` — skip and return ok=False.
    """

    model_config = _STRICT

    default_mode: PolicyMode = "auto"
    confirm_timeout_s: int = Field(default=30, gt=0)
    per_tool: dict[str, PolicyMode] = Field(default_factory=_default_per_tool_policy)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v -k policy`
Expected: all 4 new tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 136 + 4 = 140 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): flesh out PolicyConfig — confirm_timeout_s + spec defaults"
```

---

## Task 2: Create `androidharness/policy.py` core

The module owns:
- `PolicyDecision` — `Enum` with `AUTO`, `CONFIRM`, `DRY_RUN`, `DENY` (string-valued, matching the config `PolicyMode` Literal).
- `Confirmer` — Protocol with `ask(call: ToolCall) -> bool`.
- `AlwaysApproveConfirmer`, `AlwaysRejectConfirmer`, `RecordingConfirmer` — test helpers.
- `Policy` — class with:
  - `from_config(cfg: PolicyConfig) -> Policy` factory.
  - `decide(tool_name: str) -> PolicyDecision`.
  - `apply(call: ToolCall, execute_fn) -> ToolResult | ToolError` — the gate. Calls `execute_fn(call)` only when allowed.
- `CliConfirmer` — `Confirmer` that prompts on stdin via `typer.echo`, reads with `select.select(..., timeout_s)`, auto-rejects on timeout. Comes later in this task (last step).

**Files:**
- Create: `androidharness/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write failing tests (Part A — enum + confirmers)**

Create `tests/test_policy.py`:

```python
from __future__ import annotations

import pytest

from androidharness.policy import (
    AlwaysApproveConfirmer,
    AlwaysRejectConfirmer,
    PolicyDecision,
    RecordingConfirmer,
)
from androidharness.tools import ToolCall


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
```

- [ ] **Step 2: Run tests, expect import failure**

Run: `uv run pytest tests/test_policy.py -v`
Expected: collection error / `ModuleNotFoundError: No module named 'androidharness.policy'`.

- [ ] **Step 3: Create `androidharness/policy.py` with enum + confirmers**

```python
from __future__ import annotations

import logging
import select
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from androidharness.tools import ToolCall, ToolError, ToolResult

_log = logging.getLogger("androidharness.policy")


class PolicyDecision(str, Enum):
    """Resolved policy for one tool call. String values match the YAML mode
    strings so `PolicyDecision(cfg_mode)` round-trips."""

    AUTO = "auto"
    CONFIRM = "confirm"
    DRY_RUN = "dry-run"
    DENY = "deny"


class Confirmer(Protocol):
    """Inject this into the agent to handle `confirm`-mode tool calls.
    Implementations:
      * `CliConfirmer` — interactive y/n on stdin with a timeout.
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
    _idx: int = 0

    def ask(self, call: ToolCall) -> bool:
        self.calls.append(call)
        answer = self.answers[self._idx]  # raises IndexError when exhausted
        self._idx += 1
        return answer
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_policy.py -v`
Expected: all 4 enum/confirmer tests pass.

- [ ] **Step 5: Write failing tests (Part B — `Policy` class)**

Append to `tests/test_policy.py`:

```python
from androidharness.config import PolicyConfig
from androidharness.policy import Policy


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
```

- [ ] **Step 6: Run tests, expect failure on `Policy` import**

Run: `uv run pytest tests/test_policy.py -v -k policy_decide or policy_apply`
Expected: 8 failures — `ImportError: cannot import name 'Policy'`.

- [ ] **Step 7: Implement `Policy` in `androidharness/policy.py`**

Append (below the confirmers):

```python
ExecuteFn = Callable[[ToolCall], ToolResult | ToolError]


@dataclass
class Policy:
    """Gates every tool call. Owns the per-tool decision lookup and the
    `auto / confirm / dry-run / deny` dispatch."""

    default: PolicyDecision = PolicyDecision.AUTO
    per_tool: dict[str, PolicyDecision] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg) -> "Policy":
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
                return execute_fn(call)
            return ToolError(f"user rejected: {call.name}({call.args})")

        if decision == PolicyDecision.DRY_RUN:
            return ToolResult(message=f"dry-run: would have called {call.name}({call.args})")

        # DENY
        return ToolError(f"policy=deny: refused {call.name}({call.args})")
```

`Callable` and `Protocol` are already imported from `typing`. `field` is already from `dataclasses`. No new module-level imports needed beyond what Step 3 already added.

- [ ] **Step 8: Run all `Policy` tests**

Run: `uv run pytest tests/test_policy.py -v`
Expected: all 12 tests pass (4 from Part A + 8 from Part B).

- [ ] **Step 9: Write failing tests (Part C — `CliConfirmer`)**

Append to `tests/test_policy.py`:

```python
from io import StringIO

from androidharness.policy import CliConfirmer


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
    assert "secret" in captured.out + captured.err or "7" in captured.out + captured.err
```

- [ ] **Step 10: Run tests, expect `CliConfirmer` failures**

Run: `uv run pytest tests/test_policy.py -v -k cli_confirmer`
Expected: 6 failures — `ImportError: cannot import name 'CliConfirmer'`.

- [ ] **Step 11: Implement `CliConfirmer` in `androidharness/policy.py`**

Append (at the bottom of the module):

```python
class CliConfirmer:
    """Interactive `y/n` confirmer for the CLI. Reads stdin with a timeout
    so unattended runs auto-reject rather than block forever.

    Uses `select.select` for the timeout, which is Linux/macOS-only — the
    rest of the project already assumes a POSIX environment via ADB.
    """

    def __init__(self, timeout_s: float = 30.0) -> None:
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
            return False

        answer = sys.stdin.readline().strip().lower()
        return answer in {"y", "yes"}
```

- [ ] **Step 12: Run all policy tests**

Run: `uv run pytest tests/test_policy.py -v`
Expected: all 18 tests pass.

- [ ] **Step 13: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 140 + 14 = 154 passing (4 from Part A + 8 from Part B + 6 from Part C; remember Task 1 added 4, so 140 + 14).

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 14: Commit**

```bash
git add androidharness/policy.py tests/test_policy.py
git commit -m "feat(policy): Policy + Confirmer + CliConfirmer (auto/confirm/dry-run/deny gate)"
```

---

## Task 3: Wire `Policy` into the `Agent` loop

The injection point: between `call = ToolCall(...)` and `result = execute(self.device, call, obs)` in `agent.py`. Replace the direct `execute(...)` call with `policy.apply(call, execute_fn, confirmer)` where `execute_fn` partially applies `device` and `obs`.

**Files:**
- Modify: `androidharness/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agent.py`:

```python
from androidharness.config import PolicyConfig
from androidharness.policy import (
    AlwaysApproveConfirmer,
    AlwaysRejectConfirmer,
    Policy,
    RecordingConfirmer,
)


def test_agent_default_policy_passes_calls_through_unchanged(fake_device, fake_gemini):
    """Existing behavior preservation: with the default permissive Policy,
    the agent dispatches every tool call to the device, just like before."""
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert result.status == "done"
    # The tap actually reached the device.
    assert any(c[0] == "tap" for c in fake_device.calls)


def test_agent_confirm_mode_asks_confirmer_and_routes_rejection_back(
    fake_device, fake_gemini
):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "type", "args": {"id": 1, "text": "secret"}},
            {"name": "done", "args": {"success": False, "reason": "rejected"}},
        ]
    )
    confirmer = RecordingConfirmer(answers=[False])
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"type": "confirm"})),
        confirmer=confirmer,
    )
    result = agent.run("type some text")

    assert result.status == "done"
    # The confirmer was called once with the type call.
    assert len(confirmer.calls) == 1
    assert confirmer.calls[0].name == "type"
    # The device was NEVER asked to type — the policy blocked it.
    assert not any(c[0] == "type_text" for c in fake_device.calls)
    # The rejection reached the model as a tool_result with ok=False.
    second_call_contents = client.generate_calls[1]["contents"]
    rendered = " ".join(str(c) for c in second_call_contents)
    assert "user rejected" in rendered.lower()


def test_agent_dry_run_mode_short_circuits_and_marks_ok_true(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "dry-ran"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"tap": "dry-run"})),
        confirmer=AlwaysRejectConfirmer(),
    )
    result = agent.run("tap something")

    assert result.status == "done"
    # The device was NEVER tapped.
    assert not any(c[0] == "tap" for c in fake_device.calls)
    # The tool_result the model saw was ok=True.
    tr = result.turn_log[0]["tool_result"]
    assert tr["ok"] is True
    assert "dry-run" in tr["message"].lower()


def test_agent_deny_mode_short_circuits_and_marks_ok_false(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": False, "reason": "denied"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"tap": "deny"})),
        confirmer=AlwaysApproveConfirmer(),
    )
    agent.run("tap something")

    assert not any(c[0] == "tap" for c in fake_device.calls)


def test_agent_confirm_approved_lets_call_through_to_device(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "type", "args": {"id": 1, "text": "hi"}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"type": "confirm"})),
        confirmer=AlwaysApproveConfirmer(),
    )
    agent.run("type some text")
    assert any(c[0] == "type_text" for c in fake_device.calls)
```

(`HIERARCHY` is the constant defined at the top of `tests/test_agent.py` and includes a Settings button at id 1.)

- [ ] **Step 2: Run tests, expect failures**

Run: `uv run pytest tests/test_agent.py -v -k policy`
Expected: 5 failures — `TypeError: Agent.__init__() got an unexpected keyword argument 'policy'`.

- [ ] **Step 3: Add `policy` and `confirmer` fields to `Agent`**

In `androidharness/agent.py`, find the `@dataclass class Agent:` block. Add imports near the top of the file:

```python
from androidharness.policy import AlwaysRejectConfirmer, Confirmer, Policy
```

Extend the `Agent` dataclass:

```python
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
    confirmer: Confirmer = field(default_factory=AlwaysRejectConfirmer)
```

The default `Policy()` is permissive (`default_mode=AUTO`, empty `per_tool`) — every tool call passes through, so existing tests keep working. The default `Confirmer` is `AlwaysRejectConfirmer` so any caller who enables `confirm` mode but forgets to inject a real confirmer fails safely (rejection beats accidental approval).

- [ ] **Step 4: Replace the direct `execute(...)` call with `policy.apply(...)`**

Find the block in `agent.py` that currently reads:

```python
            try:
                result = execute(self.device, call, obs)
            except Exception as e:
                _log.exception("turn %d: tool dispatch raised", turn_idx)
                result = ToolError(f"tool {call.name} raised {_format_exception(e)}")
```

Replace with:

```python
            def _run_tool(c: ToolCall) -> ToolResult | ToolError:
                # Keep the original exception-to-ToolError shielding around
                # the device call; policy.apply will receive the result either
                # way and forward it to the model.
                try:
                    return execute(self.device, c, obs)
                except Exception as e:
                    _log.exception("turn %d: tool dispatch raised", turn_idx)
                    return ToolError(f"tool {c.name} raised {_format_exception(e)}")

            result = self.policy.apply(call, _run_tool, self.confirmer)
```

- [ ] **Step 5: Run the new agent tests**

Run: `uv run pytest tests/test_agent.py -v -k policy`
Expected: all 5 new tests pass.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: 154 + 5 = 159 passing. Existing `tests/test_agent.py` tests must all still pass without modification because of the permissive default Policy.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add androidharness/agent.py tests/test_agent.py
git commit -m "feat(agent): consult Policy before every tool call (auto/confirm/dry-run/deny)"
```

---

## Task 4: Wire `--policy` CLI flag + CliConfirmer

The CLI flag accepts a comma-separated `tool=mode` list and merges over the config's `per_tool` for one run. The default `CliConfirmer` (with timeout from `cfg.policy.confirm_timeout_s`) is injected into the `Agent`.

**Files:**
- Modify: `androidharness/cli.py`
- Modify: `androidharness/runner.py`
- Test: `tests/test_cli_run_config.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli_run_config.py`:

```python
def test_cli_policy_flag_overrides_config_per_tool(isolated_home, stub_run, tmp_path):
    """--policy is parsed as tool=mode pairs and merged over cfg.policy.per_tool
    for the single run. The merged policy reaches the agent via run_task."""
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("policy:\n  default_mode: auto\n  per_tool: {type: confirm}\n")
    result = runner.invoke(
        app,
        ["run", "test task", "--policy", "tap=deny,type=auto"],
    )
    assert result.exit_code == 0, result.stdout
    # The merged policy passed to run_task should have the CLI overrides applied.
    policy = stub_run["policy"]
    assert policy.decide("tap").value == "deny"
    assert policy.decide("type").value == "auto"


def test_cli_policy_flag_rejects_unknown_mode(isolated_home, stub_run):
    result = runner.invoke(app, ["run", "test", "--policy", "tap=banana"])
    assert result.exit_code != 0
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "policy" in combined.lower()
    assert "banana" in combined


def test_cli_policy_flag_rejects_malformed_pair(isolated_home, stub_run):
    """Must be `tool=mode` — missing `=` is a hard error."""
    result = runner.invoke(app, ["run", "test", "--policy", "tap"])
    assert result.exit_code != 0


def test_cli_run_passes_confirm_timeout_from_config(isolated_home, stub_run, tmp_path):
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("policy:\n  confirm_timeout_s: 7\n")
    result = runner.invoke(app, ["run", "test"])
    assert result.exit_code == 0, result.stdout
    # The CliConfirmer instance reached run_task with the configured timeout.
    confirmer = stub_run["confirmer"]
    assert getattr(confirmer, "_timeout_s", None) == 7
```

The `stub_run` fixture in `test_cli_run_config.py` already captures the kwargs passed to `run_task`. After Task 4 lands, those kwargs include `policy` and `confirmer`.

- [ ] **Step 2: Run tests, expect failures**

Run: `uv run pytest tests/test_cli_run_config.py -v -k "policy or confirm_timeout"`
Expected: 4 failures — `--policy` flag not defined; `run_task` doesn't accept `policy`/`confirmer` kwargs.

- [ ] **Step 3: Add a `--policy` parser helper to `androidharness/cli.py`**

At the top of `androidharness/cli.py` (just below the existing module-level helpers like `_resolve_config_path`):

```python
_VALID_POLICY_MODES = {"auto", "confirm", "dry-run", "deny"}


def _parse_policy_overrides(raw: str | None) -> dict[str, str]:
    """Parse a `--policy tap=confirm,type=deny` string into a per_tool dict.
    Returns {} when `raw` is None or empty. Raises typer.BadParameter on
    malformed input."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            raise typer.BadParameter(
                f"--policy entry {pair!r} is not in `tool=mode` form"
            )
        tool, mode = (p.strip() for p in pair.split("=", 1))
        if mode not in _VALID_POLICY_MODES:
            raise typer.BadParameter(
                f"--policy mode {mode!r} for tool {tool!r} must be one of "
                f"{sorted(_VALID_POLICY_MODES)}"
            )
        out[tool] = mode
    return out
```

- [ ] **Step 4: Add the `--policy` Typer Option and build the `Policy` + `CliConfirmer`**

In the `run_cmd` definition, add a new option to the signature (next to the other `Option` flags):

```python
    policy_override: str | None = typer.Option(
        None, "--policy",
        help="Per-tool policy override, e.g. `tap=confirm,type=deny`.",
    ),
```

After the existing `cfg = load_config(...)` block in `run_cmd`, add the policy build step (place it after `d = cfg.defaults` and before the client-selection block):

```python
    # Build the per-run Policy from config + CLI override.
    from androidharness.policy import CliConfirmer, Policy
    overrides = _parse_policy_overrides(policy_override)
    merged_per_tool = {**cfg.policy.per_tool, **overrides}
    policy = Policy.from_config(
        cfg.policy.model_copy(update={"per_tool": merged_per_tool})
    )
    confirmer = CliConfirmer(timeout_s=cfg.policy.confirm_timeout_s)
```

In the `run_task(...)` invocation at the bottom of `run_cmd`, add `policy=policy, confirmer=confirmer,` to the kwargs.

- [ ] **Step 5: Modify `androidharness/runner.py` to accept and forward `policy` + `confirmer`**

Find the `run_task(...)` signature. Add the two kwargs (after `resource_id_in_render`):

```python
def run_task(
    *,
    task: str,
    device: Any,
    client: LLMClient,
    model: str,
    runs_root: Path,
    max_turns: int = 40,
    wall_clock_s: float = 600.0,
    quantize_screenshots: bool = False,
    viewport_filter: bool = False,
    resource_id_in_render: bool = False,
    policy: "Policy | None" = None,
    confirmer: "Confirmer | None" = None,
) -> RunOutcome:
```

Add an import at the top of `runner.py`:

```python
from androidharness.policy import AlwaysRejectConfirmer, Confirmer, Policy
```

(Use real type names, not forward references; remove the quotes in the signature.)

In the body of `run_task`, where `Agent(...)` is constructed, pass `policy=policy or Policy(), confirmer=confirmer or AlwaysRejectConfirmer(),`:

```python
    agent = Agent(
        device=device,
        client=client,
        model=model,
        max_turns=max_turns,
        wall_clock_s=wall_clock_s,
        quantize_screenshots=quantize_screenshots,
        viewport_filter=viewport_filter,
        resource_id_in_render=resource_id_in_render,
        policy=policy or Policy(),
        confirmer=confirmer or AlwaysRejectConfirmer(),
    )
```

- [ ] **Step 6: Run the new CLI tests**

Run: `uv run pytest tests/test_cli_run_config.py -v -k "policy or confirm_timeout"`
Expected: all 4 new tests pass.

- [ ] **Step 7: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 159 + 4 = 163 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add androidharness/cli.py androidharness/runner.py tests/test_cli_run_config.py
git commit -m "feat(cli): --policy override + CliConfirmer wired through run_task"
```

---

## Task 5: Update docs

Touch only top-level `docs/*.md`; do not edit `docs/superpowers/`.

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/architecture.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/getting-started.md`

- [ ] **Step 1: Update `docs/configuration.md` — flesh out the `### policy` section**

Find the existing `### policy` block (it's the 2-row placeholder with `default_mode` and `per_tool`). Replace with:

````markdown
### `policy`

Gates every tool call. Lets you point the agent at your personal phone without worrying that one bad model decision wipes a chat thread or buys a subscription. The agent consults the policy between the LLM's tool choice and the device call.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_mode` | `"auto"` \| `"confirm"` \| `"dry-run"` \| `"deny"` | `"auto"` | Mode applied to any tool not named in `per_tool`. |
| `confirm_timeout_s` | int > 0 | `30` | Seconds the CLI confirm prompt waits before auto-rejecting. |
| `per_tool` | dict[str, mode] | `{type: confirm, long_press: confirm}` | Per-tool overrides. The defaults come from spec §4 — typing and long-press require explicit confirmation on personal devices. |

Modes:
- `auto` — call the tool as usual.
- `confirm` — prompt on the CLI (`[y/N]`); rejection returns `ok=False` to the agent, which can react.
- `dry-run` — skip the device call; return `ok=True` with a `"dry-run: would have called X"` message so the agent can walk a plan end-to-end without touching the phone.
- `deny` — skip the call; return `ok=False`.

Example:

```yaml
policy:
  default_mode: auto
  confirm_timeout_s: 15
  per_tool:
    type: deny           # never type anywhere unattended
    long_press: confirm  # ask before destructive long-presses
    tap: auto            # taps are fine
```

CLI override for a single run:

```bash
uv run androidharness run "..." --policy "tap=confirm,type=deny"
```

`--policy` is parsed as a comma-separated `tool=mode` list and merges over `policy.per_tool` for that single run. Modes outside `{auto, confirm, dry-run, deny}` are rejected.
````

- [ ] **Step 2: Update `docs/architecture.md`**

Find the `Module reference` section. After the `androidharness/runner.py` entry, insert a new entry:

```markdown
### `androidharness/policy.py`

The policy gate the agent consults before every tool call.

- `PolicyDecision` — `Enum(AUTO|CONFIRM|DRY_RUN|DENY)`. String values match the YAML mode strings so `PolicyDecision(cfg_mode)` round-trips.
- `Policy` — owns the per-tool decision lookup. `decide(name)` returns the resolved `PolicyDecision`; `apply(call, execute_fn, confirmer)` dispatches: `auto` passes through to `execute_fn`; `confirm` asks the injected `Confirmer` and returns the answer-shaped result; `dry-run` returns `ToolResult(message="dry-run: ...")` without touching the device; `deny` returns `ToolError(message="policy=deny: ...")`.
- `Confirmer` Protocol — single method `ask(call: ToolCall) -> bool`. `CliConfirmer` (default in the CLI) prompts on stderr and reads stdin with a `select`-based timeout. `AlwaysApproveConfirmer` / `AlwaysRejectConfirmer` / `RecordingConfirmer` are test helpers.

The agent loop (`agent.py`) wraps the `tools.execute(...)` call in a closure and hands it to `policy.apply(...)`; the policy's return value is what reaches the agent's turn log.
```

Also update the `### androidharness/cli.py` bullet for the `run` command — add a clause about the policy flag:

```markdown
- `androidharness run <task>` — resolves config, selects device, builds the per-run `Policy` (config + `--policy` override) and `CliConfirmer`, builds `Agent` + the configured `LLMClient` (`LiteLLMClient` by default; `LiteLLMRouterClient` when `throttler.enabled`; `GoogleGenaiClient` when `providers.use_litellm=false`), calls `run_task`
```

- [ ] **Step 3: Update `docs/roadmap.md`**

Find the row for milestone 4 (currently `| 4 | Policy seam — destructive-action gating | Pending | |`). After Task 4 lands, the commits will be visible via `git log --oneline 3950675..HEAD | head -N`. Replace with:

```markdown
| 4 | Policy seam — destructive-action gating | **Shipped** | <NEW_COMMIT_SHAS> |
```

Collect the actual SHAs with `git log --oneline e6ce1a9..HEAD` (from after milestone 3) and paste in chronological order: PolicyConfig, policy.py, agent wiring, CLI wiring. The doc commit's own SHA does not need to be in this row.

Also update the "Current focus" paragraph:

```markdown
Milestones 1 (config schema), 2 (LiteLLM provider seam), 3 (throttler + Router fallback), and 4 (policy seam) are complete. Milestone 5 (Settings UI) is the last item in the "v2 minimum" block.
```

- [ ] **Step 4: Update `docs/getting-started.md`**

After the existing "Logical model names and the throttler" section and before "Troubleshooting", insert:

````markdown
## Policy — gating destructive actions

Pointing the agent at your personal phone? The `policy` gate is the safety net. Out of the box, `type` and `long_press` require a `[y/N]` confirmation at the terminal before the call reaches the device; everything else (`tap`, `swipe`, `scroll`, etc.) is `auto`.

```bash
# One-off override: dry-run every tap, deny typing entirely.
uv run androidharness run "..." --policy "tap=dry-run,type=deny"
```

See [configuration.md](configuration.md#policy) for the full mode reference. The confirm prompt auto-rejects after `policy.confirm_timeout_s` (default 30s) so unattended runs can't accidentally approve destructive actions.
````

- [ ] **Step 5: Verify**

Run: `grep -rn "milestone 4\|policy" docs/*.md | grep -iv "shipped\|spec\|plan" | head -30`
Look for any remaining `Pending` / `Placeholder` references to milestone 4 outside `docs/superpowers/`.

- [ ] **Step 6: Commit**

```bash
git add docs/configuration.md docs/architecture.md docs/roadmap.md docs/getting-started.md
git commit -m "docs: policy seam for v2 milestone 4"
```

---

## Task 6: Manual smoke test (human-run)

Same shape as previous milestones — needs a real ADB device + GEMINI_API_KEY. No commit.

- [ ] **Step 1: Confirm dry-run mode end-to-end**

```bash
uv run androidharness run "open settings and toggle wifi off" --policy "tap=dry-run,swipe=dry-run,scroll=dry-run,type=dry-run" --max-turns 6
```

Expected: the agent runs to completion but nothing on the phone changes. Every `turns.jsonl` entry's `tool_result.message` starts with `dry-run:`.

- [ ] **Step 2: Confirm `confirm` mode prompts and rejects on timeout**

```bash
uv run androidharness run "type 'hello' in any text field" --policy "type=confirm" --max-turns 3
# Walk away from the keyboard when the prompt appears; let it time out.
```

Expected: after `confirm_timeout_s` (default 30s) the prompt prints `[policy] timeout — rejecting`; the agent's next turn sees a `user rejected` tool_result and routes around.

- [ ] **Step 3: Confirm `deny` mode terminates cleanly**

```bash
uv run androidharness run "open settings" --policy "tap=deny,swipe=deny,scroll=deny,press_key=deny" --max-turns 4
```

Expected: every device-affecting tool call comes back as `ok=False, message="policy=deny: ..."`. The agent eventually calls `done(success=False)` or hits `max_turns`. Nothing changes on the phone.

---

## Self-review

**Spec coverage (§4 + roadmap item #4):**

| Spec line | Where it lands |
|---|---|
| "A `Policy` object the agent consults before dispatching tools" | Task 2 (`Policy` class) + Task 3 (agent wiring) |
| "Per-tool mode: `auto` \| `confirm` \| `dry-run` \| `deny`" | Task 2 (`PolicyDecision` + `apply` dispatch) |
| Default policy on personal devices: `auto` for navigation, `confirm` for `type` + `long_press` | Task 1 (`_default_per_tool_policy()`); default `default_mode="auto"` already in placeholder |
| `confirm` mode emits a prompt and blocks until approve/reject; rejection returns `ok=False` "user rejected: ..." | Task 2 (`CliConfirmer`) + Task 2 Step 7 (`Policy.apply` rejection branch returning `ToolError("user rejected: ...")`) |
| Config: YAML file plus `--policy` CLI flag for ad-hoc override | Task 1 (YAML schema) + Task 4 (`--policy` parser) |
| Web UI shows current policy + per-session toggle | **Deferred to milestone 5** (Settings UI). The policy *config* is fully consumable from the Settings UI when it lands; this milestone leaves that for milestone 5. |

**Placeholder scan:** No `TODO`, `TBD`, "add appropriate", "similar to Task N", or "fill in" tokens. Every test step has the literal body; every code step has the literal code. Task 5 Step 3 has a `<NEW_COMMIT_SHAS>` token that is an intentional runtime fill-in — the implementer collects actual SHAs via `git log` at commit time, exactly as milestone 3 did.

**Type consistency:**
- `PolicyDecision` enum string values (`"auto"`, `"confirm"`, `"dry-run"`, `"deny"`) match `PolicyMode` Literal in `config.py`.
- `Confirmer.ask(call: ToolCall) -> bool` — consistent across `CliConfirmer`, all test helpers, and the agent invocation.
- `Policy.apply(call, execute_fn, confirmer) -> ToolResult | ToolError` — consistent with `tools.execute` return type and what the `Agent.run` loop already expects to forward to `contents`.
- `Policy.from_config(cfg: PolicyConfig) -> Policy` — used in Task 2 tests, Task 3 tests, and Task 4 CLI wiring.
- `_parse_policy_overrides(raw: str | None) -> dict[str, str]` — return type matches what `PolicyConfig.model_copy(update={"per_tool": ...})` accepts.
- `run_task(..., policy=None, confirmer=None)` kwargs — `None` defaults are resolved inside `run_task` to `Policy()` / `AlwaysRejectConfirmer()`, matching the `Agent` field defaults.

**Deferred items (explicit, not bugs):**
- Web UI confirm prompt + policy panel → milestone 5 / milestone 8 (live monitoring).
- Per-screen / per-app policy contexts → not in spec.
- Audit-log of confirm decisions → out of scope; the agent's `turns.jsonl` already records each `tool_result.message` which surfaces `"user rejected"` / `"dry-run: ..."` / `"policy=deny: ..."` strings.
