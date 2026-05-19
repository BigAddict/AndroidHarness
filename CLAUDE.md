# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repo was just initialized — `main.py` is a stub, `README.md` is empty, and no application code, tests, or package layout exists yet. Treat any architectural decision (module structure, entry points, test framework) as open until the user weighs in.

## Tooling

- Package/dependency manager: **uv** (project metadata lives in `pyproject.toml`, lockfile is `uv.lock`).
- Python: pinned to **3.11** via `.python-version`.
- Dependencies declared so far: `uiautomator2` and `uiautodev` — i.e. the project targets **Android UI automation over ADB** (uiautomator2 drives a real device/emulator; uiautodev is the inspector/web UI). Any feature work should assume an ADB-connected device is in the loop.

## Commands

```bash
uv sync                  # install/refresh deps into .venv
uv run python main.py    # run the entry point
uv add <pkg>             # add a runtime dep (updates pyproject + uv.lock)
uv add --dev <pkg>       # add a dev dep
uv lock                  # refresh lockfile without installing
```

No test runner, linter, or formatter is configured yet — don't invent commands. If the user asks for tests/lint, ask which tool to wire up (pytest, ruff, etc.) before adding configuration.
