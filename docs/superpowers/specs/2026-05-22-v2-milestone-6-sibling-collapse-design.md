# v2 Milestone 6 — Perception sibling-collapse design

**Status:** spec, ready to plan.
**Date:** 2026-05-22.
**Parent spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §7 step 1.

## Goal

Collapse runs of N≥3 consecutive nodes with the same `class_name` + same `resource_id` (both possibly empty) and no distinguishing `text` / `content_desc` into a single rendered row of the form `[id] ClassName × N`. The agent sees one line instead of 60 — a substantial token win on notification shades, app drawers, contact lists, and any other large homogeneous list.

The collapse is **rendering-only**. The `Observation` stays canonical so `peek`, screenshots, and any other inspectors keep seeing the full tree. Tap dispatch is unaffected — the rendered id (the first node of the run) resolves to a valid `Node` in the Observation; tapping any non-rendered id from the run also works (same bounds, same effect).

## Non-goals

- Tree-level sibling detection (parent/depth tracking). The spec defines a run as "consecutive in the flat node list with matching attributes" — that suffices for the common case (homogeneous list rendered as a flat child sequence by the layout engine) and avoids changing `Node`'s shape.
- Cross-class merging (e.g. `ImageView` + `TextView` rows of an item). That's a richer transformation; not in M6.
- Renumbering. Hidden nodes 13..N stay valid in the Observation; they just don't appear in the rendered text. The model uses the visible id (12) by convention.
- A new renderer subclass. The collapse is a feature flag on `ProseRenderer.observation`, gated by an existing `PerceptionConfig.sibling_collapse` field.

## Definition of a run

A list of ≥3 consecutive `Node` entries in `Observation.nodes` qualifies as a collapsible run iff **every** node in the run satisfies:

1. Same `class_name` as the first node.
2. Same `resource_id` as the first node (both may be empty).
3. `text` is empty.
4. `content_desc` is empty.

If any one of those four conditions fails for any node, the run is shorter or doesn't exist.

The check does NOT consider:
- Bounds (the model rarely cares; rows of icons typically have varying y).
- Trait flags (`clickable`, `enabled`, …). Runs with mixed states fall through to per-node rendering anyway because the visible label is empty, and a clickable/unclickable mix is rare for visually-identical siblings — but for safety, runs ignore trait differences.
- Resource-id segment short form (which exists in render). Two nodes with `resource_id="com.x:id/foo"` and `resource_id="com.y:id/foo"` are NOT in the same run; the full resource-id string must match.

Empty text + empty content_desc is the spec's "no distinguishing text" guard. If the run had labels, collapsing would lose information the model might need.

## Rendered output

For a run of N≥3 starting at the node currently rendered `[id] ClassName` (with optional `#resource_id_short`):

```
[id] ClassName × N
```

When `with_resource_id=True` and the run shares a non-empty `resource_id`:

```
[id] ClassName × N #resource_id_short
```

Examples:

- `[12] ImageView × 60`
- `[34] FrameLayout × 8 #notification_item`

The example from the parent spec includes a parenthesized annotation (`(notification icons, com.nextcloud)`). That requires data the current `Node` doesn't carry (package, ancestor content-desc) and would need a separate perception step. **Out of scope for M6.** Keep the line tight.

## Pipeline placement

`ProseRenderer.observation(obs, *, with_resource_id, sibling_collapse)` gains a third keyword. When `True`, the renderer walks `obs.nodes` and emits one line per run-or-single-node. The per-node loop becomes:

```
i = 0
while i < len(nodes):
    run = scan_run(nodes, i)
    if run.length >= 3:
        emit collapsed line for nodes[i]
        i += run.length
    else:
        emit normal line for nodes[i]
        i += 1
```

Pure function over `Observation`. No I/O, no parse-time changes, no `Node` schema changes.

## Plumbing the flag

`PerceptionConfig.sibling_collapse: bool = False` already exists in `config.py`. M6 wires it through to the renderer:

1. `Renderer.observation` Protocol gains `sibling_collapse: bool = False` keyword.
2. `ProseRenderer.observation` implements the logic above.
3. `Observation.render` (`perception.py:66-69`) gains a matching `sibling_collapse: bool = False` keyword and passes it through to the renderer.
4. `Node.format` / `Observation.summary` are unchanged (per-node rendering, not affected).
5. `Agent` reads `cfg.perception.sibling_collapse` at construction and passes it on every render call. (Mirror of how `with_resource_ids` is plumbed today.)
6. `cli.py peek` gains a `--sibling-collapse / --no-sibling-collapse` flag (mirror of `--viewport-filter`) so the user can A/B the effect on the connected device.

## Testing strategy

