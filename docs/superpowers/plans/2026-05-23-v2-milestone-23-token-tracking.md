# v2 Milestone 23 — Token tracking + spend visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture per-turn LLM usage (prompt/completion/total tokens + resolved model name) into `turns.jsonl`, aggregate per-run totals into `result.json`, estimate dollar cost from a static price map, and expose a `androidharness usage` CLI that walks `runs/` and reports spend. Always-on, no config flag. Degrades cleanly when a client implementation cannot supply usage.

**Architecture:** A new `Usage` frozen dataclass in `androidharness/llm.py`. The two LiteLLM clients (`LiteLLMClient`, `LiteLLMRouterClient`) read `response.usage` + `response.model` from the LiteLLM completion result and attach the dataclass to their return dict under an optional `"usage"` key. `Agent.run` reads `raw.get("usage")` and stamps it onto each `turn_log` entry as a plain dict. `runner.run_task` walks the turn_log after `agent.run` returns (and on the crashed path) to compute per-model totals + a cost estimate via a new `androidharness/pricing.py` module, then writes both into `result.json`. A new `androidharness usage` subcommand walks `runs/*/result.json` and prints a per-run + totals table.

**Spec:** `docs/superpowers/specs/2026-05-23-v2-milestone-23-token-tracking-design.md`.

**Design decisions (locked in the spec):**
1. Usage shape: `Usage(model, prompt_tokens, completion_tokens, total_tokens)`. The `model` is the *resolved* deployment (post-fallback), not the logical-chain name from the request.
2. Return-shape extension is additive: the existing dict gains an optional `"usage"` key. No breaking changes to `LLMClient.generate`'s Protocol.
3. Aggregation is per-model (a single run can bill against multiple deployments via the M22 fallback chain).
4. Pricing is a static dict in `androidharness/pricing.py` for v1. The dollar figure is `cost_usd_estimate` — explicitly an estimate. Moving prices to config is a future-M follow-up.
5. Crashed runs still write `usage_total` for the turns that completed. Robust to mid-write crashes because the turns.jsonl is line-atomic.
6. No config flag — token tracking is always-on. Test fakes that don't supply usage degrade cleanly (key absent throughout the chain).
7. The `androidharness usage` CLI reads from `cfg.defaults.runs_dir` (the same directory the runner writes to).

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `androidharness/llm.py` | Modify | Add `Usage` dataclass; LiteLLMClient + LiteLLMRouterClient attach `usage` to return dict; best-effort attach in GoogleGenaiClient. |
| `androidharness/agent.py` | Modify | Pass `raw.get("usage")` through to each `turn_log` entry. |
| `androidharness/runner.py` | Modify | Aggregate per-model usage from turn_log into `result.json` (happy + crashed paths); add `cost_usd_estimate`. |
| `androidharness/pricing.py` | New | `MODEL_PRICES` static dict + `estimate_cost_usd(usage_total)` helper. |
| `androidharness/cli.py` | Modify | New `usage` subcommand: walk `runs/*/result.json`, print per-run + totals table. |
| `tests/test_llm.py` | Modify | 3 new tests (LiteLLMClient usage capture, omission when absent, Router resolves deployment name). |
| `tests/test_agent.py` | Modify | 2 new tests (stamps usage on turn_log when present; omits when absent). |
| `tests/test_runner.py` | Modify | 3 new tests (aggregation, cost estimate, crashed-path aggregation). |
| `tests/test_pricing.py` | New | 3 unit tests on `estimate_cost_usd`. |
| `tests/test_cli_usage.py` | New | 4 CLI tests (table output, missing-usage tolerance, `--since`, `--json`). |
| `docs/architecture.md` | Modify | One paragraph: per-turn usage + per-run aggregation. |
| `docs/configuration.md` | Modify | One line under a new "Pricing" subsection: `MODEL_PRICES` is in code, not YAML. |
| `docs/roadmap.md` | Modify | New row for M23, marked Shipped with commit range. |

Untouched: `config.py`, `perception.py`, `render.py`, `device.py`, `tools.py`, `policy.py`, `imaging.py`, `logging_setup.py`, the `web/` subpackage.

---

## Task 1: `Usage` dataclass + LiteLLM clients capture token usage

**Why first:** Foundation — nothing downstream can read usage until the clients produce it. Self-contained in `llm.py` and `test_llm.py`.

