# AndroidHarness v2 — Stack & Scale Design

**Date:** 2026-05-20
**Status:** Approved (brainstorming phase)
**Predecessor:** [2026-05-19-android-ai-harness-design.md](2026-05-19-android-ai-harness-design.md)

---

## 1. Goals

Evolve the v1 MVP (single host, single device, single provider, CLI only) into a personal multi-device platform without abandoning what works. Concretely:

- Run the same agent loop against multiple LLM providers, with rate-limit-aware routing.
- Gate destructive tools behind a policy so the harness is safe to point at the user's personal phone.
- Persist runs in a queryable store and watch them live in a browser.
- Give the agent retrieval-augmented memory of its own past work.
- Compress the UI-tree observation so context spend grows sub-linearly with screen complexity.

**Non-goals** for v2: multi-tenant auth, container orchestration, distributed control plane, replacing the agent loop with a framework (LangGraph et al.), benchmark/eval mode.

## 2. Architecture — the seam model

The v1 agent loop (`androidharness/agent.py`) is preserved. Every new capability lives behind a Protocol so it can be swapped without touching the loop.

```
CLI ──┐
Web UI (FastAPI + HTMX) ──┤
                          ├─► Agent core (v1, unchanged)
                          │     ├─► LLMClient → LiteLLMClient + Throttler  (provider seam)
                          │     ├─► Device / RemoteDevice                   (device seam)
                          │     ├─► Policy gate                             (permission seam)
                          │     ├─► RunSink → FileSink + SQLiteSink         (storage seam)
                          │     └─► OTel spans                              (telemetry)
                          │
                          └─► EpisodicMemory (chromadb) — recall_similar_runs tool
```

Each seam is one small module + one Protocol. The agent constructor takes them as dependencies (already the v1 pattern for `device` and `client`).

## 3. Provider seam — LiteLLM + Throttler

**Why LiteLLM, not LangGraph:** they solve different problems. LiteLLM is a provider gateway (Gemini, Claude, OpenAI, local — one OpenAI-shaped API). LangGraph is an agent framework that would replace our loop. The loop is small, well-understood, and tested — keep it. The provider client is the layer we want to abstract.

**Components:**
- `LiteLLMClient` implementing the existing `GeminiClient` Protocol (rename to `LLMClient`). Returns the same `{"name", "args"}` shape the agent expects.
- `Throttler` wrapper that maintains a token-bucket per `(provider, model)` key. On 429 or quota-style error, blocks until the bucket refills, then retries via LiteLLM's `Router` fallback list.
- Config in `pyproject.toml` extras and an `androidharness.yaml` file: ordered fallback list per logical model name (`fast` → `gemini-2.5-flash` → `claude-haiku-4-5` → `gpt-4o-mini`).
- Cost ledger: LiteLLM emits per-call cost; we sum into the run's SQLite row.

**What changes in v1 code:** `GoogleGenaiClient` becomes one implementation of `LLMClient`. `LiteLLMClient` becomes the default. Agent code is untouched.

## 4. Policy seam — destructive-action gating

A `Policy` object the agent consults before dispatching tools. Per-tool mode: `auto` | `confirm` | `dry-run` | `deny`.

**Default policy on personal devices:**
- `auto`: `tap`, `swipe`, `scroll`, `show_screen`, `wait`, `press_key`
- `confirm`: `type` (typing into payment / messaging fields is destructive enough), `long_press`
- `deny`: anything new added later that touches package install / system settings — explicit allow required

`confirm` mode emits a prompt to the CLI / Web UI and blocks until the user approves or rejects. Rejections come back to the model as a `tool_result` with `ok=False, message="user rejected: ..."` so the agent can react.

**Config:** YAML file, plus a `--policy` CLI flag for ad-hoc override. Web UI shows current policy and lets the user toggle modes per session.

## 5. Storage seam — SQLite + files

`RunSink` Protocol. Default v1 behavior (write `meta.json`, `turns.jsonl`, `result.json`, `screenshots/`) stays in a `FileSink`. New `SQLiteSink` writes the same data to a single `runs.db` for queryability. Both sinks run in parallel by default.

**Schema sketch:**
```
runs(id, started_at, ended_at, device_serial, model, task, status, success, reason, turns, cost_usd, run_dir)
turn_events(run_id, turn_idx, ts, tool_name, tool_args_json, observation_summary, ok, message)
screenshots(run_id, turn_idx, path)  # path on disk, blobs stay as files
```

Screenshots stay as files on disk (binary blobs in SQLite are wasteful) — the table just indexes them.

**Migrations:** alembic. Bootstraps on `androidharness migrate`.

**Backfill of existing runs:** the `runs/` tree from v1 contains real run data we want queryable from day one. `androidharness index runs [--runs-dir ./runs]` scans every `<run_dir>/meta.json` + `turns.jsonl` + `result.json` and writes them into SQLite. Idempotent: skips runs whose `id` is already present, so it's safe to re-run. Same command also lives as a step inside `androidharness migrate` for first-time setup.

