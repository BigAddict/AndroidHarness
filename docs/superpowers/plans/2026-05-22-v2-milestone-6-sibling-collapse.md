# v2 Milestone 6 — Perception sibling-collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse runs of N≥3 consecutive nodes with the same `class_name` + `resource_id` and empty `text` / `content_desc` into a single rendered row `[id] ClassName × N`. The collapse is render-time only; `Observation` stays canonical so tap dispatch, `peek`, and screenshots are unaffected.

**Architecture:** A new `sibling_collapse: bool = False` keyword on `Renderer.observation` (Protocol), `ProseRenderer.observation` (implementation), and `Observation.render` (caller helper). `Agent` reads `cfg.perception.sibling_collapse` at construction and threads it through every render call alongside `with_resource_ids`. `runner.run_task` gains a `sibling_collapse` parameter; the `run` CLI passes the config value through. `peek` gains `--sibling-collapse / --no-sibling-collapse` to override the config flag for one-off inspection.

**Spec:** `docs/superpowers/specs/2026-05-22-v2-milestone-6-sibling-collapse-design.md`.

**Design decisions (locked in the spec):**
1. Definition of a run: ≥3 consecutive `Node` entries with identical `class_name`, identical `resource_id` (both possibly empty), empty `text`, empty `content_desc`.
2. Output format: `[id] ClassName × N`, optionally `[id] ClassName × N #rid_short` when `with_resource_id=True` and the run shares a non-empty `resource_id`.
3. No renumbering — hidden nodes 13..N stay valid in the `Observation` and a tap on any one resolves; the model uses the visible id by convention.
4. The collapse is a feature flag, not a renderer subclass — `PerceptionConfig.sibling_collapse` already exists.
5. No XML-fixture changes for the unit tests — construct `Observation(nodes=[Node(...), ...])` directly. Three reference XML fixtures land for the measurement script only.

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `androidharness/render.py` | Modify | `Renderer.observation` Protocol + `ProseRenderer.observation` gain `sibling_collapse: bool = False`. Collapse logic. |
| `androidharness/perception.py` | Modify | `Observation.render` gains `sibling_collapse: bool = False` and threads it through. |
| `androidharness/agent.py` | Modify | `Agent` gains `sibling_collapse: bool = False`; every `obs.render(...)` call passes it. |
| `androidharness/runner.py` | Modify | `run_task` gains `sibling_collapse: bool = False`; constructs `Agent` with it. |
| `androidharness/cli.py` | Modify | `run` passes `cfg.perception.sibling_collapse` through; `peek` gains `--sibling-collapse / --no-sibling-collapse` flag. |
| `tests/test_render.py` | Modify | 7 new tests for collapse logic. |
| `tests/test_perception.py` | Modify | 1 new test for `Observation.render` threading. |
| `tests/test_cli_peek.py` | Modify | 1 new test for the override flag. |
| `tests/test_agent.py` | Modify | 1 new test that the flag reaches the renderer. |
| `tests/fixtures/screens/settings_list.xml` | New | Reference XML captured from a real device — measurement input. |
| `tests/fixtures/screens/app_drawer.xml` | New | Reference XML — heavy collapse candidate. |
| `tests/fixtures/screens/notification_shade.xml` | New | Reference XML — heavy collapse candidate. |
| `scripts/measure_perception.py` | New | Manual dev tool: prints char counts and rough token estimates with/without each compression flag. Not packaged. |
| `docs/architecture.md` | Modify | One line documenting sibling collapse. |
| `docs/configuration.md` | Modify | Note that `perception.sibling_collapse` is now functional. |
| `docs/roadmap.md` | Modify | Mark M6 Shipped with the commit range. |

Untouched: `config.py` (`PerceptionConfig.sibling_collapse` already exists), `llm.py`, `policy.py`, `device.py`, `tools.py`, `imaging.py`, `logging_setup.py`, the `web/` subpackage.

---

## Task 1: Add `sibling_collapse` keyword to the Renderer Protocol and ProseRenderer (no behavior yet)

