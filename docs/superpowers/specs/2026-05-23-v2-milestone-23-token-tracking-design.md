# v2 Milestone 23 — Token tracking + spend visibility design

**Status:** spec, ready to plan.
**Date:** 2026-05-23.
**Parent spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` (no direct anchor — this fills a missing observability slot the parent spec never named).

## Goal

Capture the LLM-side token usage of every turn into the run's artifacts, aggregate per-run totals into `result.json`, and expose a `androidharness usage` CLI that walks `runs/` and reports spend across the local history. The user moves from "I have no idea what that 40-turn Binance run cost me" to "that run was 18 312 prompt + 1 423 completion tokens, ~$0.012". Token tracking is also the prerequisite for any A/B experiment (e.g. M24's mandatory-screenshot experiment) where the question "did the change save tokens net of any new cost" needs a real before/after.

The feature is always-on with no config flag — every `LLMClient.generate` call returns `usage` alongside the tool call, the agent stamps it onto each `turn_log` entry, the runner aggregates per-model on completion, and the CLI summarizes. When a client implementation can't supply usage (fake clients in tests, the GoogleGenaiClient when the SDK doesn't expose it), the field is simply absent and the rest of the chain degrades cleanly to zero.

## Non-goals

- **Pricing in config.** Prices live as a static constant in a new `androidharness/pricing.py` module for v1. They drift over time; moving them to YAML is a future-M follow-up if real bills diverge from estimates noticeably.
- **Throttler integration.** The token-bucket throttler estimates pre-flight cost for rate-limiting; M23 captures post-flight actuals for accounting. Different purposes, no overlap. The throttler's logic is untouched.
- **Cached / reasoning token sub-counts.** Some providers report `cached_content_tokens_count`, `reasoning_tokens`, etc. Basic `prompt_tokens` + `completion_tokens` + `total_tokens` covers >95% of accounting needs; sub-counts can layer on later.
- **Real-time cost capping.** "Stop the run if it crosses $X" is a safety feature that needs spend-during-run, not after-run aggregation. M23 measures; capping is a separate milestone.
- **Per-tool-call cost.** One tool call per turn today, so per-turn equals per-call. If multi-call turns ever ship, the breakdown lands then.
- **Schema migration of existing `result.json` files.** Old runs simply lack `usage_total` and `cost_usd_estimate`; the CLI tolerates missing keys.

## Definition of "usage"

Every `LLMClient.generate(...)` call (where the underlying provider returns usage data) attaches a `Usage` dataclass:

```python
@dataclass(frozen=True)
class Usage:
    model: str            # the *actual* model used post-fallback (e.g. "gemini/gemini-2.5-flash")
    prompt_tokens: int    # input tokens billed
    completion_tokens: int  # output tokens billed
    total_tokens: int     # prompt + completion (provider sometimes reports a slightly different total — we trust the provider)