**Files:**
- Modify: `androidharness/llm.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Inspect the existing LiteLLM test patterns.**

```
grep -n "monkeypatch\|response\|completion\|usage" tests/test_llm.py | head -30
```

The existing tests typically monkeypatch `litellm.completion` (or `_litellm.completion` on the client instance) to return a fake response object. The fake exposes `.choices[0].message.tool_calls` + `.function.name` + `.function.arguments`. For M23, the fake also needs `.usage` and `.model` attributes. Build the fake to match: a SimpleNamespace or a small dataclass with the right shape.

- [ ] **Step 2: Write three failing tests in `tests/test_llm.py`.**

```python
def test_litellm_client_returns_usage_from_response(monkeypatch):
    """The `usage` key on LiteLLMClient.generate's return reflects the
    underlying response.usage values."""
    from types import SimpleNamespace
    from androidharness.llm import LiteLLMClient, Usage

    fake_response = SimpleNamespace(
        model="gemini/gemini-2.5-flash",
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="tap", arguments='{"id": 1}'))
        ]))],
        usage=SimpleNamespace(prompt_tokens=1234, completion_tokens=89, total_tokens=1323),
    )

    client = LiteLLMClient()
    monkeypatch.setattr(client._litellm, "completion", lambda **kw: fake_response)

    raw = client.generate(model="gemini/gemini-2.5-flash", system_instruction="", contents=[], tools=[])
    assert raw["name"] == "tap"
    usage = raw.get("usage")
    assert isinstance(usage, Usage)
    assert usage.model == "gemini/gemini-2.5-flash"
    assert usage.prompt_tokens == 1234
    assert usage.completion_tokens == 89
    assert usage.total_tokens == 1323


def test_litellm_client_omits_usage_when_response_has_none(monkeypatch):
    """When response.usage is absent, the return dict lacks the `usage`
    key entirely (no None placeholder)."""
    from types import SimpleNamespace
    from androidharness.llm import LiteLLMClient

    fake_response = SimpleNamespace(
        model="gemini/gemini-2.5-flash",
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="tap", arguments='{}'))
        ]))],
        usage=None,
    )

    client = LiteLLMClient()
    monkeypatch.setattr(client._litellm, "completion", lambda **kw: fake_response)

    raw = client.generate(model="gemini/gemini-2.5-flash", system_instruction="", contents=[], tools=[])
    assert "usage" not in raw


def test_litellm_router_returns_usage_with_resolved_model(monkeypatch):
    """When the Router resolves a logical name to a concrete deployment, the
    captured Usage.model is the resolved deployment, not the logical name."""
    from types import SimpleNamespace
    from androidharness.llm import LiteLLMRouterClient, Usage

    # The user called with model="default" (a logical name); LiteLLM resolved
    # it to gemini-2.5-pro (a fallback) and that's what we should record.
    fake_response = SimpleNamespace(
        model="gemini/gemini-2.5-pro",
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="done", arguments='{"success": true, "reason": "ok"}'))
        ]))],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=50, total_tokens=550),
    )

    # Build a Router client without going through __init__'s Router construction.
    client = LiteLLMRouterClient.__new__(LiteLLMRouterClient)
    client._router = SimpleNamespace(completion=lambda **kw: fake_response)

    raw = client.generate(model="default", system_instruction="", contents=[], tools=[])
    usage = raw.get("usage")
    assert isinstance(usage, Usage)
    assert usage.model == "gemini/gemini-2.5-pro", "must record resolved deployment, not logical name"
```

Run: `uv run pytest -q tests/test_llm.py -k usage`. Expect all three to FAIL with `ImportError: cannot import name 'Usage' ...`.

- [ ] **Step 3: Define `Usage` and attach it in both LiteLLM clients.**

In `androidharness/llm.py`, after the imports:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    """Token accounting for a single LLM call.

    `model` is the resolved deployment that actually served the request
    (post-fallback), not necessarily the logical name the caller passed.
    """
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

Then add a small helper near the top:

```python
def _extract_usage(response) -> Usage | None:
    """Pull token counts off a LiteLLM completion response.

    Defensive — providers and LiteLLM versions disagree on shape; missing
    fields default to 0 and missing whole-`usage` returns None (which the
    caller turns into a `usage`-key omission).
    """
    raw_usage = getattr(response, "usage", None)
    if raw_usage is None:
        return None
    return Usage(
        model=getattr(response, "model", "") or "",
        prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(raw_usage, "total_tokens", 0) or 0),
    )
```

Inside `LiteLLMClient.generate`, find the existing `return {"name": name, "args": args}` line. Replace with:

```python
result: dict = {"name": name, "args": args}
usage = _extract_usage(response)
if usage is not None:
    result["usage"] = usage