**Why first:** Keep every existing test green. The keyword defaults to `False`; nothing collapses until Task 2 adds the logic. This lets us land the seam change in isolation.

**Files:**
- Modify: `androidharness/render.py`
- Modify: `tests/test_render.py`

- [ ] **Step 1: Write a failing test that pins the new keyword on the Protocol and the default-False behavior on ProseRenderer.**

Append to `tests/test_render.py`:

```python
def test_prose_renderer_observation_accepts_sibling_collapse_keyword_default_false():
    """The keyword exists and defaults to False — calling without it must
    behave identically to calling with sibling_collapse=False."""
    r = ProseRenderer()
    obs = Observation(nodes=[
        _node(id=1, cls="android.widget.ImageView", text="", content_desc="", clickable=False),
        _node(id=2, cls="android.widget.ImageView", text="", content_desc="", clickable=False),
        _node(id=3, cls="android.widget.ImageView", text="", content_desc="", clickable=False),
    ])
    # Default and explicit-False must match.
    assert r.observation(obs) == r.observation(obs, sibling_collapse=False)
```

Run `uv run pytest -q tests/test_render.py::test_prose_renderer_observation_accepts_sibling_collapse_keyword_default_false`. The test should FAIL with a `TypeError: observation() got an unexpected keyword argument 'sibling_collapse'`.

- [ ] **Step 2: Add the keyword to both Protocol and ProseRenderer.**

In `androidharness/render.py`, edit the `Renderer` Protocol:

```python
class Renderer(Protocol):
    def node(self, n: Node, *, with_resource_id: bool = False) -> str: ...

    def observation(
        self,
        obs: Observation,
        *,
        with_resource_id: bool = False,
        sibling_collapse: bool = False,
    ) -> str: ...
```

And `ProseRenderer.observation`:

```python
def observation(
    self,
    obs: Observation,
    *,
    with_resource_id: bool = False,
    sibling_collapse: bool = False,
) -> str:
    return "\n".join(self.node(n, with_resource_id=with_resource_id) for n in obs.nodes)
```

(Body unchanged for now — the `sibling_collapse` argument is accepted but ignored. Task 2 adds the logic.)

- [ ] **Step 3: Run the test — it should now pass.**

```bash
uv run pytest -q tests/test_render.py
```

All pre-existing render tests must still pass.

- [ ] **Step 4: Run lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```bash
git add androidharness/render.py tests/test_render.py
git commit -m "feat(render): accept sibling_collapse keyword on Renderer (no-op)"
```

---

## Task 2: Implement the collapse logic in ProseRenderer.observation

**Files:**
- Modify: `androidharness/render.py`
- Modify: `tests/test_render.py`

- [ ] **Step 1: Write the seven failing tests from the spec.**

Append to `tests/test_render.py`:

