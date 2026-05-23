# v2 Milestone 22 — Perception foreground-package signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepend `# foreground: <package>` to every rendered Observation (when the new `perception.foreground_package` flag is on) so the model has a stable "what app am I in" signal across turns. The package is read from the topmost `<node>` child of `<hierarchy>` in the UIAutomator XML and stored on `Observation.foreground_package`. Render-time only; `Node` is unchanged.

**Architecture:** A new `foreground_package: bool = False` keyword on `Renderer.observation` (Protocol), `ProseRenderer.observation` (implementation), and `Observation.render` (caller helper). `Observation` grows a `foreground_package: str = ""` field set by `parse_hierarchy`. `Agent` reads `cfg.perception.foreground_package` and threads it through every render call alongside `with_resource_ids` and `sibling_collapse`. `runner.run_task` gains the parameter; the `run` CLI passes the config value; `peek` gains `--foreground-package / --no-foreground-package` for one-off A/B.

**Spec:** `docs/superpowers/specs/2026-05-23-v2-milestone-22-foreground-package-signal-design.md`.

**Design decisions (locked in the spec):**
1. Foreground source: `hierarchy/node[1]/@package` from the raw XML (the first direct-child `<node>` of `<hierarchy>`).
2. Empty-foreground semantics: when the field is `""`, the header line is **entirely omitted** — no `# foreground: \n` with a trailing-empty value.
3. Header format: exactly `"# foreground: " + obs.foreground_package + "\n"` — pinned by tests so future renderer ports reproduce it.
4. `Node` is unchanged. Foreground lives on `Observation`. Per-node package annotation is a separate future milestone.
5. No XML-fixture changes for unit tests — construct `Observation(nodes=[...], foreground_package="...")` directly. The existing reference fixtures from M6 are used only by the measurement script extension.
6. No SYSTEM_PROMPT changes ship in this milestone — the header is self-explanatory. A prompt nudge is a one-line follow-up if a real run shows the model isn't picking up the signal.

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `androidharness/config.py` | Modify | `PerceptionConfig.foreground_package: bool = False`. |
| `androidharness/perception.py` | Modify | `Observation.foreground_package: str = ""`; `parse_hierarchy` populates from `<hierarchy>/<node>[1]/@package`; `Observation.render` accepts the flag. |
| `androidharness/render.py` | Modify | `Renderer.observation` Protocol + `ProseRenderer.observation` accept `foreground_package`; prepend header when True + field non-empty. |
| `androidharness/agent.py` | Modify | `Agent.foreground_package: bool = False`; threaded into every `obs.render(...)` call (three callsites). |
| `androidharness/runner.py` | Modify | `run_task` accepts `foreground_package: bool = False`; forwards to `Agent`. |
| `androidharness/cli.py` | Modify | `run_cmd` passes `cfg.perception.foreground_package`; `peek_cmd` gains `--foreground-package / --no-foreground-package`. |
| `tests/test_perception.py` | Modify | 4 new tests (3 parse + 1 render-threading). |
| `tests/test_render.py` | Modify | 4 new tests (header on, off, empty-field, combined-with-sibling-collapse). |
| `tests/test_config.py` | Modify | 1 default-value assertion. |
| `tests/test_agent.py` | Modify | 1 new test that the flag reaches the renderer. |
| `tests/test_cli_peek.py` | Modify | 2 new tests for the override flag. |
| `scripts/measure_perception.py` | Modify | One extra print line per fixture (foreground package). |
| `docs/architecture.md` | Modify | One line: `ProseRenderer` describes the foreground header. |
| `docs/configuration.md` | Modify | New row for `perception.foreground_package`. |
| `docs/roadmap.md` | Modify | New row at the bottom of the v2 milestone table for M22, marked Shipped with commit range. |

Untouched: `llm.py`, `policy.py`, `device.py`, `tools.py`, `imaging.py`, `logging_setup.py`, the `web/` subpackage.

---

## Task 1: `Observation.foreground_package` field + `parse_hierarchy` extraction