## 6. Telemetry — OpenTelemetry spans

Wrap the agent loop and each tool dispatch in OTel spans. Default exporter writes to a local JSON file (no infra). Optional `LANGFUSE_API_KEY` env var swaps to a Langfuse exporter for LLM-aware tracing (cost, prompt diffs, latency percentiles). Stays optional — no Langfuse dependency in the default install.

## 7. Perception compression — sequenced

Five techniques, shipped one at a time so we can measure token impact per step:

1. **Sibling run-length collapse.** Detect N≥3 consecutive siblings with same `class` + same `resource-id` (or both empty) + no distinguishing `text`. Render as one row: `[12] ImageView × 60 (notification icons, com.nextcloud)`. Tap still works on id 12 (resolves to first of the group).
2. **Viewport filter.** Drop nodes with `bounds=[0,0][0,0]`, `visibility="gone"`, or fully outside the screen rect. Optional `--include-offscreen` for debugging.
3. **Resource-id in render.** Add the last segment of `resource-id` to the rendered row when present (e.g. `Button "Settings" #settings_row`). Often lets the model use shorter, more stable handles.
4. **Compact render format.** Benchmark TOON/YAML-columnar vs current prose-y format. Ship only if (a) token count drops ≥20% on real screens **and** (b) tool-call accuracy doesn't regress on the existing test set.
5. **Two-tier rendering + `inspect(id)` tool.** Default render strips content-desc, package, full bounds. Model can call `inspect(id)` to get the verbose row for one node.

Ship in this order. Each step lands with a before/after token measurement on three reference screens (settings list, app drawer, notification shade once shade tool exists).

## 8. Vector store — episodic memory (chromadb)

User wants all three use cases: cross-run episodic, per-app UI knowledge, error-recovery library. Ship as three concentric layers, same store.

**Storage:** chromadb, embedded, file-backed at `~/.androidharness/memory.db`. Zero ops, sufficient for single-user. Switching to Qdrant later is a one-collection-export migration.

**Indexing job:** runs after each task. Reads the just-finished run, embeds:

For the existing `runs/` tree (and any future bulk re-index), `androidharness index memory [--runs-dir ./runs]` walks every completed run and embeds it. Idempotent on `(run_id, layer)` pairs so re-running is safe and cheap.

Per-run flow embeds:
- `(task_text)` → run summary doc (use case (a): episodic recall)
- `(app_package, screen_signature)` → known-good action trajectories (use case (b): UI knowledge)
- `(NO_PROGRESS warning + recovery action)` → escape recipes (use case (c): error library)

**Embedding model:** Gemini's `text-embedding-004` (free tier, already have the API key) or a local sentence-transformer if user prefers offline. Configurable.

**Retrieval as tools:**
- `recall_similar_runs(task)` → top-3 past tasks with their final outcome and ≤5 key turns each.
- `recall_app_knowledge(package_name)` → known patterns for this app.
- `recall_recovery(stuck_pattern)` → past escapes from the same NO_PROGRESS signature.

Agent calls these explicitly — no automatic injection. Keeps the context window controllable.

**Risk:** retrieved trajectories drift as apps update. Mitigation: each stored memory has a `last_validated_at`; retrieval prefers recent. Memories older than 60 days are deprioritized.

## 9. Web UI — FastAPI + HTMX

Start as the **configuration surface** for the seams (LiteLLM, throttler, policy, memory, perception). CLI is retained — both read/write the same Pydantic-validated config file at `~/.androidharness/config.yaml`. Monitoring grows on top later.

**v2.0 — Settings UI:**
- **Providers panel** — list of LLM providers; API key entry; enable/disable; drag-and-drop fallback order.
- **Models panel** — logical model names (`fast`, `smart`, `cheap`) mapped to provider/model pairs; per-1M-token cost displayed from LiteLLM's price table.
- **Throttler panel** — per-(provider, model) RPM / TPM / daily $ cap inputs.
- **Policy panel** — per-tool mode dropdown (`auto` / `confirm` / `dry-run` / `deny`); session-only override toggle.
- **Memory panel** — embedding model selector (Gemini `text-embedding-004` / local `all-MiniLM-L6-v2`); enable toggle per layer (episodic / app-knowledge / recovery); retention days.
- **Perception panel** — per-compression-step toggle (sibling collapse, viewport filter, resource-id in render, etc.) so steps can be A/B'd against token spend.
- **Devices panel** — live `adb devices` output with friendly labels; pick a default.
- **Logs panel** — level, rotation size, file path.
- All forms POST to a `PATCH /config` endpoint that validates against the Pydantic schema before writing. Invalid configs reject with the field error inline.
- Auth: none. Bind to `127.0.0.1` only.

