# v2 Milestone 22 — Perception foreground-package signal design

**Status:** spec, ready to plan.
**Date:** 2026-05-23.
**Parent spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §7. Picks up the package-annotation thread that M6's spec explicitly punted (the `(notification icons, com.nextcloud)` example in the parent §7.1).

## Goal

Surface the foreground window's Android package name to the model as a single header line at the top of every rendered Observation:

```
# foreground: com.binance.dev
[1] FrameLayout (clickable)
[2] TextView "Sell" (clickable)
...
```

The model gains a stable, low-bandwidth signal for "what app am I currently in" that survives integer-id resets across turns, lets it recognize when it has bounced out of the target app, and grounds `done(success=False, "X not on this device")` give-up decisions. This was the missing signal in the 40-turn Binance failure: the agent opened Binance on turn 9, pressed home on turn 10, and had no perception-level memory that it had ever been in Binance.

The signal is render-time only and gated by a new `perception.foreground_package: bool = False` config flag (default off, matching every other perception lever). `Observation` grows by one string field; `Node` is unchanged.

## Non-goals

- **Per-node package annotation** (the parent §7.1 `(com.nextcloud)` example). Annotating every rendered line with its package would also disambiguate popups, system overlays, and embedded WebViews — but it bloats every row by 20–40 chars on the common case where every node shares the foreground package. Out of scope here; can layer on later if foreground-only proves insufficient.
- **Memory / vector-store integration.** v2 spec §8 envisages `(app_package, screen_signature) → trajectories` retrieval. The foreground signal is a *display* feature; downstream features that *key on* it land separately.
- **Multi-window / split-screen disambiguation.** We define the foreground as the package of the topmost `<node>` child of `<hierarchy>` — UIAutomator's first-window-is-focused convention. Split-screen surfaces only the focused half. Acceptable for v1.
- **A new renderer subclass.** Same shape as M6: a flag on `ProseRenderer.observation`, gated by `PerceptionConfig.foreground_package`.
- **System-prompt teaching.** The header is self-explanatory (`# foreground: <pkg>`). No SYSTEM_PROMPT changes ship in this milestone — let the model pick the signal up on its own first. If a real run shows it's not being used, a follow-up prompt nudge is a one-line edit.

## Definition of "foreground package"

The value of the `package` attribute on the **first direct-child `<node>` of `<hierarchy>`** in the UIAutomator XML dump. This is the topmost window — UIAutomator orders windows by z-order with the focused window first.

The value is **empty** when:
- `<hierarchy>` has no `<node>` children (degenerate dump).
- The topmost `<node>` lacks a `package` attribute (unusual but possible on hand-crafted fixtures).

In both empty cases the header line is omitted entirely (no `# foreground: ` with a trailing-empty value).

## Rendered output

When `foreground_package=True` AND `obs.foreground_package` is non-empty:

```
# foreground: com.binance.dev
[1] FrameLayout (clickable)
[2] TextView "Sell" (clickable)
```

When the flag is `False` (default) OR `obs.foreground_package == ""`, the output is **byte-identical** to today's behavior (no header, no extra leading newline).

The `# ` prefix mirrors shell-comment / markdown-quote idioms — humans skim past, LLMs treat as metadata. Tests pin the exact `# foreground: <pkg>\n` format so a future renderer change (e.g. a TOON port) re-derives the same string.

## Pipeline placement

```
parse_hierarchy(xml)
  → Observation(nodes=[...], foreground_package="com.binance.dev")

DEFAULT_RENDERER.observation(obs, foreground_package=True)
  → "# foreground: com.binance.dev\n[1] FrameLayout ...\n[2] ..."
```

Three places change inside perception/render:

1. **`parse_hierarchy`** — reads `hierarchy/node[1]/@package` once and stores it on the new `Observation.foreground_package` field. Node walking and node emission are untouched.
2. **`Renderer.observation` Protocol** — gains `foreground_package: bool = False`.
3. **`ProseRenderer.observation`** — when the flag is True and the field is non-empty, prepend `"# foreground: " + obs.foreground_package + "\n"` to the existing rendered body. The rest of the algorithm (per-node format, sibling-collapse runs) is unchanged.

`Node` is unchanged — no new field, no signature change on `Node.format()`.

## Plumbing the flag

Mirror of the M6 sibling-collapse plumbing chain, end-to-end:

1. **`PerceptionConfig`** — gain `foreground_package: bool = False`. Adds an `extra="forbid"`-compatible field; no migration needed (existing YAML files still parse — the field defaults).
2. **`Renderer.observation` Protocol + `ProseRenderer.observation`** — accept and implement.
3. **`Observation.render`** — accept and thread to the renderer.
4. **`Agent`** — read `cfg.perception.foreground_package` at construction; pass to every `obs.render(...)` call alongside `with_resource_ids` and `sibling_collapse`. Three callsites in `Agent.run` (observation payload, stall detector, turn log). All three must match — the stall-detector invariant from M6 carries over: comparing strings rendered with different flags breaks no-progress detection.
5. **`runner.run_task`** — accept `foreground_package: bool = False` and forward to `Agent`.
6. **`cli.py run_cmd`** — pass `foreground_package=cfg.perception.foreground_package`.
7. **`cli.py peek_cmd`** — gain `--foreground-package / --no-foreground-package` for one-off A/B against a live device (mirror of `--sibling-collapse`).

The Settings UI does not currently expose perception flags (no `_perception.html` panel exists in `androidharness/web/templates/`). No UI work in this milestone — users edit `~/.androidharness/config.yaml` directly or call `androidharness config show` to inspect.

## Testing strategy