**Why first:** Foundational. Nothing else can render the header until `Observation` carries the field and `parse_hierarchy` populates it. Stays inside `perception.py` and `test_perception.py`.

**Files:**
- Modify: `androidharness/perception.py`
- Modify: `tests/test_perception.py`

- [ ] **Step 1: Write three failing tests in `tests/test_perception.py`.**

```python
def test_parse_hierarchy_extracts_foreground_package():
    """The package attribute on the topmost <node> child of <hierarchy>
    populates obs.foreground_package."""
    from androidharness.perception import parse_hierarchy

    xml = (
        "<?xml version='1.0'?>"
        "<hierarchy>"
        "  <node package='com.binance.dev' bounds='[0,0][1000,1000]'>"
        "    <node class='android.widget.Button' bounds='[0,0][10,10]' clickable='true'/>"
        "  </node>"
        "</hierarchy>"
    )
    obs = parse_hierarchy(xml)
    assert obs.foreground_package == "com.binance.dev"


def test_parse_hierarchy_foreground_package_empty_when_hierarchy_empty():
    """<hierarchy></hierarchy> with no node children yields ''."""
    from androidharness.perception import parse_hierarchy

    xml = "<?xml version='1.0'?><hierarchy></hierarchy>"
    obs = parse_hierarchy(xml)
    assert obs.foreground_package == ""


def test_parse_hierarchy_foreground_package_empty_when_attr_missing():
    """Topmost <node> with no package= attribute yields ''."""
    from androidharness.perception import parse_hierarchy

    xml = (
        "<?xml version='1.0'?>"
        "<hierarchy>"
        "  <node bounds='[0,0][1000,1000]'>"
        "    <node class='android.widget.Button' bounds='[0,0][10,10]' clickable='true'/>"
        "  </node>"
        "</hierarchy>"
    )
    obs = parse_hierarchy(xml)
    assert obs.foreground_package == ""
```

Run: `uv run pytest -q tests/test_perception.py -k foreground_package`. Expect: all three FAIL with `AttributeError: 'Observation' object has no attribute 'foreground_package'`.

- [ ] **Step 2: Add the field to `Observation`.**

In `androidharness/perception.py`, edit the `Observation` dataclass:

```python
@dataclass
class Observation:
    nodes: list[Node] = field(default_factory=list)
    foreground_package: str = ""
```

(Defaulting to `""` keeps every existing call site that constructs `Observation(nodes=[...])` valid — verified by the full pytest run at the end.)

- [ ] **Step 3: Populate the field in `parse_hierarchy`.**

In the same file, `parse_hierarchy` currently has:

```python
def parse_hierarchy(xml: str, *, viewport_filter: bool = False) -> Observation:
    root = etree.fromstring(xml.encode("utf-8"))
    obs = Observation()
    ...
```

Just after `obs = Observation()`, extract the foreground package:

```python
def parse_hierarchy(xml: str, *, viewport_filter: bool = False) -> Observation:
    root = etree.fromstring(xml.encode("utf-8"))
    obs = Observation()
    for child in root:
        if child.tag == "node":
            obs.foreground_package = child.get("package", "")
            break
    ...
```

(One linear scan looking for the first `<node>` child; stop at the first match. When `<hierarchy>` has no `<node>` children the loop never runs and the field stays `""`. When the topmost node has no `package=` attribute, `.get("package", "")` returns `""`. Both empty cases covered.)

- [ ] **Step 4: Run the three new tests — they should pass.**

```
uv run pytest -q tests/test_perception.py -k foreground_package
```

- [ ] **Step 5: Run the full perception suite — no regressions on the existing tests.**

```
uv run pytest -q tests/test_perception.py
```

- [ ] **Step 6: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/perception.py tests/test_perception.py
git commit -m "feat(perception): extract foreground package from XML into Observation"
```

---

## Task 2: `PerceptionConfig.foreground_package` config field

**Why next:** Land the schema change in isolation so nothing downstream depends on it yet. The field exists with default `False`; no consumer wires it up until later tasks.

**Files:**
- Modify: `androidharness/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Find the existing PerceptionConfig defaults test.**