```python
def _imgview(id: int, resource_id: str = "", text: str = "", content_desc: str = "") -> Node:
    return _node(
        id=id,
        cls="android.widget.ImageView",
        text=text,
        content_desc=content_desc,
        resource_id=resource_id,
        clickable=False,
    )


def test_sibling_collapse_run_of_three_emits_single_line():
    r = ProseRenderer()
    obs = Observation(nodes=[_imgview(1), _imgview(2), _imgview(3)])
    assert r.observation(obs, sibling_collapse=True) == "[1] ImageView × 3"


def test_sibling_collapse_run_below_threshold_renders_each_node():
    r = ProseRenderer()
    obs = Observation(nodes=[_imgview(1), _imgview(2)])
    rendered = r.observation(obs, sibling_collapse=True)
    assert rendered == "[1] ImageView\n[2] ImageView"


def test_sibling_collapse_disabled_renders_each_node():
    r = ProseRenderer()
    obs = Observation(nodes=[_imgview(1), _imgview(2), _imgview(3)])
    # Disabled (the default) renders each node verbatim.
    assert r.observation(obs) == "[1] ImageView\n[2] ImageView\n[3] ImageView"


def test_sibling_collapse_mixed_class_breaks_run():
    """Two ImageViews, a TextView, then three ImageViews. Only the last three
    collapse (run of 2 + singleton + run of 3)."""
    r = ProseRenderer()
    obs = Observation(nodes=[
        _imgview(1),
        _imgview(2),
        _node(id=3, cls="android.widget.TextView", text="", content_desc="", clickable=False),
        _imgview(4),
        _imgview(5),
        _imgview(6),
    ])
    rendered = r.observation(obs, sibling_collapse=True)
    assert rendered == "[1] ImageView\n[2] ImageView\n[3] TextView\n[4] ImageView × 3"


def test_sibling_collapse_text_breaks_run():
    """Middle node has text='X' — no run forms; each line renders normally."""
    r = ProseRenderer()
    obs = Observation(nodes=[
        _imgview(1),
        _imgview(2, text="X"),
        _imgview(3),
    ])
    rendered = r.observation(obs, sibling_collapse=True)
    assert rendered == '[1] ImageView\n[2] ImageView "X"\n[3] ImageView'


def test_sibling_collapse_resource_id_in_collapsed_line():
    """With with_resource_id=True and a shared non-empty resource_id, the
    collapsed line carries #rid_short."""
    r = ProseRenderer()
    obs = Observation(nodes=[
        _imgview(1, resource_id="com.example:id/icon"),
        _imgview(2, resource_id="com.example:id/icon"),
        _imgview(3, resource_id="com.example:id/icon"),
    ])
    rendered = r.observation(obs, with_resource_id=True, sibling_collapse=True)
    assert rendered == "[1] ImageView × 3 #icon"


def test_sibling_collapse_run_at_end_of_list():
    """Off-by-one guard: a run ending at the last node still collapses."""
    r = ProseRenderer()
    obs = Observation(nodes=[
        _node(id=1, cls="android.widget.TextView", text="Header", content_desc="", clickable=False),
        _imgview(2),
        _imgview(3),
        _imgview(4),
    ])
    rendered = r.observation(obs, sibling_collapse=True)
    assert rendered == '[1] TextView "Header"\n[2] ImageView × 3'
```

Run `uv run pytest -q tests/test_render.py -k sibling_collapse`. All seven should FAIL — the collapse logic does not exist yet.

- [ ] **Step 2: Implement the collapse logic.**

Replace `ProseRenderer.observation` in `androidharness/render.py`:

```python
def observation(
    self,
    obs: Observation,
    *,
    with_resource_id: bool = False,
    sibling_collapse: bool = False,
) -> str:
    if not sibling_collapse:
        return "\n".join(
            self.node(n, with_resource_id=with_resource_id) for n in obs.nodes
        )

    lines: list[str] = []
    nodes = obs.nodes
    i = 0
    n = len(nodes)
    while i < n:
        run_end = i + 1
        head = nodes[i]
        # A node is collapsible only if it has no distinguishing label.
        if not head.text and not head.content_desc:
            while run_end < n:
                cur = nodes[run_end]
                if (
                    cur.class_name == head.class_name
                    and cur.resource_id == head.resource_id
                    and not cur.text
                    and not cur.content_desc
                ):
                    run_end += 1
                else:
                    break
        run_len = run_end - i
        if run_len >= 3:
            parts = [f"[{head.id}]", head.short_class, f"× {run_len}"]
            if with_resource_id and head.resource_id:
                rid = head.resource_id
                short = rid.rsplit("/", 1)[-1] if "/" in rid else rid
                parts.append(f"#{short}")
            lines.append(" ".join(parts))
            i = run_end
        else:
            lines.append(self.node(head, with_resource_id=with_resource_id))
            i += 1
    return "\n".join(lines)
```

- [ ] **Step 3: Run all render tests — every test (old + new) must pass.**

```bash
uv run pytest -q tests/test_render.py
```

- [ ] **Step 4: Run the full suite to catch any unexpected regression.**

```bash
uv run pytest -q
```

- [ ] **Step 5: Run lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 6: Commit.**