return result
```

Do the same surgery on the corresponding `return` line(s) inside `LiteLLMRouterClient.generate`. (The Router has the same shape — it returns from `self._router.completion(...)` — so the same helper applies.)

For the early-exit / safety-blocked branches that return a synthetic `done()` call, leave them alone — those code paths have no real usage to record.

- [ ] **Step 4: Run the new tests — they should pass.**

```
uv run pytest -q tests/test_llm.py -k usage
```

- [ ] **Step 5: Run the full LLM suite to catch regressions.**

```
uv run pytest -q tests/test_llm.py
```

- [ ] **Step 6: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): capture token usage on every LiteLLM completion"
```

---

## Task 2: `Agent.run` stamps usage onto every `turn_log` entry

**Why next:** Now that the client emits usage, we need to record it per turn so runs.jsonl is the source of truth for per-turn accounting.

**Files:**
- Modify: `androidharness/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Inspect where turn_log is appended.**

`grep -n "turn_log.append\|usage" androidharness/agent.py | head -10` — locate the existing `turn_log.append({...})` call in `Agent.run` (around line 240-250).

- [ ] **Step 2: Write two failing agent tests.**

```python
def test_agent_stamps_usage_onto_turn_log():
    """When the client returns usage, the corresponding turn_log entry
    carries the same data (as a plain dict, JSON-serializable)."""
    from dataclasses import asdict
    from androidharness.agent import Agent
    from androidharness.llm import Usage
    from androidharness.policy import AlwaysApproveConfirmer, Policy

    xml = (
        "<?xml version='1.0'?>"
        "<hierarchy>"
        "  <node bounds='[0,0][1000,1000]'>"
        "    <node class='android.widget.Button' bounds='[0,0][10,10]' clickable='true'/>"
        "  </node>"
        "</hierarchy>"
    )

    class _FakeDevice:
        serial = "fake"
        model = "fake"
        def dump_hierarchy(self) -> str:
            return xml
        def screenshot(self) -> bytes:
            return b""

    class _ClientWithUsage:
        def generate(self, *, model, system_instruction, contents, tools):
            return {
                "name": "done",
                "args": {"success": True, "reason": "ok"},
                "usage": Usage(model="gemini/gemini-2.5-flash", prompt_tokens=100, completion_tokens=10, total_tokens=110),
            }

    agent = Agent(
        device=_FakeDevice(),
        client=_ClientWithUsage(),
        model="fake",
        max_turns=1,
        policy=Policy(),
        confirmer=AlwaysApproveConfirmer(),
    )
    result = agent.run("test")
    assert result.turn_log, "expected at least one turn"
    usage_dict = result.turn_log[0].get("usage")
    assert usage_dict is not None
    assert usage_dict["prompt_tokens"] == 100
    assert usage_dict["model"] == "gemini/gemini-2.5-flash"


def test_agent_omits_usage_when_client_does_not_provide():
    """A client that returns no `usage` key produces turn_log entries
    with no `usage` key (or a None placeholder — but absent is cleaner)."""
    from androidharness.agent import Agent
    from androidharness.policy import AlwaysApproveConfirmer, Policy

    xml = (
        "<?xml version='1.0'?>"
        "<hierarchy>"
        "  <node bounds='[0,0][1000,1000]'>"
        "    <node class='android.widget.Button' bounds='[0,0][10,10]' clickable='true'/>"
        "  </node>"
        "</hierarchy>"
    )

    class _FakeDevice:
        serial = "fake"
        model = "fake"
        def dump_hierarchy(self) -> str:
            return xml
        def screenshot(self) -> bytes:
            return b""

    class _ClientNoUsage:
        def generate(self, *, model, system_instruction, contents, tools):
            return {"name": "done", "args": {"success": True, "reason": "ok"}}

    agent = Agent(
        device=_FakeDevice(),
        client=_ClientNoUsage(),
        model="fake",
        max_turns=1,
        policy=Policy(),
        confirmer=AlwaysApproveConfirmer(),
    )
    result = agent.run("test")
    assert result.turn_log[0].get("usage") is None  # absent or explicitly None — both OK