```
grep -n "PerceptionConfig\|sibling_collapse" tests/test_config.py
```

Locate whichever test currently asserts `PerceptionConfig().sibling_collapse is False` (or similar defaults). The new assertion piggybacks there.

- [ ] **Step 2: Write a failing assertion.**

Add one line to the relevant test (or a tiny new test if the file convention prefers one-assertion-per-test):

```python
def test_perception_config_foreground_package_default_false():
    from androidharness.config import PerceptionConfig
    assert PerceptionConfig().foreground_package is False
```

Run: `uv run pytest -q tests/test_config.py -k foreground_package`. Expect FAIL: `AttributeError: ... has no attribute 'foreground_package'` (or `ValidationError` if Pydantic flags an unknown field — depends on how the assertion is written).

- [ ] **Step 3: Add the field to `PerceptionConfig`.**

In `androidharness/config.py`, find `class PerceptionConfig`:

```python
class PerceptionConfig(BaseModel):
    """Perception feature flags. M6 (sibling_collapse) and M11 (viewport_filter,
    resource_id_in_render) are live; M16 (screenshot_quantized format) is pending."""
    model_config = _STRICT

    sibling_collapse: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False
    screenshot_quantized: bool = False
```

Add `foreground_package: bool = False`. Field order matches the spec's narrative: foreground is a structural-context signal, place it next to `sibling_collapse`:

```python
class PerceptionConfig(BaseModel):
    """Perception feature flags. M6 (sibling_collapse), M11 (viewport_filter,
    resource_id_in_render), and M22 (foreground_package) are live; M16
    (screenshot_quantized format) is pending."""
    model_config = _STRICT

    sibling_collapse: bool = False
    foreground_package: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False
    screenshot_quantized: bool = False
```

Note the docstring update — M22 joins the list of live flags.

- [ ] **Step 4: Run the test — it should pass.**

```
uv run pytest -q tests/test_config.py -k foreground_package
```

- [ ] **Step 5: Verify existing YAML configs still parse.** `_STRICT` typically means `extra="forbid"`, but we're adding a field with a default — not requiring one. Existing configs (including the user's `~/.androidharness/config.yaml`) keep parsing because the field just defaults.

```
uv run androidharness config show 2>&1 | grep foreground_package
```

Expected output: `foreground_package: false` somewhere under the `perception:` block.

- [ ] **Step 6: Run the full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): add perception.foreground_package flag"
```

---

## Task 3: `Renderer.observation` accepts and applies `foreground_package`

**Why:** Land both the kwarg and the header logic in one task — the body is only 3–4 lines, no need to split no-op + logic into two commits the way M6 did for the substantial collapse algorithm.

**Files:**
- Modify: `androidharness/render.py`
- Modify: `tests/test_render.py`

- [ ] **Step 1: Write four failing render tests.**

Append to `tests/test_render.py`:

```python
def test_foreground_package_header_prepends_when_enabled():
    r = ProseRenderer()
    obs = Observation(
        nodes=[_node(id=1, cls="android.widget.Button", text="Buy", clickable=True)],
        foreground_package="com.binance.dev",
    )
    rendered = r.observation(obs, foreground_package=True)
    assert rendered == '# foreground: com.binance.dev\n[1] Button "Buy" (clickable)'


def test_foreground_package_header_omitted_when_disabled():
    """Default behavior: no header, byte-identical to pre-M22 output."""
    r = ProseRenderer()
    obs = Observation(
        nodes=[_node(id=1, cls="android.widget.Button", text="Buy", clickable=True)],
        foreground_package="com.binance.dev",
    )
    rendered = r.observation(obs)
    assert rendered == '[1] Button "Buy" (clickable)'


def test_foreground_package_header_omitted_when_field_empty():
    """Flag on but field empty → no stray `# foreground: \\n` header."""
    r = ProseRenderer()
    obs = Observation(
        nodes=[_node(id=1, cls="android.widget.Button", text="Buy", clickable=True)],
        foreground_package="",
    )
    rendered = r.observation(obs, foreground_package=True)
    assert rendered == '[1] Button "Buy" (clickable)'


