# Roadmap

Status is based on git history, not the spec wish-list. A milestone counts as shipped only when a commit lands the code.

Spec references:
- v1 design: `docs/superpowers/specs/2026-05-19-android-ai-harness-design.md`
- v2 design: `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md`

---

## v1 baseline — shipped

All v1 milestones are complete as of the initial implementation commits.

| Feature | Commit | Notes |
|---------|--------|-------|
| Package skeleton, deps | `62f1b23` | uv project, uiautomator2, lxml, Pillow |
| Perception: XML → Observation | `a1b123a`, `99b6292` | compact numbered node list |
| Device Protocol + UIAutomatorDevice | `89eb679` | uiautomator2 wrapper, FakeDevice fixture |
| Tool vocabulary + validation | `fa122e1` | all 9 v1 tools, GEMINI_FUNCTION_DECLARATIONS |
| Agent loop | `435555f` | Gemini function-calling, screenshot escape hatch |
| Run artifacts (meta/turns/result/screenshots) | `9a9d6f4` | incremental JSONL writes |
| CLI: `devices` + `run` | `d804b95` | Typer app, GoogleGenaiClient |
| Gemini retry/backoff | `147c776` | exponential backoff on 429/5xx |
| IME restore after `type` | `1316f26` | captures and restores prior IME |
| Rotating file logs | `9b22d1d` | `setup_file_logging`, 10 MB/5 files |
| No-progress detector | `cbfe3af` | 3-turn identical-call+obs detector, SYSTEM_PROMPT guidance |
| Incremental turn writes + crash recovery | `f00bbe3` | `on_turn` callback, `status: crashed` |

---

## v2 milestones

Items 1–5 are the "v2 minimum" per the spec. Items 6+ are the long tail.

| # | Milestone | Status | Commit(s) |
|---|-----------|--------|-----------|
| 1 | **Config schema** — Pydantic `AndroidHarnessConfig` + YAML load/save + CLI integration | **Shipped** | `902d71a`, `c677d16`, `beb4c33`, `558354b` |
| 2 | Provider seam — LiteLLM + `LLMClient` refactor | **Shipped** | `280f267`, `9b75726`, `8712309`, `b3754a9`, `e577254`, `a1d96b3`, `b49e4a2` |
| 3 | Throttler — token-bucket + Router fallback | **Shipped** | `61ea308`, `ae02883`, `e1b1ac0`, `2c1c74b`, `f88e55e` |
| 4 | Policy seam — destructive-action gating | **Shipped** | `af1233c`, `181cbcd`, `1f4c813`, `70b1445` |
| 5 | **Web UI v2.0 — Settings UI** — FastAPI + HTMX editor for providers, models, throttler, policy, devices, logging, general defaults | **Shipped** | `04a61e7` → `1d0bba4` |
| 6 | Perception compression step 1 — sibling collapse | Pending | |
| 7 | Storage seam — SQLiteSink + alembic migrations | Pending | |
| 8 | Web UI v2.1 — live monitoring | Pending | |
| 9 | OTel spans + JSON exporter | Pending | |
| 10 | Web UI v2.2 — replay | Pending | |
| 11 | Perception compression steps 2–3 (viewport filter, resource-id in render) | **Shipped** | Viewport filter `6e81c6b`; resource-id in render `615f1a5` |
| 12 | Vector store layer (a) — `recall_similar_runs` | Pending | |
| 13 | Web UI v2.3 — launcher | Pending | |
| 14 | Notification-shade tool pair | **Shipped** | `587107e` (`open_notifications`, `close_notifications` via `adb cmd statusbar`) |
| 15 | Vector store layers (b)+(c) — UI knowledge + recovery | Pending | |
| 16 | Perception compression steps 4–5 (compact format, inspect tool) | Pending | |
| 17 | Web UI v2.4 — cost dashboard | Pending | |
| 18 | Flow runtime — FlowStore, selector helpers, execute_flow, core flows | Pending | |
| 19 | Flow miner — repeated-subsequence detection, candidate generation | Pending | |
| 20 | Settings UI Flows panel — review, promote, auto-disable | Pending | |
| 21 | Device seam — RemoteDevice + adb-proxy | Pending (deferred) | Only needed when agent runs off-host |

---

## What shipped outside the v2 milestone sequence

A few items landed ahead of their dependency order:

- **Notification-shade tools** (milestone 14) shipped at `587107e` before the provider, policy, storage, and web UI milestones. The tools use a simple `adb shell cmd statusbar` call and have no dependency on the later seams.
- **Viewport filter** (part of milestone 11, step 2) shipped at `6e81c6b` alongside the v1 polish work, before the formal milestone ordering placed it at #11. The `perception.viewport_filter` config flag is live.

---

## Current focus

Milestones 1–5 are complete. The "v2 minimum" block is shipped. Milestone 6 (perception compression step 1 — sibling collapse) is the next planned item.