```

Run: FAIL (the first test) — the turn_log entry has no `usage` key yet.

- [ ] **Step 3: Plumb usage through `Agent.run`.**

In `androidharness/agent.py`, find the `raw = self.client.generate(...)` line. Just after it, capture usage:

```python
raw = self.client.generate(
    model=self.model,
    system_instruction=SYSTEM_PROMPT,
    contents=contents,
    tools=GEMINI_FUNCTION_DECLARATIONS,
)
call = ToolCall(name=raw["name"], args=dict(raw.get("args", {})))
usage = raw.get("usage")
```

Then in the existing `turn_log.append({...})` block, add the usage entry. The cleanest way given the existing structure:

```python
turn_entry = {
    "turn": turn_idx,
    "observation_summary": obs.render(
        with_resource_ids=self.resource_id_in_render,
        sibling_collapse=self.sibling_collapse,
    ),
    "observation_payload": dict(obs_payload),
    "tool_call": {"name": call.name, "args": call.args},
    "tool_result": tool_result_payload,
}
if usage is not None:
    from dataclasses import asdict
    turn_entry["usage"] = asdict(usage)
turn_log.append(turn_entry)
```

Move the `from dataclasses import asdict` to the top of the file so it's not imported inside the loop (small perf consideration). Same for any other inline imports if it makes the diff cleaner.

- [ ] **Step 4: Run the new tests.**

```
uv run pytest -q tests/test_agent.py -k usage
```

- [ ] **Step 5: Run the full suite.**

```
uv run pytest -q
```

- [ ] **Step 6: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/agent.py tests/test_agent.py
git commit -m "feat(agent): stamp per-turn usage onto turn_log when available"
```

---

## Task 3: Runner aggregates usage into `result.json`

**Why next:** Per-turn data is now captured; runs.jsonl is the source of truth. Now compress to per-run totals so users have a single number per run.

**Files:**
- Modify: `androidharness/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Inspect the runner's existing result.json shape.**

```
grep -n "result.json\|usage\|status.*crashed\|turns_path" androidharness/runner.py | head -20
```

Find both writes of `result.json`: one in the success path, one in the crashed-except path.

- [ ] **Step 2: Write three failing runner tests in `tests/test_runner.py`.**

(Read the file first to see the existing test idioms — there are likely existing tests that build a fake agent + fake device + fake client and call `run_task`. Use the same shape.)

```python
def test_run_task_aggregates_usage_into_result_json(tmp_path):
    """Multi-turn usage from turn_log is aggregated per-model into
    result.json['usage_total']."""
    import json
    from androidharness.llm import Usage
    # ... build a fake client that returns different usage on different turns:
    # turn 1: gemini/gemini-2.5-flash, 100/10/110
    # turn 2: gemini/gemini-2.5-pro, 500/50/550
    # ... then run for 2 turns (3rd turn returns done()).
    # Assert result.json["usage_total"] == {
    #     "gemini/gemini-2.5-flash": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    #     "gemini/gemini-2.5-pro": {"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550},
    # }


def test_run_task_includes_cost_estimate_in_result_json(tmp_path):
    """result.json["cost_usd_estimate"] is the rounded sum from
    estimate_cost_usd applied to usage_total."""
    # Single-model run, flash: 1_000_000 prompt + 1_000_000 completion tokens
    # → 0.30 + 2.50 = 2.80 USD (with the v1 MODEL_PRICES).
    # Use a smaller number to avoid fragile float comparisons (assert pytest.approx).


def test_run_task_crashed_run_still_writes_usage_total(tmp_path):
    """A run that crashes after 2 turns still writes usage_total reflecting
    the 2 completed turns."""
    # Use a client that returns usage on turn 1 and 2, then raises on turn 3.
    # Assert result.json["status"] == "crashed" AND result.json["usage_total"] is present.
```

Flesh out the test bodies using the existing test patterns. The exact tooling (fake device, fake client) matches what `tests/test_runner.py` already does.

Run: `uv run pytest -q tests/test_runner.py -k usage`. Expect all three to FAIL — `result.json` doesn't have `usage_total` yet.

- [ ] **Step 3: Add aggregation to `runner.run_task`.**

Define a small helper near the top of `runner.py`:

```python
from collections import defaultdict


def _aggregate_usage(turn_log: list[dict]) -> dict[str, dict[str, int]]:
    """Sum prompt/completion/total tokens per model across the turn log.
    Turns without a `usage` key contribute nothing."""
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    for t in turn_log:
        u = t.get("usage")
        if not u:
            continue
        bucket = totals[u["model"]]
        bucket["prompt_tokens"] += u.get("prompt_tokens", 0)
        bucket["completion_tokens"] += u.get("completion_tokens", 0)
        bucket["total_tokens"] += u.get("total_tokens", 0)
    return dict(totals)
```

In the happy-path `result.json` write:

```python
usage_total = _aggregate_usage(result.turn_log)
result_payload = {
    "status": result.status,
    "success": result.success,
    "reason": result.reason,
    "turns": result.turns,
}
if usage_total:
    result_payload["usage_total"] = usage_total