| Test | What it asserts |
|---|---|
| `tests/test_perception.py::test_parse_hierarchy_extracts_foreground_package` | Topmost `<node package="X">` populates `obs.foreground_package`. |
| `tests/test_perception.py::test_parse_hierarchy_foreground_package_empty_when_hierarchy_empty` | XML with `<hierarchy></hierarchy>` (no node children) yields `foreground_package=""`. |
| `tests/test_perception.py::test_parse_hierarchy_foreground_package_empty_when_attr_missing` | Topmost `<node>` lacks `package=` attribute → `""`. |
| `tests/test_render.py::test_foreground_package_header_prepends_when_enabled` | Flag True + non-empty foreground → first line is `# foreground: com.x`. |
| `tests/test_render.py::test_foreground_package_header_omitted_when_disabled` | Flag False (default) → no header; existing render unchanged. |
| `tests/test_render.py::test_foreground_package_header_omitted_when_field_empty` | Flag True but `foreground_package=""` → no header line (no stray `# foreground: \n`). |
| `tests/test_render.py::test_foreground_package_combines_with_sibling_collapse` | Flag True + `sibling_collapse=True` → header followed by collapsed body. |
| `tests/test_perception.py::test_observation_render_threads_foreground_package` | `Observation.render(foreground_package=True)` produces the header. |
| `tests/test_config.py::test_perception_config_foreground_package_default_false` | `PerceptionConfig().foreground_package is False`. (Augment whichever existing perception-config test covers defaults — minimal addition.) |
| `tests/test_agent.py::test_agent_passes_foreground_package_to_renderer` | When `cfg.perception.foreground_package=True`, the observation text the agent sends starts with `# foreground:`. |
| `tests/test_cli_peek.py::test_peek_foreground_package_flag_overrides_config` | `peek --foreground-package` adds the header even when config has it off. |
| `tests/test_cli_peek.py::test_peek_no_foreground_package_flag_overrides_config` | `peek --no-foreground-package` suppresses the header even when config has it on. |

No XML-fixture changes for the unit tests — they construct `Observation(nodes=[...], foreground_package="...")` directly with the precise shapes they probe.

## Validation on real screens

The M6 measurement script (`scripts/measure_perception.py`) already loads the three captured fixtures. Extend it to print `obs.foreground_package` for each. Expected values (predictions to be confirmed):

- `settings_list.xml` → `com.android.settings`
- `app_drawer.xml` → likely `com.sec.android.app.launcher` (Samsung One UI) or similar
- `notification_shade.xml` → `com.android.systemui`

Recorded in the Measurements section below before the milestone ships.

## Files touched

**Modified:**
- `androidharness/config.py` — `PerceptionConfig` gains `foreground_package: bool = False`.
- `androidharness/perception.py` — `Observation` gains `foreground_package: str = ""`; `Observation.render` accepts the flag; `parse_hierarchy` populates the field.
- `androidharness/render.py` — `Renderer.observation` Protocol + `ProseRenderer.observation` accept `foreground_package`; prepend header when True + non-empty.
- `androidharness/agent.py` — `Agent.foreground_package: bool = False`; threaded into all three `obs.render(...)` callsites.
- `androidharness/runner.py` — `run_task` accepts `foreground_package` and forwards to `Agent`.
- `androidharness/cli.py` — `run_cmd` passes `cfg.perception.foreground_package`; `peek_cmd` gains the override flag.
- `tests/test_perception.py` — 4 new tests (3 parse + 1 threading).
- `tests/test_render.py` — 4 new tests.
- `tests/test_config.py` — 1 small assertion added on default.
- `tests/test_agent.py` — 1 new test.
- `tests/test_cli_peek.py` — 2 new tests.
- `scripts/measure_perception.py` — one extra print line per fixture.

**Untouched:** `tools.py`, `policy.py`, `device.py`, `llm.py`, `imaging.py`, `logging_setup.py`, the `web/` subpackage.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Topmost `<node>` isn't always the focused window (system overlays, transient popups). | Acceptable v1 — UIAutomator's first-child-is-focused convention is correct on virtually every screen. Edge cases addressed by a future per-node package annotation. |
| Header bytes break the M6 stall-detector invariant. | All three `obs.render(...)` callsites pass the same `foreground_package` value, just like `sibling_collapse`. Both the model and the detector see the same string. |
| `# foreground: …` prefix syntax confuses some models. | Ride-along: rerun the Binance task with the flag on, watch whether the model uses the signal. Per-call escape is `peek --no-foreground-package` or flipping the YAML. |
| Existing tests that construct `Observation(nodes=[...])` directly break. | The new field defaults to `""` — existing construction stays valid. Full suite must remain green at every task boundary. |
| Settings UI doesn't show the new flag. | No Perception panel exists today; out of scope for this milestone. A future UI milestone can expose the whole `cfg.perception` block. |

## Sequencing inside the milestone

1. `Observation.foreground_package` field + `parse_hierarchy` extraction + 3 perception tests.
2. `PerceptionConfig.foreground_package` config field + default-coverage assertion.
3. `Renderer.observation` Protocol + `ProseRenderer.observation` accept the kwarg AND implement the header logic + 4 render tests. (Logic is 3–4 lines, no need to split no-op + logic into two tasks as M6 did.)
4. Thread through `Observation.render` + 1 threading test.
5. Plumb through `Agent` (new field + 3 callsites) + 1 agent test.
6. Plumb through `runner.run_task` + `run` CLI (no new tests; mirrors M6 Task 5).
7. `peek --foreground-package / --no-foreground-package` + 2 override tests.
8. Extend `scripts/measure_perception.py`; run it; record per-fixture foreground values in Measurements.
9. Docs pass: architecture, configuration, roadmap.

## Measurements

_To be filled in before the milestone is marked Shipped._