```bash
git add androidharness/render.py tests/test_render.py
git commit -m "feat(render): implement sibling-collapse for runs of N≥3 nodes"
```

---

## Task 3: Thread `sibling_collapse` through `Observation.render`

**Files:**
- Modify: `androidharness/perception.py`
- Modify: `tests/test_perception.py`

- [ ] **Step 1: Write the failing threading test.**

Append to `tests/test_perception.py`:

```python
def test_observation_render_threads_sibling_collapse():
    """Observation.render(sibling_collapse=True) must produce the same
    collapsed output that ProseRenderer.observation produces directly."""
    from androidharness.perception import Node, Observation

    def img(id_: int) -> Node:
        return Node(
            id=id_,
            class_name="android.widget.ImageView",
            text="",
            content_desc="",
            resource_id="",
            bounds=(0, 0, 10, 10),
            clickable=False,
            long_clickable=False,
            scrollable=False,
            editable=False,
        )

    obs = Observation(nodes=[img(1), img(2), img(3)])
    rendered = obs.render(sibling_collapse=True)
    assert rendered == "[1] ImageView × 3"
    # Default keeps the old behavior.
    assert obs.render() == "[1] ImageView\n[2] ImageView\n[3] ImageView"
```

Run `uv run pytest -q tests/test_perception.py -k sibling_collapse`. FAIL — `Observation.render` doesn't accept the keyword yet.

- [ ] **Step 2: Add the keyword to `Observation.render`.**

In `androidharness/perception.py`, replace the `render` method on `Observation`:

```python
def render(
    self,
    *,
    with_resource_ids: bool = False,
    sibling_collapse: bool = False,
) -> str:
    from androidharness.render import DEFAULT_RENDERER

    return DEFAULT_RENDERER.observation(
        self,
        with_resource_id=with_resource_ids,
        sibling_collapse=sibling_collapse,
    )
```

- [ ] **Step 3: Run perception and render tests.**

```bash
uv run pytest -q tests/test_perception.py tests/test_render.py
```

- [ ] **Step 4: Run lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```bash
git add androidharness/perception.py tests/test_perception.py
git commit -m "feat(perception): thread sibling_collapse through Observation.render"
```

---

## Task 4: Plumb `sibling_collapse` through `Agent`