_write_json(run_dir / "result.json", result_payload)
```

For the crashed path: the runner currently doesn't have a turn_log in scope at the except-clause (it caught `BaseException` from `agent.run` before the return). The fix is to read turns from the on-disk jsonl that `write_turn` has been appending to. Walk it in the except handler:

```python
except BaseException as e:
    turns_file.close()
    meta["ended_at"] = time.time()
    meta["status"] = "crashed"
    _write_json(run_dir / "meta.json", meta)

    # Aggregate usage from whichever turns landed before the crash.
    partial_turns: list[dict] = []
    with turns_path.open() as f:
        for line in f:
            try:
                partial_turns.append(json.loads(line))
            except json.JSONDecodeError:
                # truncated last line — skip it
                continue
    usage_total = _aggregate_usage(partial_turns)

    crashed_payload = {
        "status": "crashed",
        "success": False,
        "reason": f"{type(e).__name__}: {e}",
        "turns": len(partial_turns),
    }
    if usage_total:
        crashed_payload["usage_total"] = usage_total
    _write_json(run_dir / "result.json", crashed_payload)
    raise
```

Note: the `import json` already exists at the top of `runner.py`. Verify and only add if it doesn't.

- [ ] **Step 4: Run the three new tests.**

```
uv run pytest -q tests/test_runner.py -k usage
```

- [ ] **Step 5: Run the full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 6: Commit.**

```
git add androidharness/runner.py tests/test_runner.py
git commit -m "feat(runner): aggregate per-model usage_total into result.json"
```

---

## Task 4: Pricing module + `cost_usd_estimate` in result.json

**Files:**
- New: `androidharness/pricing.py`
- New: `tests/test_pricing.py`
- Modify: `androidharness/runner.py`

- [ ] **Step 1: Write three failing pricing tests in a new `tests/test_pricing.py`.**

```python
"""Tests for the cost-estimation helpers."""

from __future__ import annotations

import pytest


def test_estimate_cost_usd_single_model():
    from androidharness.pricing import estimate_cost_usd

    usage_total = {
        "gemini/gemini-2.5-flash": {
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "total_tokens": 2_000_000,
        }
    }
    # With the v1 MODEL_PRICES: 1M flash prompt = $0.30, 1M flash completion = $2.50.
    assert estimate_cost_usd(usage_total) == pytest.approx(2.80, rel=1e-9)


def test_estimate_cost_usd_multi_model():
    from androidharness.pricing import estimate_cost_usd

    usage_total = {
        "gemini/gemini-2.5-flash": {
            "prompt_tokens": 100_000,
            "completion_tokens": 100_000,
            "total_tokens": 200_000,
        },
        "gemini/gemini-2.5-pro": {
            "prompt_tokens": 100_000,
            "completion_tokens": 100_000,
            "total_tokens": 200_000,
        },
    }
    # Flash: 0.30*0.1 + 2.50*0.1 = 0.28
    # Pro:   1.25*0.1 + 10.00*0.1 = 1.125
    # Total: 1.405
    assert estimate_cost_usd(usage_total) == pytest.approx(1.405, rel=1e-9)


def test_estimate_cost_usd_unknown_model_contributes_zero():
    from androidharness.pricing import estimate_cost_usd

    usage_total = {
        "weirdvendor/mystery-model": {
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "total_tokens": 2_000_000,
        }
    }
    assert estimate_cost_usd(usage_total) == 0.0