**v2.1 — Live monitoring:**
- Active and recent runs list. Click → live view: current observation, last screenshot, tool call timeline, elapsed, token + cost counters. SSE stream per run.

**v2.2 — Replay:**
- Open any past run, scrub turns like a debugger. Foundation for later eval/regression work.

**v2.3 — Launcher:**
- Dropdown of `list_devices()` + task input. Submits to `POST /runs` that spawns the agent as a background task. CLI works in parallel.

**v2.4 — Cost dashboard:**
- Rolling spend per provider/model/day, throttler state, per-run cost breakdown.

**Stack:** FastAPI, Jinja2 templates, HTMX, SSE for streams, vanilla CSS. Screenshots rendered via `<img src="/runs/<id>/screenshots/<turn>.png">`. No React. No build step.

**Packaging:** ships in the main package with an optional `[web]` extra (FastAPI + Jinja2 + Pydantic only pulled in if installed). New CLI command `androidharness serve --port 8000`.

**CLI / UI parity:** CLI flags (`--policy`, `--model`, `--throttle-rpm`, …) override the config file for that single run. The config file is the persisted source of truth; the UI is one of two equally valid ways to edit it.

## 10. Device seam — RemoteDevice (deferred trigger)

Not required for v2 launch, but spec it so the boundary is clean:

- `RemoteDevice` implements the existing `Device` Protocol but proxies every call to an `adb-proxy` HTTP service running on the host with USB phones.
- `adb-proxy` is a thin FastAPI service wrapping a local `UIAutomatorDevice` and exposing the same Protocol over HTTP.
- Build this only when the user actually wants to run the agent on a different machine than the phone. Until then, the Protocol is enough.

## 11. Long-term roadmap

Ordered by dependency, not by hype:

| # | Milestone | Unlocks |
|---|-----------|---------|
| 1 | **Config schema** — Pydantic `AndroidHarnessConfig` + YAML load/save + CLI integration | foundation for every seam below |
| 2 | Provider seam — LiteLLM + `LLMClient` refactor, reads config | multi-model |
| 3 | Throttler — token-bucket + LiteLLM Router fallback, reads config | rate-limit survival |
| 4 | Policy seam — gates on `type`, `long_press`, reads config | safe on personal device |
| 5 | **Web UI v2.0 — Settings UI** (the knob) | edit all of (1)–(4) without YAML |
| 6 | Perception compression step 1 — sibling collapse | immediate token win |
| 7 | Storage seam — `SQLiteSink` + alembic migrations | queryable history |
| 8 | Web UI v2.1 — live monitoring (depends on 7) | watch runs live |
| 9 | OTel spans + JSON exporter | observability foundation |
| 10 | Web UI v2.2 — replay | review past runs |
| 11 | Perception compression steps 2–3 (viewport, resource-id) | further token wins |
| 12 | Vector store layer (a) — `recall_similar_runs` | episodic memory |
| 13 | Web UI v2.3 — launcher | run from browser |
| 14 | Notification-shade tool pair (already specced in memory) | reach the shade |
| 15 | Vector store layers (b) + (c) | UI knowledge + recovery |
| 16 | Perception compression steps 4–5 (compact format, inspect) | depends on (11) benchmarks |
| 17 | Web UI v2.4 — cost dashboard | full self-service |
| 18 | Device seam — `RemoteDevice` + `adb-proxy` | agent off-host (only if needed) |

Each milestone is small enough to land in one focused session. **Items 1–5 are the "v2 minimum"** — after those, the harness is multi-provider, gated, and configurable through a browser. Items 6+ are the long tail.

**Sequencing note:** Config schema (1) is the new prerequisite — provider, throttler, and policy all read from it, and the Settings UI is its editor. Building (1) first means (2)–(5) just plug into a stable shape instead of churning their interfaces as we go.

## 12. What this design does NOT do

- Replace the agent loop. We keep `agent.py` as-is and let it grow only when the loop itself becomes the bottleneck (e.g. multi-agent planner/executor split).
- Add benchmarks or eval mode. Replay (milestone 8) is the first step toward that, but the eval harness itself is a separate v3 spec.
- Auth, multi-tenant, or any networked control plane. v2 stays single-user, localhost-bound.
- Containerization. Everything runs in the user's `uv`-managed venv.
- TOON or alternative formats — only adopted if step 7 benchmark proves the win.

## 13. Open questions to revisit during implementation

- **Embedding cost vs. local model.** Gemini `text-embedding-004` is free now but quota'd. Decide in milestone 10 whether to default to local `sentence-transformers/all-MiniLM-L6-v2`.
- **Policy default for `swipe`.** Currently `auto`. A swipe on a banking app's confirm screen is destructive. Revisit after we see real failure modes.
- **SQLite concurrency.** Single-writer is fine for personal use; if Web UI ever spawns concurrent runs, switch to WAL mode (one-line change).
