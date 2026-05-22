# Specs and plans index

`docs/superpowers/` is the historical record of how AndroidHarness was designed and built. Specs describe **intent at design time**; plans describe **how the work was decomposed**; the code is the **as-built source of truth**.

These files are intentionally **not rewritten after a milestone ships** — they would lose their value as a record of what was thought, when. For current state, use:

- [`docs/roadmap.md`](../roadmap.md) — canonical shipped-vs-pending table for v1 baseline and the v2 roadmap.
- [`docs/architecture.md`](../architecture.md) — what the code looks like today.
- `git log --oneline e6ce1a9..HEAD` (or any base SHA) — the executed work.

## Specs

| Spec | What it covers |
|------|---------------|
| [`specs/2026-05-19-android-ai-harness-design.md`](specs/2026-05-19-android-ai-harness-design.md) | v1 design — the agent loop, tool vocabulary, perception, device Protocol, run artifacts, Gemini integration. Drove the v1 baseline. |
| [`specs/2026-05-20-v2-stack-and-scale-design.md`](specs/2026-05-20-v2-stack-and-scale-design.md) | v2 multi-milestone design — the seam model, provider gateway via LiteLLM, throttler/Router, policy gate, episodic memory, web UI, flow runtime, device proxy. All 21 v2 milestones are listed here. |

## Plans

Each plan was followed via `superpowers:subagent-driven-development` (fresh subagent per task + two-stage review). Status reflects the canonical `docs/roadmap.md` table.

| Plan | Status | Shipped at |
|------|--------|------------|
| [`plans/2026-05-20-android-ai-harness.md`](plans/2026-05-20-android-ai-harness.md) | **Shipped** (v1 baseline) | Commits up to `035c625` |
| [`plans/2026-05-20-v2-milestone-1-config-schema.md`](plans/2026-05-20-v2-milestone-1-config-schema.md) | **Shipped** (M1 — Pydantic `AndroidHarnessConfig`, YAML load/save, `androidharness config` CLI) | `902d71a` → `558354b` |
| [`plans/2026-05-21-v2-milestone-2-litellm-provider-seam.md`](plans/2026-05-21-v2-milestone-2-litellm-provider-seam.md) | **Shipped** (M2 — `LLMClient` Protocol, `LiteLLMClient`, multi-provider config) | `280f267` → `b49e4a2` (+ `488888e` docs) |
| [`plans/2026-05-21-v2-milestone-3-throttler.md`](plans/2026-05-21-v2-milestone-3-throttler.md) | **Shipped** (M3 — `BucketConfig`, `ThrottlerConfig`, `logical_models`, `LiteLLMRouterClient`) | `61ea308` → `f88e55e` (+ `e6ce1a9` docs) |
| [`plans/2026-05-22-v2-milestone-4-policy-seam.md`](plans/2026-05-22-v2-milestone-4-policy-seam.md) | **Shipped** (M4 — `PolicyConfig`, `Policy`, `Confirmer` Protocol, `CliConfirmer`, `--policy` flag) | `af1233c` → `70b1445` (+ `31cd7be` docs, `3cf5e58` polish) |

## Post-milestone work not in any plan

These were small follow-ups surfaced by real runs, landed without their own plan file. Listed here so a fresh session knows where the deviations live:

- `7a112fb` — `meta.json` captures the policy snapshot; `Policy.apply` tags confirm-approved messages with `"[confirmed] "` so artifacts distinguish gated calls from auto ones.
- `1fdecc5` — `setup_logging` now streams to stderr alongside the rotating file (renamed from `setup_file_logging`; back-compat alias kept). The agent's per-turn `_log.info` calls now appear live in the terminal.
- `5e46ef9` — `type_text` with `replace=False` actually appends (was silently overwriting because `set_text` always overwrites).
- `ac4ed18` — `type_text` reads back after writing; raises `TypeFieldMismatchError` when the field disagrees (catches the `maxLength` + toast case the model otherwise can't perceive).
- `d0f62bf` — doc refresh in `architecture.md` / `development.md` to reflect the `set_text` rewrite + read-back behavior.

## When to write a new plan vs. a small commit

- New plan + subagent dispatch: any milestone in the v2 roadmap, any feature that touches more than 2 files, any change that needs TDD across multiple components.
- Direct commit: bug fixes surfaced by real runs (like the four post-M4 items above), single-file refactors, doc-only updates, config tuning.

The plan template is well-established by the M1–M4 files — copy the shape of the most recent one and adapt.