def test_foreground_package_combines_with_sibling_collapse():
    """Header followed by collapsed body."""
    r = ProseRenderer()
    obs = Observation(
        nodes=[_imgview(1), _imgview(2), _imgview(3)],
        foreground_package="com.binance.dev",
    )
    rendered = r.observation(obs, foreground_package=True, sibling_collapse=True)
    assert rendered == "# foreground: com.binance.dev\n[1] ImageView × 3"
```

`_node()` and `_imgview()` are the existing helpers near the top of `tests/test_render.py` from M6. If `_node()` doesn't yet accept whatever kwarg shape the tests need, adapt minimally — match the existing pattern, don't add new helpers.

Run: `uv run pytest -q tests/test_render.py -k foreground_package`. Expect: all four FAIL — `observation()` doesn't accept `foreground_package`.

- [ ] **Step 2: Add the keyword to the Protocol and ProseRenderer + implement the header.**

In `androidharness/render.py`, edit `Renderer` Protocol:

```python
class Renderer(Protocol):
    def node(self, n: Node, *, with_resource_id: bool = False) -> str: ...

    def observation(
        self,
        obs: Observation,
        *,
        with_resource_id: bool = False,
        sibling_collapse: bool = False,
        foreground_package: bool = False,
    ) -> str: ...
```

Edit `ProseRenderer.observation`. The new flag wraps the existing body — header is one optional prefix line:

```python
def observation(
    self,
    obs: Observation,
    *,
    with_resource_id: bool = False,
    sibling_collapse: bool = False,
    foreground_package: bool = False,
) -> str:
    # existing body — unchanged, kept verbatim below
    if not sibling_collapse:
        body = "\n".join(
            self.node(n, with_resource_id=with_resource_id) for n in obs.nodes
        )
    else:
        lines: list[str] = []
        nodes = obs.nodes
        i = 0
        n = len(nodes)
        while i < n:
            run_end = i + 1
            head = nodes[i]
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
                    parts.append(f"#{self._short_resource_id(head.resource_id)}")
                lines.append(" ".join(parts))
                i = run_end
            else:
                lines.append(self.node(head, with_resource_id=with_resource_id))
                i += 1
        body = "\n".join(lines)

    if foreground_package and obs.foreground_package:
        return f"# foreground: {obs.foreground_package}\n{body}"
    return body
```

The refactor introduces a `body` local and a single return-point at the bottom. The collapse algorithm is unchanged — just hoisted into the conditional. Re-running the M6 sibling-collapse tests must keep passing.

Also update the `CompactRenderer` fixture in `tests/test_render.py` (the Protocol-conformance fixture used by `test_renderer_protocol_accepts_a_custom_implementation`) to include `foreground_package: bool = False` in its `observation` signature, mirroring the M6 Task-1 fixup. Without this update the Protocol fixture drifts out of sync.

- [ ] **Step 3: Run all render tests — every test (old + new) must pass.**

```
uv run pytest -q tests/test_render.py
```

- [ ] **Step 4: Run the full suite.**

```
uv run pytest -q
```

- [ ] **Step 5: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 6: Commit.**

```
git add androidharness/render.py tests/test_render.py
git commit -m "feat(render): foreground-package header prepended when flag is on"
```

---

## Task 4: Thread `foreground_package` through `Observation.render`

**Files:**
- Modify: `androidharness/perception.py`
- Modify: `tests/test_perception.py`

- [ ] **Step 1: Write the failing threading test.**

Append to `tests/test_perception.py`:

```python
def test_observation_render_threads_foreground_package():
    """Observation.render(foreground_package=True) prepends the header from
    the field set by parse_hierarchy (or constructed directly)."""
    from androidharness.perception import Node, Observation

    obs = Observation(
        nodes=[
            Node(
                id=1, class_name="android.widget.Button",
                text="Buy", content_desc="", resource_id="",
                bounds=(0, 0, 10, 10),
                clickable=True, long_clickable=False, scrollable=False, editable=False,
            )
        ],
        foreground_package="com.binance.dev",
    )
    rendered = obs.render(foreground_package=True)
    assert rendered.startswith("# foreground: com.binance.dev\n")