```

Run: FAIL — `androidharness.pricing` module does not exist.

- [ ] **Step 2: Create `androidharness/pricing.py`.**

```python
"""Static cost estimation for LLM usage.

Prices are point-in-time references (see `MODEL_PRICES` below). The dollar
amounts computed here are labeled `cost_usd_estimate` everywhere — they are
not a substitute for the provider bill. Update the constant or move it to
config if a real bill diverges noticeably from the estimate.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("androidharness.pricing")


# USD per million tokens. Verified against public list prices as of 2026-05-23.
# Tier-specific rates (free vs. paid) may differ — verify against your bill.
MODEL_PRICES: dict[str, dict[str, float]] = {
    "gemini/gemini-2.5-flash":      {"prompt": 0.30, "completion": 2.50},
    "gemini/gemini-2.5-pro":        {"prompt": 1.25, "completion": 10.00},
    "gemini/gemini-2.5-flash-lite": {"prompt": 0.10, "completion": 0.40},
    "anthropic/claude-haiku-4-5":   {"prompt": 1.00, "completion": 5.00},
    "openai/gpt-4o-mini":           {"prompt": 0.15, "completion": 0.60},
}

_warned_unknown: set[str] = set()


def estimate_cost_usd(usage_total: dict[str, dict[str, int]]) -> float:
    """Estimate the total USD spend for an aggregated usage_total dict.

    Shape of `usage_total` matches the runner's aggregation:
        {model_name: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}}

    Unknown models contribute 0 to the total and emit a single WARN-level log
    line (per process) so a misconfigured pricing constant is visible without
    spamming.
    """
    total = 0.0
    for model, bucket in usage_total.items():
        prices = MODEL_PRICES.get(model)
        if prices is None:
            if model not in _warned_unknown:
                _log.warning("no MODEL_PRICES entry for %r; contributing $0 to cost estimate", model)
                _warned_unknown.add(model)
            continue
        total += bucket.get("prompt_tokens", 0) * prices["prompt"] / 1_000_000
        total += bucket.get("completion_tokens", 0) * prices["completion"] / 1_000_000
    return total
```

- [ ] **Step 3: Wire `cost_usd_estimate` into the runner's result.json.**

In `androidharness/runner.py`, in both the happy-path and crashed-path writes, after computing `usage_total`:

```python
from androidharness.pricing import estimate_cost_usd
...
if usage_total:
    result_payload["usage_total"] = usage_total
    result_payload["cost_usd_estimate"] = round(estimate_cost_usd(usage_total), 6)
```

(Six decimals of precision keeps tiny costs visible without scientific notation.)

- [ ] **Step 4: Extend one runner test.**

Extend `test_run_task_includes_cost_estimate_in_result_json` from Task 3 with an explicit cost-value assertion that matches what `estimate_cost_usd` would compute for the test's usage values.

- [ ] **Step 5: Run pricing + runner tests.**

```
uv run pytest -q tests/test_pricing.py tests/test_runner.py
```

- [ ] **Step 6: Full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/pricing.py androidharness/runner.py tests/test_pricing.py tests/test_runner.py
git commit -m "feat(pricing): MODEL_PRICES + cost_usd_estimate in result.json"
```

---

## Task 5: `androidharness usage` CLI subcommand

**Files:**
- Modify: `androidharness/cli.py`
- New: `tests/test_cli_usage.py`

- [ ] **Step 1: Write four failing CLI tests in a new `tests/test_cli_usage.py`.**

```python
"""Tests for the `androidharness usage` subcommand — walks runs/ and prints
spend per run + a totals row."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from androidharness.cli import app

runner = CliRunner()


def _make_run(
    runs_dir: Path,
    name: str,
    *,
    usage_total: dict | None = None,
    cost: float | None = None,
    turns: int = 5,
    status: str = "done",
) -> Path:
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    result: dict = {
        "status": status,
        "success": status == "done",
        "reason": "ok",
        "turns": turns,
    }
    if usage_total is not None:
        result["usage_total"] = usage_total
        if cost is not None:
            result["cost_usd_estimate"] = cost
    (run_dir / "result.json").write_text(json.dumps(result))
    return run_dir


