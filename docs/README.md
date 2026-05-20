# AndroidHarness — documentation index

AndroidHarness is a Python tool that gives a Gemini LLM a real Android phone and a natural-language task, then lets it work the task to completion by reading the device UI tree and issuing actions over ADB.

One command, one task, one device:

```bash
export GOOGLE_API_KEY=...
uv run androidharness run "Open Settings and toggle Wi-Fi off"
```

The agent reads the UI, calls tools (`tap`, `swipe`, `type`, …), observes results, and calls `done()` when finished or stuck. Every step is written to `./runs/<id>/` for later inspection.

## Table of contents

| Doc | What it covers |
|-----|---------------|
| [getting-started.md](getting-started.md) | Prerequisites, install, first run, troubleshooting |
| [architecture.md](architecture.md) | Module-by-module walkthrough |
| [configuration.md](configuration.md) | `~/.androidharness/config.yaml` schema and the `config` subcommand |
| [tools.md](tools.md) | The agent's full tool vocabulary |
| [run-artifacts.md](run-artifacts.md) | `meta.json` / `turns.jsonl` / `result.json` schema with a real example |
| [development.md](development.md) | Tests, lint, adding a new tool, FakeDevice/FakeGeminiClient fixtures |
| [roadmap.md](roadmap.md) | v2 milestone status — what's shipped, what's pending |

Design specs live in `docs/superpowers/specs/` and are not modified by this index.