```

Run: FAIL — `Observation.render` doesn't accept `foreground_package`.

- [ ] **Step 2: Add the keyword to `Observation.render`.**

In `androidharness/perception.py`:

```python
def render(
    self,
    *,
    with_resource_ids: bool = False,
    sibling_collapse: bool = False,
    foreground_package: bool = False,
) -> str:
    from androidharness.render import DEFAULT_RENDERER

    return DEFAULT_RENDERER.observation(
        self,
        with_resource_id=with_resource_ids,
        sibling_collapse=sibling_collapse,
        foreground_package=foreground_package,
    )
```

- [ ] **Step 3: Run perception + render tests.**

```
uv run pytest -q tests/test_perception.py tests/test_render.py
```

- [ ] **Step 4: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 5: Commit.**

```
git add androidharness/perception.py tests/test_perception.py
git commit -m "feat(perception): thread foreground_package through Observation.render"
```

---

## Task 5: Plumb `foreground_package` through `Agent`

**Files:**
- Modify: `androidharness/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Inspect the three `obs.render(...)` callsites.**

`grep -n "obs.render(" androidharness/agent.py` — expect exactly 3 matches inside `Agent.run`:
1. The observation payload (lines around 180–185).
2. The stall-detector argument to `_is_stalled` (around line 195).
3. The `observation_summary` written into `turn_log` (around line 250).

All three currently pass `with_resource_ids=self.resource_id_in_render` and `sibling_collapse=self.sibling_collapse`. The new flag joins them.

- [ ] **Step 2: Write a failing agent test.**

Append to `tests/test_agent.py`:

```python
def test_agent_passes_foreground_package_to_renderer():
    """When Agent.foreground_package=True, the rendered observation the
    agent sends in `contents` carries the foreground header."""
    from androidharness.agent import Agent
    from androidharness.policy import AlwaysApproveConfirmer, Policy

    xml = (
        "<?xml version='1.0'?>"
        "<hierarchy>"
        "  <node package='com.binance.dev' bounds='[0,0][1000,1000]'>"
        "    <node class='android.widget.Button' bounds='[0,0][10,10]' clickable='true'/>"
        "  </node>"
        "</hierarchy>"
    )

    class _FakeDevice:
        serial = "fake"
        model = "fake"
        def dump_hierarchy(self) -> str:
            return xml
        def screenshot(self) -> bytes:
            return b""

    captured: list[str] = []

    class _CapturingClient:
        def generate(self, *, model, system_instruction, contents, tools):
            for c in contents:
                if c.get("role") == "observation":
                    captured.append(c["text"])
            return {"name": "done", "args": {"success": True, "reason": "ok"}}

    agent = Agent(
        device=_FakeDevice(),
        client=_CapturingClient(),
        model="fake",
        max_turns=1,
        foreground_package=True,
        policy=Policy(),
        confirmer=AlwaysApproveConfirmer(),
    )
    agent.run("test")
    assert captured, "agent never sent an observation"
    assert captured[0].startswith("# foreground: com.binance.dev\n"), captured[0]
```

Run: FAIL — `Agent.__init__()` doesn't accept `foreground_package`.

- [ ] **Step 3: Add the field and thread it through every `obs.render(...)` call.**

In `androidharness/agent.py`, insert the field on the dataclass between `sibling_collapse` and `policy`:

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
    foreground_package: bool = False
    policy: Policy = field(default_factory=Policy)
    confirmer: Confirmer = field(default_factory=AlwaysRejectConfirmer)