```

Why `model` is on the Usage and not just the run's meta: with the M22 fallback chain in place, a single run's turns may bill against `gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro`, and `gemini/gemini-2.5-flash-lite` depending on which deployment answered each call. Per-model breakdown is essential — pro is roughly 4× the flash rate.

## Turn-artifact shape

Each line in `turns.jsonl` already carries:

```json
{
  "turn": 1,
  "observation_summary": "...",
  "observation_payload": {...},
  "tool_call": {"name": "tap", "args": {...}},
  "tool_result": {...}
}
```

M23 adds an optional `usage` field:

```json
{
  ...
  "usage": {
    "model": "gemini/gemini-2.5-flash",
    "prompt_tokens": 1234,
    "completion_tokens": 89,
    "total_tokens": 1323
  }
}
```

When the client doesn't return usage (test fakes, non-LiteLLM clients with stubbed responses), the key is omitted entirely — no `"usage": null` placeholder, no `0`-filled stub.

## Run-result aggregation

`result.json` currently:

```json
{
  "status": "done",
  "success": true,
  "reason": "...",
  "turns": 12
}
```

M23 extends with per-model totals and an estimated cost:

```json
{
  "status": "done",
  "success": true,
  "reason": "...",
  "turns": 12,
  "usage_total": {
    "gemini/gemini-2.5-flash": {
      "prompt_tokens": 18312,
      "completion_tokens": 1423,
      "total_tokens": 19735
    }
  },
  "cost_usd_estimate": 0.01205
}
```

The aggregation is computed by `runner.run_task` from the turn_log after `agent.run` returns. When all turns lacked usage data (legacy runs reconstructed in tests, fake clients), the new fields are omitted — the CLI tolerates their absence.

The crashed-run path (`status: "crashed"`) also writes `usage_total` from whichever turns landed before the crash. This is important: a 40-turn crash that burned 30 turns of tokens should still be visible in the spend report.

## Pricing

A new `androidharness/pricing.py` module holds a static price map and a `estimate_cost_usd(usage_total)` helper:

```python
MODEL_PRICES: dict[str, dict[str, float]] = {
    # USD per million tokens, as of 2026-05-23 (public list, text rates).
    # Verify against your bill; tier-specific (free/paid) rates may differ.
    "gemini/gemini-2.5-flash":       {"prompt": 0.30,  "completion": 2.50},
    "gemini/gemini-2.5-pro":         {"prompt": 1.25,  "completion": 10.00},
    "gemini/gemini-2.5-flash-lite":  {"prompt": 0.10,  "completion": 0.40},
    "anthropic/claude-haiku-4-5":    {"prompt": 1.00,  "completion": 5.00},
    "openai/gpt-4o-mini":            {"prompt": 0.15,  "completion": 0.60},
}


def estimate_cost_usd(usage_total: dict[str, dict[str, int]]) -> float:
    """Sum `(prompt_tokens × prompt_rate + completion_tokens × completion_rate) / 1e6`
    across every model present. Unknown models contribute 0 (logged once at WARN)."""
```

The values are honest best-effort references; the docstring above the dict points users at their actual bill and at `MODEL_PRICES` for adjustments. A future M can move this dict into config.

## `androidharness usage` CLI

A new subcommand walks `runs/*/result.json` and prints a per-run + totals table on stdout:

```
$ androidharness usage
run_id                          turns  model                          prompt  completion  total  cost_usd
20260523T082255Z-4a435f         38     gemini/gemini-2.5-flash        42013   3211        45224  $0.0207
20260523T082550Z-1af485         12     gemini/gemini-2.5-flash        13442   892         14334  $0.0063
20260523T090112Z-6f06d8         2      gemini/gemini-2.5-flash        1844    72          1916   $0.0008
20260523T092503Z-b5e933         16     gemini/gemini-2.5-flash        18312   1423        19735  $0.0121
20260523T094646Z-af68f4         40     gemini/gemini-2.5-flash        47881   3502        51383  $0.0231
---
                                108                                    123492  9100        132592 $0.0630
```

Optional flags (keep the v1 surface tight):
- `--since YYYY-MM-DD` — filter by run start date (parsed from the timestamp prefix in the run dir name).
- `--model <name>` — filter to runs that hit a specific model (useful with fallback chains).
- `--json` — dump the raw aggregation rather than the table.

Runs missing `usage_total` (legacy, fake-client runs) are listed with `—` in the numeric columns and contribute 0 to the totals.

## Pipeline placement

```
client.generate(...) 
  → {"name": ..., "args": ..., "usage": Usage(...)}    # M23: usage added
agent.run loop:
  raw = client.generate(...)
  call = ToolCall(name=raw["name"], args=raw["args"])
  turn_log.append({..., "usage": raw.get("usage")})    # M23: stamped on turn
runner.run_task:
  for turn in turn_log:
    aggregate per-model from turn.get("usage")
  result.json["usage_total"] = aggregated              # M23: per-run totals
  result.json["cost_usd_estimate"] = estimate_cost_usd(usage_total)
cli usage:
  walk runs/*/result.json
  print table                                          # M23: cross-run view
