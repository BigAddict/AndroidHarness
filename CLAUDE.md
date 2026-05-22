# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where to start

**For a fast orientation, read these in order:**
1. [`docs/README.md`](docs/README.md) — what AndroidHarness is, one-line install + run.
2. [`docs/roadmap.md`](docs/roadmap.md) — what's shipped, what's pending. This is the canonical "current state" tracker.
3. [`docs/superpowers/README.md`](docs/superpowers/README.md) — index into the design specs + implementation plans (the historical record of how each milestone was decomposed and shipped).
4. [`docs/architecture.md`](docs/architecture.md) — module-by-module walkthrough.

The code is the source of truth. Specs and plans under `docs/superpowers/` are design-time records and are intentionally not rewritten after a milestone ships — they document intent at planning time, not as-built state.

## What this project is

AndroidHarness gives an LLM (Gemini, Claude, GPT, anything LiteLLM-supported) a real Android phone and a natural-language task. The agent reads the UI tree via `uiautomator2`, calls tools (`tap`, `swipe`, `type`, `scroll`, `press_key`, `wait`, `show_screen`, `open_notifications`, `close_notifications`, `done`), and writes turn-by-turn artifacts to `runs/<id>/` for later inspection.

v1 baseline and v2 milestones 1–4 are shipped on `feat/v1-harness`. v2 milestone 5 (FastAPI + HTMX Settings UI) is the next planned item — see `docs/roadmap.md` for the full v2 roadmap.

## Tooling

- Package/dependency manager: **uv** (project metadata in `pyproject.toml`, lockfile `uv.lock`).
- Python: **3.11** via `.python-version`.
- Tests: **pytest** (`uv run pytest -q`).
- Lint/format: **ruff** with `E, F, I, B, UP` rules (`uv run ruff check androidharness/ tests/`).
- Entry point: `androidharness` Typer CLI (`uv run androidharness --help`).
- The agent assumes an ADB-connected device or emulator is in the loop. Many runs are exercised against the user's personal phone — the policy seam (milestone 4) exists to gate destructive tool calls.

## Commands

```bash
uv sync                                # install/refresh deps into .venv
uv run androidharness --help           # CLI entry — devices, run, config subcommands
uv run androidharness config show      # print the effective config as YAML
uv run androidharness run "<task>"     # run an agent task against an ADB device
uv run pytest -q                       # full test suite
uv run ruff check androidharness/ tests/   # lint
```

When the user asks for a change, default to TDD via the `superpowers:writing-plans` → `superpowers:subagent-driven-development` flow if it's more than a one-file edit. The four v2 milestones in `docs/superpowers/plans/` are reference templates for plan + dispatch shape.

## Conventions worth respecting

- Each seam lives in its own module: `agent.py` (the loop), `llm.py` (`LLMClient` Protocol + adapters), `policy.py` (`Policy` + `Confirmer`), `device.py` (`Device` Protocol + `UIAutomatorDevice`), `perception.py` (XML → Observation), `tools.py` (tool dispatch + Gemini-shaped declarations), `runner.py` (artifact I/O), `config.py` (Pydantic schema).
- Tests use protocols + fakes, not mocking frameworks. `tests/conftest.py` has `FakeDevice` and `FakeGeminiClient` (the latter satisfies `LLMClient` structurally; the name stuck after the milestone-2 rename).
- The agent loop binds to `LLMClient` and `Policy` abstractions — the seam is the point. Concrete clients (`LiteLLMClient`, `LiteLLMRouterClient`, `GoogleGenaiClient`) live only in `llm.py` and `cli.py`.
- Minimal comments. WHY-comments only — the file structure and naming should carry the WHAT.
- Don't modify `docs/superpowers/specs/` or `docs/superpowers/plans/` after a milestone ships. They are design-time records.