```

Update every `obs.render(...)` call in `Agent.run` — three of them. Each becomes:

```python
obs.render(
    with_resource_ids=self.resource_id_in_render,
    sibling_collapse=self.sibling_collapse,
    foreground_package=self.foreground_package,
)
```

**Critical:** All three callsites must pass the same flags. The stall detector compares `current_obs_render` (caller's arg, second callsite) against `turn_log[-N:]["observation_summary"]` (third callsite). M6 made these consistent; M22 must keep them consistent.

- [ ] **Step 4: Run the new test — it should pass.**

```
uv run pytest -q tests/test_agent.py -k foreground_package
```

- [ ] **Step 5: Run the full suite.**

```
uv run pytest -q
```

- [ ] **Step 6: Run lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 7: Commit.**

```
git add androidharness/agent.py tests/test_agent.py
git commit -m "feat(agent): pass foreground_package to every observation render"
```

---

## Task 6: Plumb `foreground_package` through `run_task` and the `run` CLI

**Files:**
- Modify: `androidharness/runner.py`
- Modify: `androidharness/cli.py`

(No new tests — Task 5 covers the Agent threading; `tests/test_cli_run_config.py` exists if a regression test feels warranted, but the plan does not require one. Mirrors M6 Task 5.)

- [ ] **Step 1: Add `foreground_package: bool = False` to `run_task`.**

In `androidharness/runner.py`, insert after `sibling_collapse`:

```python
def run_task(
    *,
    ...
    viewport_filter: bool = False,
    resource_id_in_render: bool = False,
    sibling_collapse: bool = False,
    foreground_package: bool = False,
    policy: Policy | None = None,
    confirmer: Confirmer | None = None,
) -> RunOutcome:
```

Forward into the `Agent(...)` constructor — same insertion position:

```python
agent = Agent(
    ...
    viewport_filter=viewport_filter,
    resource_id_in_render=resource_id_in_render,
    sibling_collapse=sibling_collapse,
    foreground_package=foreground_package,
    ...
)
```

- [ ] **Step 2: Wire the config flag through `run_cmd`.**

In `androidharness/cli.py`, `run_cmd` already passes `sibling_collapse=cfg.perception.sibling_collapse`. Add a parallel kwarg:

```python
foreground_package=cfg.perception.foreground_package,
```

- [ ] **Step 3: Full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 4: Commit.**

```
git add androidharness/runner.py androidharness/cli.py
git commit -m "feat(runner,cli): pass cfg.perception.foreground_package through run"
```

---

## Task 7: Add `--foreground-package / --no-foreground-package` to `peek`

**Files:**
- Modify: `androidharness/cli.py`
- Modify: `tests/test_cli_peek.py`

- [ ] **Step 1: Add a hierarchy fixture with a known package, and a stub that returns it.**

Append to `tests/test_cli_peek.py` near the existing `_COLLAPSIBLE_HIERARCHY`:

```python
_PACKAGED_HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node package="com.binance.dev" bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Buy" clickable="true"/>
  </node>