**Files:**
- Modify: `androidharness/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Inspect how `resource_id_in_render` is plumbed and mirror it.**

In `androidharness/agent.py`, `Agent` has a `resource_id_in_render: bool = False` field and three `obs.render(...)` callsites. The new field follows the same pattern.

- [ ] **Step 2: Write a failing test that pins the threading.**

Append to `tests/test_agent.py`:

```python
def test_agent_passes_sibling_collapse_to_renderer(monkeypatch):
    """When Agent.sibling_collapse=True the rendered observation the agent
    builds is collapsed."""
    from androidharness.agent import Agent
    from androidharness.llm import LLMClient
    from androidharness.perception import Node, Observation
    from androidharness.policy import AlwaysApproveConfirmer, Policy

    # Three ImageView nodes — should collapse to one line.
    collapsible_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node bounds="[0,0][1000,1000]">
        <node class="android.widget.ImageView" bounds="[0,0][10,10]" clickable="true"/>
        <node class="android.widget.ImageView" bounds="[10,0][20,10]" clickable="true"/>
        <node class="android.widget.ImageView" bounds="[20,0][30,10]" clickable="true"/>
      </node>
    </hierarchy>"""

    class FakeDevice:
        serial = "fake"
        model = "fake"
        def dump_hierarchy(self) -> str:
            return collapsible_xml
        def screenshot(self) -> bytes:
            return b""

    captured: list[str] = []

    class CapturingClient:
        def generate(self, *, model, system_instruction, contents, tools):
            for c in contents:
                if c.get("role") == "observation":
                    captured.append(c["text"])
            return {"name": "done", "args": {"success": True, "reason": "ok"}}

    agent = Agent(
        device=FakeDevice(),
        client=CapturingClient(),
        model="fake",
        max_turns=1,
        sibling_collapse=True,
        policy=Policy(),
        confirmer=AlwaysApproveConfirmer(),
    )
    agent.run("test")
    assert captured, "agent never sent an observation"
    assert "× 3" in captured[0], f"expected collapsed render, got: {captured[0]!r}"
```

(If `AlwaysApproveConfirmer` is not exported, the existing `tests/conftest.py` has one or the test can use `Policy(default=PolicyDecision.allow)` — pick whichever pattern matches the surrounding test file. Check `tests/test_agent.py` for the local convention before writing.)

Run the test — FAIL: `Agent` does not accept `sibling_collapse`.

- [ ] **Step 3: Add the field and thread it through every `obs.render(...)` call.**

In `androidharness/agent.py`, add the field next to `resource_id_in_render`:

```python
@dataclass
class Agent:
    device: Any
    client: LLMClient
    model: str = "gemini-2.5-flash"
    max_turns: int = 40
    wall_clock_s: float = 600.0
    quantize_screenshots: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False
    sibling_collapse: bool = False
    policy: Policy = field(default_factory=Policy)
    confirmer: Confirmer = field(default_factory=AlwaysRejectConfirmer)
```

Then update every `obs.render(...)` call inside `Agent.run` to pass it. There are three: the observation payload, the stall-detector argument, and the turn-log summary. Each becomes:

```python
obs.render(
    with_resource_ids=self.resource_id_in_render,
    sibling_collapse=self.sibling_collapse,
)
```

(The stall-detector call and the turn-log summary currently pass no flags. Pass both flags consistently so the model and the stall detector are looking at the same string — otherwise a collapsed UI could falsely trigger a "stale observation" warning.)

- [ ] **Step 4: Run the test — it should pass.**

```bash
uv run pytest -q tests/test_agent.py -k sibling_collapse
```

- [ ] **Step 5: Run the full suite.**

```bash
uv run pytest -q
```

- [ ] **Step 6: Run lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```bash
git add androidharness/agent.py tests/test_agent.py
git commit -m "feat(agent): pass sibling_collapse to every observation render"
```

---

## Task 5: Plumb `sibling_collapse` through `run_task` and the `run` CLI

**Files:**
- Modify: `androidharness/runner.py`
- Modify: `androidharness/cli.py`

(No new tests in this task — Task 4 already covers the Agent threading and tests/test_cli_run_config.py exists for run-CLI config-wiring coverage; consult its style if a regression test feels warranted.)

- [ ] **Step 1: Add `sibling_collapse: bool = False` to `run_task`.**

In `androidharness/runner.py`, the parameter list currently has `viewport_filter` and `resource_id_in_render` together. Insert `sibling_collapse` after `resource_id_in_render`:

```python
def run_task(
    *,
    ...
    viewport_filter: bool = False,
    resource_id_in_render: bool = False,
    sibling_collapse: bool = False,
    policy: Policy | None = None,
    confirmer: Confirmer | None = None,
) -> RunOutcome:
```

And forward it into `Agent(...)`:

```python
agent = Agent(
    ...
    viewport_filter=viewport_filter,
    resource_id_in_render=resource_id_in_render,
    sibling_collapse=sibling_collapse,
    ...
)
```

- [ ] **Step 2: Wire the config flag through the `run` CLI.**

In `androidharness/cli.py`, in `run_cmd` the call to `run_task(...)` already passes `viewport_filter=cfg.perception.viewport_filter` and `resource_id_in_render=cfg.perception.resource_id_in_render`. Add:

```python
sibling_collapse=cfg.perception.sibling_collapse,
```

- [ ] **Step 3: Run the suite.**

```bash
uv run pytest -q
```

- [ ] **Step 4: Lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```bash
git add androidharness/runner.py androidharness/cli.py
git commit -m "feat(runner,cli): pass cfg.perception.sibling_collapse through run"
```

---

## Task 6: Add `--sibling-collapse / --no-sibling-collapse` to `peek`

**Files:**
- Modify: `androidharness/cli.py`
- Modify: `tests/test_cli_peek.py`

- [ ] **Step 1: Write a failing test mirroring the `--with-resource-ids` override.**

Look at `test_peek_no_resource_ids_flag_overrides_config` for the pattern. Append a parallel pair to `tests/test_cli_peek.py`:

```python
def test_peek_sibling_collapse_flag_overrides_config(isolated_home, stub_peek, tmp_path):
    """When --sibling-collapse is passed and the config has it off, output
    should be collapsed for the stubbed observation."""
    # The stub_peek fixture's hierarchy must contain 3+ collapsible siblings.
    # If it does not, extend the fixture (see test_cli_peek.py at top) or
    # provide a one-off XML via the same monkeypatch path stub_peek uses.
    result = runner.invoke(app, ["peek", "--sibling-collapse"])
    assert result.exit_code == 0, result.output
    assert "× " in result.output


def test_peek_no_sibling_collapse_flag_overrides_config(isolated_home, stub_peek, tmp_path):
    """--no-sibling-collapse must render every node verbatim even when the
    config flag is on."""
    cfg_dir = isolated_home / ".androidharness"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "version: 1\nperception:\n  sibling_collapse: true\n"
    )
    result = runner.invoke(app, ["peek", "--no-sibling-collapse"])
    assert result.exit_code == 0, result.output
    assert "× " not in result.output
```

(Adapt the `cfg_dir` shape to whatever `isolated_home` already wires — the convention should be visible at the top of `test_cli_peek.py`. Likewise, ensure the stubbed device hierarchy in `stub_peek` actually has a collapsible run; if not, extend the stub before writing this test.)

Run the tests — FAIL: `--sibling-collapse` is an unknown option.

- [ ] **Step 2: Add the flag to `peek_cmd`.**

In `androidharness/cli.py`, mirror the shape of `with_resource_ids`:

```python
@app.command("peek")
def peek_cmd(
    serial: str | None = typer.Option(None, "--serial", "-s"),
    device_index: int | None = typer.Option(None, "--device-index", "-i"),
    viewport_filter: bool | None = typer.Option(
        None,
        "--viewport-filter/--no-viewport-filter",
        help="Drop off-screen / visibility=gone nodes. Default: cfg.perception.viewport_filter.",
    ),
    with_resource_ids: bool | None = typer.Option(
        None,
        "--with-resource-ids/--no-resource-ids",
        help="Append the resource-id to each node. Default: cfg.perception.resource_id_in_render.",
    ),
    sibling_collapse: bool | None = typer.Option(
        None,
        "--sibling-collapse/--no-sibling-collapse",
        help="Collapse runs of N≥3 identical sibling nodes. Default: cfg.perception.sibling_collapse.",
    ),
    raw_xml: bool = typer.Option(...),
    config_path: Path | None = typer.Option(None, "--config", help="Override the config path."),
) -> None:
    ...
    vf = viewport_filter if viewport_filter is not None else cfg.perception.viewport_filter
    rids = (
        with_resource_ids
        if with_resource_ids is not None
        else cfg.perception.resource_id_in_render
    )
    sc = (
        sibling_collapse
        if sibling_collapse is not None
        else cfg.perception.sibling_collapse
    )

    ...
    obs = parse_hierarchy(xml, viewport_filter=vf)
    rendered = DEFAULT_RENDERER.observation(
        obs, with_resource_id=rids, sibling_collapse=sc
    )
    typer.echo(
        f"# {len(obs.nodes)} nodes (viewport_filter={vf}, resource_ids={rids}, "
        f"sibling_collapse={sc}, ~{len(rendered)} chars)",
        err=True,
    )
    typer.echo(rendered)
```

- [ ] **Step 3: Run peek tests.**

```bash
uv run pytest -q tests/test_cli_peek.py
```

- [ ] **Step 4: Full suite + lint.**

```bash
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```bash
git add androidharness/cli.py tests/test_cli_peek.py
git commit -m "feat(cli): peek --sibling-collapse overrides the perception flag"
```

---

## Task 7: Capture three reference XML fixtures from a real device

**Why:** The measurement script in Task 8 needs realistic input. These XMLs are committed verbatim so the numbers are reproducible.

**Files:**
- New: `tests/fixtures/screens/settings_list.xml`
- New: `tests/fixtures/screens/app_drawer.xml`
- New: `tests/fixtures/screens/notification_shade.xml`

- [ ] **Step 1: Capture each screen with `adb shell uiautomator dump`.**

On a connected device, navigate to each screen, then:

```bash
adb shell uiautomator dump /sdcard/dump.xml
adb pull /sdcard/dump.xml tests/fixtures/screens/<name>.xml
```

The three screens:
- **settings_list** — Android Settings root (the long list of categories).
- **app_drawer** — the launcher's app drawer with many icons.
- **notification_shade** — pull-down notification shade with several notifications.

Each should be a screen where sibling collapse is plausibly beneficial. If a screen has fewer than 3 collapsible siblings, pick a different one.

- [ ] **Step 2: Sanity-check each fixture parses cleanly.**

```bash
uv run python -c "
from pathlib import Path
from androidharness.perception import parse_hierarchy
for name in ['settings_list', 'app_drawer', 'notification_shade']:
    xml = Path(f'tests/fixtures/screens/{name}.xml').read_text()
    obs = parse_hierarchy(xml, viewport_filter=True)
    print(name, len(obs.nodes), 'nodes')
"
```

- [ ] **Step 3: Commit the fixtures.**

```bash
git add tests/fixtures/screens/
git commit -m "test(fixtures): reference XMLs for perception measurement"
```

---

## Task 8: Add the manual measurement script and record the numbers

**Files:**
- New: `scripts/measure_perception.py`
- Modify: `docs/superpowers/specs/2026-05-22-v2-milestone-6-sibling-collapse-design.md` (the "Measurements" section)

Note: editing a spec post-ship is an exception to "don't modify shipped specs" — the Measurements section is explicitly reserved at design time for this purpose.

- [ ] **Step 1: Write the measurement script.**

```python
# scripts/measure_perception.py
"""Manual dev tool — measure rendering size with and without each compression
flag. Not part of the package; not tested. Run from the repo root:

    uv run python scripts/measure_perception.py