| Test | What it asserts |
|---|---|
| `tests/test_render.py::test_sibling_collapse_run_of_three_emits_single_line` | 3 ImageView nodes with same empty resource-id collapse to `[0] ImageView × 3`. |
| `…::test_sibling_collapse_run_below_threshold_renders_each_node` | 2 matching nodes are NOT collapsed (N must be ≥3). |
| `…::test_sibling_collapse_disabled_renders_each_node` | With flag off, the same input renders one line per node. |
| `…::test_sibling_collapse_mixed_class_breaks_run` | ImageView, ImageView, TextView, ImageView, ImageView, ImageView → first two render normally (run of 2), TextView normal, last three collapse to `× 3`. |
| `…::test_sibling_collapse_text_breaks_run` | Three ImageViews where the middle one has `text="X"` → three normal lines (no run formed). |
| `…::test_sibling_collapse_resource_id_in_collapsed_line` | With `with_resource_id=True` and a shared `resource_id`, the collapsed line carries `#id_short`. |
| `…::test_sibling_collapse_run_at_end_of_list` | Run that ends at the last node still collapses correctly (no off-by-one). |
| `tests/test_perception.py::test_observation_render_threads_sibling_collapse` | `Observation.render(sibling_collapse=True)` produces collapsed output. |
| `tests/test_cli_peek.py::test_peek_sibling_collapse_flag_overrides_config` | `androidharness peek --sibling-collapse` collapses even when config flag is off; `--no-sibling-collapse` does the opposite. |
| `tests/test_agent.py::test_agent_passes_sibling_collapse_to_renderer` | When `cfg.perception.sibling_collapse=True`, the rendered observation the agent emits is collapsed. |

No XML-fixture changes needed — tests construct `Observation(nodes=[Node(...), ...])` directly with the precise shapes they want to probe.

## Token-impact measurement

The parent spec asks for a before/after token count on three reference screens. M6 lands the measurement script as a small dev tool (`scripts/measure_perception.py`, not part of the package) that:

1. Reads an XML fixture from `tests/fixtures/`.
2. Parses via `parse_hierarchy(xml, viewport_filter=True)`.
3. Renders with and without each compression flag.
4. Prints character counts and a rough token estimate (`len // 4`).

The three reference screens are added as XML fixtures (`tests/fixtures/screens/settings_list.xml`, `…/app_drawer.xml`, `…/notification_shade.xml`). These are captured from a real device via `adb shell uiautomator dump` and committed verbatim. The script is run manually and the output recorded in this spec file under a "Measurements" section below before the milestone is marked Shipped.

The measurement script itself has no tests; it's a one-off operational tool.

## Files touched

**Modified:**
- `androidharness/render.py` — `Renderer` Protocol gains `sibling_collapse: bool = False`; `ProseRenderer.observation` implements collapse.
- `androidharness/perception.py` — `Observation.render` accepts `sibling_collapse: bool = False` keyword and passes it through.
- `androidharness/agent.py` — read `cfg.perception.sibling_collapse` at construction; pass to every render call alongside `with_resource_ids`.
- `androidharness/cli.py` — `peek` command gains `--sibling-collapse / --no-sibling-collapse` flag.
- `tests/test_render.py` — 7 new tests for the collapse logic.
- `tests/test_perception.py` — 1 new test for the threading.
- `tests/test_cli_peek.py` — 1 new test for the override flag.
- `tests/test_agent.py` — 1 new test that the flag reaches the renderer.

**New:**
- `tests/fixtures/screens/settings_list.xml`
- `tests/fixtures/screens/app_drawer.xml`
- `tests/fixtures/screens/notification_shade.xml`
- `scripts/measure_perception.py` (not packaged; manual dev tool).

**Untouched:** `config.py` (the flag already exists), `tools.py`, `policy.py`, `device.py`, `runner.py`, `llm.py`, the `web/` subpackage.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Two adjacent unrelated views (e.g. two ImageButtons one above another in a header) get collapsed. | The empty-text + empty-content-desc guard catches almost all of these — a header ImageButton always has a content-desc for accessibility. The N≥3 threshold further reduces false positives. |
| The model gets confused by `× N` syntax. | Acceptance ride-along: the agent tests include a render fixture so we can see what the model sees. If a real run misfires we can A/B with `--no-sibling-collapse`. |
| Off-by-one when the run is at the end of `obs.nodes`. | Covered by `test_sibling_collapse_run_at_end_of_list`. |
| Devices panel / Replay / future UI features that render Observations get unexpected collapse. | The flag defaults to `False` and is per-call. Only the agent loop opts in. The `peek` CLI and Web UI render with the flag value the user sets. |

## Sequencing inside the milestone

1. Add `sibling_collapse` keyword to `Renderer.observation` and `Observation.render`; default `False`; existing tests keep passing.
2. Implement `ProseRenderer.observation` collapse logic.
3. Add the 7 `test_render.py` tests + the threading test in `test_perception.py`.
4. Wire `peek` flag + test.
5. Wire `Agent` to read the config flag + test.
6. Add three reference XML fixtures.
7. Land `scripts/measure_perception.py` and run it; record the numbers in this spec's "Measurements" section.
8. Docs: `architecture.md` (one line about sibling collapse), `configuration.md` (note the flag is now functional).

## Measurements

_To be filled in before the milestone is marked Shipped._