</hierarchy>
"""


@pytest.fixture
def stub_peek_packaged(monkeypatch):
    """Like stub_peek, but the device returns a hierarchy whose topmost node
    declares package='com.binance.dev'."""

    class FakeUIDevice:
        serial = "STUB"
        model = "StubPixel"

        @classmethod
        def connect(cls, serial: str):
            obj = cls()
            obj.serial = serial
            return obj

        def dump_hierarchy(self) -> str:
            return _PACKAGED_HIERARCHY

    def fake_list_devices():
        return [DeviceInfo(serial="STUB", model="StubPixel")]

    monkeypatch.setattr("androidharness.cli.list_devices", fake_list_devices)
    monkeypatch.setattr("androidharness.cli.UIAutomatorDevice", FakeUIDevice)
```

- [ ] **Step 2: Write two failing override tests.**

```python
def test_peek_foreground_package_flag_overrides_config(isolated_home, stub_peek_packaged):
    """Default config has foreground_package=False. --foreground-package must
    add the header for one peek."""
    result = runner.invoke(app, ["peek", "--foreground-package"])
    assert result.exit_code == 0, result.stdout
    assert "# foreground: com.binance.dev" in result.stdout


def test_peek_no_foreground_package_flag_overrides_config(isolated_home, stub_peek_packaged):
    """Inverse: config sets foreground_package=true but --no-foreground-package
    suppresses for one peek."""
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("perception:\n  foreground_package: true\n")
    result = runner.invoke(app, ["peek", "--no-foreground-package"])
    assert result.exit_code == 0, result.stdout
    assert "# foreground:" not in result.stdout
```

Run: both FAIL — `--foreground-package` is an unknown option.

- [ ] **Step 3: Add the option to `peek_cmd` mirroring `--sibling-collapse`.**

In `androidharness/cli.py`, immediately after the existing `sibling_collapse` Option:

```python
foreground_package: bool | None = typer.Option(
    None,
    "--foreground-package/--no-foreground-package",
    help="Prepend `# foreground: <package>` header. Default: cfg.perception.foreground_package.",  # noqa: E501
),
```

In the body, immediately after the `sc = ...` derivation:

```python
fp = (
    foreground_package
    if foreground_package is not None
    else cfg.perception.foreground_package
)
```

Update the render call:

```python
rendered = DEFAULT_RENDERER.observation(
    obs, with_resource_id=rids, sibling_collapse=sc, foreground_package=fp
)
```

Update the stderr header for symmetry with the existing flag-status segments:

```python
typer.echo(
    f"# {len(obs.nodes)} nodes (viewport_filter={vf}, resource_ids={rids}, "
    f"sibling_collapse={sc}, foreground_package={fp}, ~{len(rendered)} chars)",
    err=True,
)
```

- [ ] **Step 4: Run peek tests.**

```
uv run pytest -q tests/test_cli_peek.py
```

All existing tests must still pass; the two new tests must now pass too.

- [ ] **Step 5: Full suite + lint.**

```
uv run pytest -q
uv run ruff check androidharness/ tests/
```

- [ ] **Step 6: Commit.**

```
git add androidharness/cli.py tests/test_cli_peek.py
git commit -m "feat(cli): peek --foreground-package overrides the perception flag"
```

---

## Task 8: Extend the measurement script and record real-screen foregrounds

**Why:** Confirms `parse_hierarchy` extracts the field correctly from real-device XMLs and documents what the model would see for each. Editing the M6 spec for measurements was the documented exception; the M22 spec has its own Measurements section reserved.

**Files:**
- Modify: `scripts/measure_perception.py`
- Modify: `docs/superpowers/specs/2026-05-23-v2-milestone-22-foreground-package-signal-design.md`

- [ ] **Step 1: Extend the measurement script.**

In `scripts/measure_perception.py`, inside the per-screen loop, add a line before the table print that surfaces the foreground:

```python
for name in SCREENS:
    xml = (fixtures / f"{name}.xml").read_text()
    obs_raw = parse_hierarchy(xml, viewport_filter=False)
    obs_vf = parse_hierarchy(xml, viewport_filter=True)
    print(f"## {name}")
    print(f"foreground: {obs_raw.foreground_package or '(none)'}")
    ...
```

- [ ] **Step 2: Run it.**

```
uv run python scripts/measure_perception.py | tee /tmp/m22-measurements.txt
```

- [ ] **Step 3: Paste the output into the M22 spec's Measurements section.**

Replace the placeholder under `## Measurements` with a fenced code block of the script's output and one short paragraph noting the foreground value for each screen.

- [ ] **Step 4: Commit.**

```
git add scripts/measure_perception.py docs/superpowers/specs/2026-05-23-v2-milestone-22-foreground-package-signal-design.md
git commit -m "tools: measure_perception.py prints foreground; record M22 measurements"
```

---

## Task 9: Documentation pass

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/configuration.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/architecture.md`.** In the rendering paragraph, extend the `ProseRenderer` description with one sentence: "When `perception.foreground_package` is on, a `# foreground: <package>` header line is prepended — a stable cross-turn signal for which app the model is currently in."

- [ ] **Step 2: `docs/configuration.md`.** Add a new row to the `perception` table:

```
| `foreground_package` | bool | `false` | Prepend `# foreground: <package>` to every rendered Observation. The package is the topmost `<node>` of the UIAutomator dump (the focused window). A/B with `androidharness peek --foreground-package` / `--no-foreground-package`. |
```

- [ ] **Step 3: `docs/roadmap.md`.** Append a new row to the v2 milestone table (after the existing M21):

```
| 22 | **Perception foreground-package signal** — `# foreground: <package>` header line; render-time only; defaults off; `peek --foreground-package` override | **Shipped** | <first> → <last> |
```

Find `<first>` and `<last>` via `git log --oneline <pre-M22-sha>..HEAD` after Task 8 lands. Also update the "Current focus" paragraph at the bottom of the file to mention M22 shipped.

- [ ] **Step 4: Commit.**

```
git add docs/architecture.md docs/configuration.md docs/roadmap.md
git commit -m "docs: M22 shipped — foreground-package signal documented across architecture, config, roadmap"
```

---

## Final verification

- [ ] **Step 1: Full test suite.**

```
uv run pytest -q
```

- [ ] **Step 2: Lint.**

```
uv run ruff check androidharness/ tests/
```

- [ ] **Step 3: Smoke against a real device.**

```
uv run androidharness peek --no-foreground-package > /tmp/before.txt
uv run androidharness peek --foreground-package    > /tmp/after.txt
diff -u /tmp/before.txt /tmp/after.txt | head -10
```

The diff should show exactly one new line at the top of `after.txt`: `# foreground: <whatever package the device's current screen is in>`.

- [ ] **Step 4: Real-task validation.** Flip `cfg.perception.foreground_package: true` in `~/.androidharness/config.yaml` and rerun the Binance task that motivated this milestone:

```
androidharness run "Open the Binance app, navigate to the P2P trading dashboard, ..."
```

Watch `runs/<id>/turns.jsonl` — the `observation_payload.text` field on every turn should now start with `# foreground: <pkg>`. The agent should be able to recognize when it has left `com.binance.dev` and either re-enter it or `done(success=False)` instead of thrashing on the launcher for 30 turns.

- [ ] **Step 5: Subagent dispatch review (recommended).** If executing via `superpowers:subagent-driven-development`, the two-stage review (spec compliance + code quality) runs per-task. A final reviewer pass over the full M22 commit range happens after Task 9.

---

## Risks & mitigations (recapped)

| Risk | Mitigation |
|---|---|
| Topmost `<node>` is not always the focused window (system overlays, transient popups). | UIAutomator's z-order convention is correct on virtually every screen; edge cases are addressed by a future per-node package annotation. |
| Header bytes break the M6 stall-detector invariant. | All three `obs.render(...)` callsites in `Agent.run` pass the same `foreground_package` value, just like `sibling_collapse`. Task 5 enforces this explicitly. |
| `# foreground: …` prefix syntax confuses the model. | Final verification Step 4 is the empirical check. Per-call escape is `peek --no-foreground-package` or flipping the YAML. |
| Existing `Observation(nodes=[...])` constructions break. | The new field defaults to `""`; the full suite must remain green at every task boundary. |
| Pydantic's `extra="forbid"` rejects existing configs. | The new flag has a default — Pydantic accepts configs that omit it. `uv run androidharness config show` post-Task 2 confirms the user's existing YAML still parses. |

---

## Sequencing summary

1. Task 1 — `Observation.foreground_package` field + `parse_hierarchy` extraction + 3 perception tests.
2. Task 2 — `PerceptionConfig.foreground_package` field + default-coverage assertion.
3. Task 3 — Renderer Protocol + ProseRenderer.observation accept kwarg AND implement the header + 4 render tests.
4. Task 4 — `Observation.render` threads the kwarg + 1 perception threading test.
5. Task 5 — `Agent` reads + threads the flag through all three `obs.render(...)` calls + 1 agent test.
6. Task 6 — `runner.run_task` + `run` CLI plumb the flag.
7. Task 7 — `peek` override flag + 2 peek tests.
8. Task 8 — Extend measurement script; record foreground values for the three reference fixtures.
9. Task 9 — Docs pass + mark Shipped on the roadmap.