"""

from __future__ import annotations

from pathlib import Path

from androidharness.perception import parse_hierarchy
from androidharness.render import DEFAULT_RENDERER

SCREENS = ["settings_list", "app_drawer", "notification_shade"]


def render(obs, *, viewport_filter: bool, resource_ids: bool, sibling_collapse: bool) -> str:
    # viewport_filter is applied at parse time, not render time; this function
    # only varies the renderer flags. The caller controls parsing.
    return DEFAULT_RENDERER.observation(
        obs, with_resource_id=resource_ids, sibling_collapse=sibling_collapse
    )


def main() -> None:
    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "screens"
    for name in SCREENS:
        xml = (fixtures / f"{name}.xml").read_text()
        obs_raw = parse_hierarchy(xml, viewport_filter=False)
        obs_vf = parse_hierarchy(xml, viewport_filter=True)
        rows = []
        for label, obs in [("raw", obs_raw), ("viewport_filter", obs_vf)]:
            for sc in (False, True):
                text = render(obs, viewport_filter=False, resource_ids=False, sibling_collapse=sc)
                rows.append((
                    label,
                    f"sibling_collapse={sc}",
                    len(obs.nodes),
                    len(text),
                    len(text) // 4,
                ))
        print(f"## {name}")
        print(f"{'parse':<20} {'flag':<24} {'nodes':>6} {'chars':>8} {'~tokens':>9}")
        for r in rows:
            print(f"{r[0]:<20} {r[1]:<24} {r[2]:>6} {r[3]:>8} {r[4]:>9}")
        print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and capture the output.**

```bash
uv run python scripts/measure_perception.py | tee /tmp/m6-measurements.txt
```

- [ ] **Step 3: Paste the output into the spec's "Measurements" section.**

Edit `docs/superpowers/specs/2026-05-22-v2-milestone-6-sibling-collapse-design.md` — replace the placeholder under `## Measurements` with a fenced code block of the script's output and one short paragraph noting the practical reduction on the two screens that benefit most.

- [ ] **Step 4: Commit script + spec update.**

```bash
git add scripts/measure_perception.py docs/superpowers/specs/2026-05-22-v2-milestone-6-sibling-collapse-design.md
git commit -m "tools: measure_perception.py + record M6 measurements"
```

---

## Task 9: Documentation pass

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/configuration.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/architecture.md`.** In the rendering paragraph, add one sentence: "Sibling-collapse (config: `perception.sibling_collapse`) collapses runs of N≥3 identical-class siblings with no distinguishing label into a single `[id] ClassName × N` line — saves tokens on app drawers and notification shades without changing the underlying Observation."

- [ ] **Step 2: `docs/configuration.md`.** Update the description of `perception.sibling_collapse` from "Placeholder, no effect yet" to a working description that points at the rendered output format and the `peek --sibling-collapse` flag.

- [ ] **Step 3: `docs/roadmap.md`.** Mark M6 as Shipped with the commit range that lands the milestone (find via `git log --oneline` after Task 8). Mirror the entry shape used for M5.

- [ ] **Step 4: Commit.**

```bash
git add docs/architecture.md docs/configuration.md docs/roadmap.md
git commit -m "docs: M6 shipped — sibling-collapse documented across architecture, config, roadmap"
```

---

## Final verification

- [ ] **Step 1: Full test suite.**

```bash
uv run pytest -q
```

- [ ] **Step 2: Lint.**

```bash
uv run ruff check androidharness/ tests/
```

- [ ] **Step 3: Smoke against a real device (optional but recommended).**

```bash
uv run androidharness peek --no-sibling-collapse > /tmp/before.txt
uv run androidharness peek --sibling-collapse > /tmp/after.txt
diff -u /tmp/before.txt /tmp/after.txt | head -40
```

The diff should show the collapsed lines on screens with homogeneous lists; structured screens (a settings detail page) should diff cleanly to nothing.

- [ ] **Step 4: Subagent dispatch review (recommended).** If executing via `superpowers:subagent-driven-development`, the two-stage review (spec compliance + code quality) runs after Task 9 against the full diff range. The implementer should be prepared to fold review feedback into a follow-up commit before the milestone is declared Shipped.

---

## Risks & mitigations (from the spec, recapped)

| Risk | Mitigation |
|---|---|
| Two unrelated views (e.g. header ImageButtons) get collapsed. | The empty-text + empty-content-desc guard catches almost all of these (header buttons carry content-desc for accessibility). N≥3 threshold further reduces false positives. |
| The model gets confused by `× N` syntax. | The smoke step above gives a quick A/B; `--no-sibling-collapse` is the per-call escape hatch. |
| Off-by-one when the run is at the end of `obs.nodes`. | Covered by `test_sibling_collapse_run_at_end_of_list`. |
| Stall detector divergence (model sees collapsed text; detector sees full text → false NO_PROGRESS). | Task 4 step 3 explicitly threads the flag into every `obs.render()` call inside the agent, including the stall-detector input, so both look at the same string. |

---

## Sequencing summary

1. Task 1 — Renderer Protocol accepts the keyword (no-op).
2. Task 2 — `ProseRenderer.observation` implements the collapse + 7 tests.
3. Task 3 — `Observation.render` threads the keyword + 1 test.
4. Task 4 — `Agent` reads + threads the flag + 1 test.
5. Task 5 — `runner.run_task` + `run` CLI plumb the flag (config-driven).
6. Task 6 — `peek` CLI override flag + 2 tests.
7. Task 7 — three reference XML fixtures.
8. Task 8 — measurement script + record numbers in the spec.
9. Task 9 — docs pass + mark Shipped on the roadmap.