@pytest.fixture
def isolated_home_with_runs(tmp_path, monkeypatch):
    """Point HOME and the config's runs_dir at a temp dir; return the runs dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    cfg_dir = tmp_path / ".androidharness"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(f"defaults:\n  runs_dir: {runs_dir}\n")
    return runs_dir


def test_usage_prints_per_run_and_total_rows(isolated_home_with_runs):
    runs = isolated_home_with_runs
    _make_run(runs, "20260523T080000Z-aaa", usage_total={
        "gemini/gemini-2.5-flash": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    }, cost=0.000055, turns=4)
    _make_run(runs, "20260523T090000Z-bbb", usage_total={
        "gemini/gemini-2.5-flash": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}
    }, cost=0.00011, turns=6)

    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0, result.stdout
    assert "20260523T080000Z-aaa" in result.stdout
    assert "20260523T090000Z-bbb" in result.stdout
    # Totals row sums prompt+completion+total across runs
    assert "300" in result.stdout       # 100 + 200 prompt
    assert "330" in result.stdout       # 110 + 220 total


def test_usage_skips_runs_missing_usage_total(isolated_home_with_runs):
    """Legacy runs without usage_total appear with `—` placeholders, contribute 0."""
    runs = isolated_home_with_runs
    _make_run(runs, "20260523T080000Z-aaa", usage_total=None, turns=3)
    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0, result.stdout
    assert "20260523T080000Z-aaa" in result.stdout
    assert "—" in result.stdout or "-" in result.stdout


def test_usage_since_flag_filters_by_date(isolated_home_with_runs):
    runs = isolated_home_with_runs
    _make_run(runs, "20260520T080000Z-old", usage_total={
        "gemini/gemini-2.5-flash": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    })
    _make_run(runs, "20260523T080000Z-new", usage_total={
        "gemini/gemini-2.5-flash": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}
    })
    result = runner.invoke(app, ["usage", "--since", "2026-05-22"])
    assert result.exit_code == 0, result.stdout
    assert "20260520T080000Z-old" not in result.stdout
    assert "20260523T080000Z-new" in result.stdout


def test_usage_json_flag_outputs_machine_readable(isolated_home_with_runs):
    runs = isolated_home_with_runs
    _make_run(runs, "20260523T080000Z-aaa", usage_total={
        "gemini/gemini-2.5-flash": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    }, cost=0.000055)
    result = runner.invoke(app, ["usage", "--json"])
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    assert "runs" in parsed and "totals" in parsed
```

Run: FAIL — `usage` is an unknown subcommand.

- [ ] **Step 2: Add the `usage` subcommand in `androidharness/cli.py`.**

```python
from datetime import datetime
from pathlib import Path


@app.command("usage")
def usage_cmd(
    since: str | None = typer.Option(
        None, "--since",
        help="Only include runs started on or after this date (YYYY-MM-DD).",
    ),
    model: str | None = typer.Option(
        None, "--model",
        help="Only count runs that hit this model (substring match against the keys in usage_total).",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON instead of the table.",
    ),
    config_path: Path | None = typer.Option(None, "--config", help="Override the config path."),
) -> None:
    """Walk runs/ and print token + cost totals per run, with a grand total."""
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    runs_dir = Path(cfg.defaults.runs_dir)
    if not runs_dir.is_dir():
        typer.echo(f"no runs directory at {runs_dir}", err=True)
        raise typer.Exit(code=1)

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as e:
            typer.echo(f"--since: not a valid YYYY-MM-DD: {since!r}", err=True)
            raise typer.Exit(code=2) from e

    # The runs/ dir contains entries named like `20260523T082255Z-4a435f`.
    # Parse the timestamp prefix when filtering by --since.
    rows: list[dict] = []
    grand_total: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    grand_cost = 0.0

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        if not result_path.is_file():
            continue

        if since_dt is not None:
            # Best-effort: parse the 16-char prefix YYYYMMDDTHHMMSSZ
            stamp = run_dir.name[:16]
            try:
                run_dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
            if run_dt < since_dt:
                continue

        try:
            result = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        usage_total = result.get("usage_total") or {}
        if model is not None and not any(model in m for m in usage_total.keys()):
            # No matching model in this run — skip when filter is active.
            if usage_total:
                continue

        run_prompt = sum(b.get("prompt_tokens", 0) for b in usage_total.values())
        run_completion = sum(b.get("completion_tokens", 0) for b in usage_total.values())
        run_total = sum(b.get("total_tokens", 0) for b in usage_total.values())
        run_cost = result.get("cost_usd_estimate")

        rows.append({
            "run_id": run_dir.name,
            "turns": result.get("turns"),
            "models": sorted(usage_total.keys()),
            "prompt_tokens": run_prompt,
            "completion_tokens": run_completion,
            "total_tokens": run_total,
            "cost_usd_estimate": run_cost,
        })
        grand_total["prompt_tokens"] += run_prompt
        grand_total["completion_tokens"] += run_completion
        grand_total["total_tokens"] += run_total
        if isinstance(run_cost, (int, float)):
            grand_cost += run_cost

    if as_json:
        typer.echo(json.dumps({
            "runs": rows,
            "totals": {**grand_total, "cost_usd_estimate": round(grand_cost, 6)},
        }, indent=2))
        return

    # Plain text table on stdout.
    header = f"{'run_id':<32} {'turns':>5} {'model':<32} {'prompt':>8} {'compl':>7} {'total':>8} {'cost_usd':>10}"
    typer.echo(header)
    for r in rows:
        models = ",".join(r["models"]) or "—"
        prompt = str(r["prompt_tokens"]) if r["prompt_tokens"] else "—"
        completion = str(r["completion_tokens"]) if r["completion_tokens"] else "—"
        total = str(r["total_tokens"]) if r["total_tokens"] else "—"
        cost = f"${r['cost_usd_estimate']:.4f}" if isinstance(r["cost_usd_estimate"], (int, float)) else "—"
        typer.echo(
            f"{r['run_id']:<32} {str(r['turns']):>5} {models:<32} "
            f"{prompt:>8} {completion:>7} {total:>8} {cost:>10}"
        )
    # Totals row
    typer.echo("-" * len(header))
    typer.echo(
        f"{'':<32} {'':>5} {'':<32} "
        f"{grand_total['prompt_tokens']:>8} {grand_total['completion_tokens']:>7} "
        f"{grand_total['total_tokens']:>8} ${grand_cost:.4f}".rjust(10)
    )
```

(Layout details are flexible — match the existing CLI style in `cli.py` for help-string conventions, error handling, etc. Use `typer.echo` for stdout.)

- [ ] **Step 3: Run the new tests.**

```
uv run pytest -q tests/test_cli_usage.py
```

- [ ] **Step 4: Full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```
git add androidharness/cli.py tests/test_cli_usage.py
git commit -m "feat(cli): androidharness usage — walk runs/ and report spend"
```

---

## Task 6: Documentation pass

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/configuration.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/architecture.md`.** Add a short paragraph in the appropriate section (near `agent.py` or `runner.py` discussion) about per-turn usage capture + per-run aggregation. One paragraph, no more.

- [ ] **Step 2: `docs/configuration.md`.** Add a small section at the end titled "Pricing" pointing at `androidharness/pricing.py` and explaining that prices are point-in-time references the user can edit if their bill diverges.

- [ ] **Step 3: `docs/roadmap.md`.** Append a new row to the v2 milestone table:

```
| 23 | **Token tracking + spend visibility** — per-turn `usage` on turn_log; per-run `usage_total` + `cost_usd_estimate` in result.json; `androidharness usage` CLI | **Shipped** | <first> → <last> |
```

Find `<first>` and `<last>` via `git log --oneline <pre-M23-sha>..HEAD` after Task 5 lands. Update the "Current focus" paragraph at the bottom to mention M23 shipped.

- [ ] **Step 4: Commit.**

```
git add docs/architecture.md docs/configuration.md docs/roadmap.md
git commit -m "docs: M23 shipped — token tracking + spend visibility documented"
```

---

## Final verification

- [ ] **Step 1: Full test suite.**

```
uv run pytest -q
```

- [ ] **Step 2: Lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 3: Run `androidharness usage` against the local `runs/` directory.**

```
androidharness usage
```

Expect a per-run table with the historical runs. Recent post-M23 runs show real token counts; pre-M23 runs show `—` placeholders.

- [ ] **Step 4: Optional one real run to populate Measurements.**

```
androidharness run "Open Settings and tell me the device model name"
```

Then re-run `androidharness usage` and paste the table into the M23 spec's Measurements section.

- [ ] **Step 5: Subagent dispatch review (recommended).** If executing via `superpowers:subagent-driven-development`, the two-stage review (spec compliance + code quality) runs per-task; a final reviewer pass over the full M23 commit range happens after Task 6.

---

## Risks & mitigations (recapped)

| Risk | Mitigation |
|---|---|
| LiteLLM's `response.usage` shape varies. | `_extract_usage` is defensive — `getattr(..., 0)` defaults, missing whole-`usage` returns None. |
| `response.model` reflects request rather than resolved deployment for some Router versions. | Acceptable v1: usage groups by whatever LiteLLM reports. The dollar figure stays right because the price map keys match what LiteLLM returns. Future M can dig into the Router's internal state for finer attribution. |
| Hard-coded prices drift. | `cost_usd_estimate` is named, not `cost_usd`. Docstring at `MODEL_PRICES` points users at their bill. Adjusting is a one-line edit. |
| Crashed runs may have truncated `turns.jsonl`. | Aggregation skips lines that fail `json.loads`. The jsonl is line-atomic per `write_turn` so this is a tail-only concern. |
| `androidharness usage` is slow on large runs/ dirs. | v1 reads only `result.json` per run (small file). 1 000 runs ≈ 50 ms total. Cache index is M7 storage seam's job, not M23's. |
| Existing test fakes break. | The agent reads `raw.get("usage")` defensively; turn_log writer skips the key when None. Existing fakes need zero updates. |

---

## Sequencing summary

1. Task 1 — `Usage` dataclass + LiteLLM clients attach usage + 3 LLM tests.
2. Task 2 — Agent stamps usage onto turn_log + 2 agent tests.
3. Task 3 — Runner aggregates per-model usage into `result.json` (happy + crashed paths) + 3 runner tests.
4. Task 4 — `androidharness/pricing.py` + `cost_usd_estimate` in result.json + 3 pricing tests.
5. Task 5 — `androidharness usage` CLI subcommand + 4 CLI tests.
6. Task 6 — Docs pass + mark Shipped on the roadmap.