```

No new flag plumbing, no config. The only seam-touching change is `LLMClient.generate`'s return shape — extended dict, not breaking, optional `usage` key.

## Plumbing the data

1. **`androidharness/llm.py`** — define `Usage` (frozen dataclass). `LiteLLMClient.generate` reads `response.usage` and `response.model` (the resolved deployment, important for fallback chains) and attaches a `Usage(...)` to the returned dict under key `"usage"`. `LiteLLMRouterClient.generate` does the same; `response.model` reflects which deployment the Router picked. `GoogleGenaiClient.generate` reads `response.usage_metadata` (google-genai's analogue) best-effort; if absent, simply omit `usage`.
2. **`androidharness/agent.py`** — `Agent.run`'s `raw = self.client.generate(...)` already produces the dict. Add `usage = raw.get("usage")`; pass into the `turn_log` entry as `"usage": dataclasses.asdict(usage) if usage else None` (dropped when None at JSON-serialize time by an `_omit_none` helper, or just don't write the key — preferred).
3. **`androidharness/runner.py`** — after `agent.run` returns (and on the crashed path), walk the turn_log and aggregate. Inject `usage_total` and `cost_usd_estimate` into the result.json dict before writing.
4. **`androidharness/pricing.py`** — new module; `MODEL_PRICES` constant + `estimate_cost_usd(usage_total)` function. No I/O, no global state.
5. **`androidharness/cli.py`** — new `usage` subcommand. Reads from the existing `cfg.defaults.runs_dir` for the source directory.

## Testing strategy

| Test | What it asserts |
|---|---|
| `tests/test_llm.py::test_litellm_client_returns_usage_from_response` | LiteLLMClient.generate puts a `usage` dict on the return when the underlying response carries `.usage`. |
| `tests/test_llm.py::test_litellm_client_omits_usage_when_response_has_none` | When the fake response lacks `.usage`, the return dict lacks the `usage` key (no `None` placeholder). |
| `tests/test_llm.py::test_litellm_router_returns_usage_with_resolved_model` | LiteLLMRouterClient.generate records `response.model` (post-fallback name), not the logical name from the request. |
| `tests/test_agent.py::test_agent_stamps_usage_onto_turn_log` | When the client returns usage, the corresponding turn_log entry has the same usage dict. |
| `tests/test_agent.py::test_agent_omits_usage_when_client_does_not_provide` | A client that returns `{"name": ..., "args": ...}` (no usage) yields turn_log entries without a `usage` key. |
| `tests/test_runner.py::test_run_task_aggregates_usage_into_result_json` | A multi-turn run with mixed-model usage produces correct per-model totals in `result.json["usage_total"]`. |
| `tests/test_runner.py::test_run_task_includes_cost_estimate_in_result_json` | `result.json["cost_usd_estimate"]` matches the expected sum for the captured usage. |
| `tests/test_runner.py::test_run_task_crashed_run_still_writes_usage_total` | A crashed run writes `usage_total` from the turns that completed before the crash. |
| `tests/test_pricing.py::test_estimate_cost_usd_single_model` | Single-model usage produces the right dollar amount. |
| `tests/test_pricing.py::test_estimate_cost_usd_multi_model` | Multi-model usage sums correctly. |
| `tests/test_pricing.py::test_estimate_cost_usd_unknown_model_contributes_zero` | Unknown model name → zero contribution, no exception. |
| `tests/test_cli_usage.py::test_usage_prints_per_run_and_total_rows` | The `usage` subcommand walks a stubbed runs/ dir and prints the expected table. |
| `tests/test_cli_usage.py::test_usage_skips_runs_missing_usage_total` | Legacy runs (no `usage_total` in result.json) render with `—` placeholders. |
| `tests/test_cli_usage.py::test_usage_since_flag_filters_by_date` | `--since` filters out runs older than the date. |
| `tests/test_cli_usage.py::test_usage_json_flag_outputs_machine_readable` | `--json` returns parseable JSON. |

Most tests construct fake objects directly. The LiteLLM tests use the project's existing monkeypatch-`litellm.completion` pattern from `tests/test_llm.py`.

## Files touched

**Modified:**
- `androidharness/llm.py` — add `Usage` dataclass; LiteLLMClient + LiteLLMRouterClient attach `usage` to return dict; best-effort attach in GoogleGenaiClient if applicable.
- `androidharness/agent.py` — pass through `raw.get("usage")` onto each `turn_log` entry.
- `androidharness/runner.py` — aggregate usage from turn_log into `result.json` (both happy and crashed paths).
- `androidharness/cli.py` — new `usage` subcommand.
- `tests/test_llm.py` — 3 new tests.
- `tests/test_agent.py` — 2 new tests.
- `tests/test_runner.py` — 3 new tests.

**New:**
- `androidharness/pricing.py` — `MODEL_PRICES` constant + `estimate_cost_usd(...)`.
- `tests/test_pricing.py` — 3 unit tests.
- `tests/test_cli_usage.py` — 4 CLI tests.

**Untouched:** `config.py`, `perception.py`, `render.py`, `device.py`, `tools.py`, `policy.py`, `imaging.py`, `logging_setup.py`, the `web/` subpackage.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| LiteLLM's `response.usage` shape varies across providers / versions. | Read defensively: `getattr(response, "usage", None)`; if present, read `.prompt_tokens` / `.completion_tokens` / `.total_tokens` with `getattr(..., 0)` defaults. Any extraction failure logs at WARN once per provider per process and continues with `usage=None`. |
| `response.model` is sometimes the request model (e.g. logical name) rather than the resolved deployment. | For the LiteLLMClient path, `response.model` is typically the resolved deployment. For the Router, fall back to the logical name if the deployment field is missing — that already preserves accountability ("I asked for `default`; total spend on `default` was $X"), it just blurs per-deployment attribution which the user can recover via LiteLLM's verbose logs if they want. |
| Hard-coded prices drift; users get misleading dollar estimates. | The dollar figure is labeled `cost_usd_estimate` everywhere — not "actual cost". Docstrings point at the constant and at the user's bill. A follow-up M can move pricing to config. |
| Crashed-path aggregation reads partially-written turns.jsonl. | The runner already reopens the file via `turns_path.open()` after `.close()`; M23 just adds an aggregation pass. The jsonl is line-atomic per `write_turn`, so even a crash mid-write leaves a valid prefix of complete lines. Robust to crash. |
| `androidharness usage` is slow on a runs/ dir with thousands of entries. | v1 just reads `result.json` per run (small file). On 1 000 runs that's ~50 ms total. If it becomes a problem later, cache aggregations in a single index file — that's the M7 storage seam's job, not M23's. |
| Tests that fake `LLMClient.generate` break because they don't return `usage`. | Defensive on the agent side: `raw.get("usage")` returns `None`, and the turn_log writer skips the key. Existing fakes need zero updates. |

## Sequencing inside the milestone

1. `Usage` dataclass + LiteLLM clients attach usage + 3 LLM tests.
2. Agent stamps usage onto turn_log + 2 agent tests.
3. Runner aggregates per-model into `result.json` (happy + crashed paths) + 3 runner tests.
4. `androidharness/pricing.py` module + `cost_usd_estimate` in `result.json` + 3 pricing tests.
5. `androidharness usage` CLI subcommand + 4 CLI tests.
6. Docs pass: architecture, configuration (note that pricing is in code for v1), roadmap.

## Measurements

_To be filled in before the milestone is marked Shipped — after Task 5 lands, run `androidharness usage` against the existing runs in `runs/` and paste the table here._
