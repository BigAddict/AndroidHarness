"""Tests for androidharness/render.py — the rendering seam.

The split's main purpose is to let us swap formats experimentally. These
tests pin:
  1. ProseRenderer output (the contract every alternative must beat in a
     benchmark before it ships).
  2. Backward compat: Node.format / Observation.render delegate to the
     default renderer with no behavior change.
  3. The Renderer Protocol can be implemented by an alternative class —
     proves the seam is real.
"""

from __future__ import annotations

from androidharness.perception import Node, Observation
from androidharness.render import DEFAULT_RENDERER, ProseRenderer, Renderer


def _node(
    id: int = 1,
    cls: str = "android.widget.Button",
    text: str = "",
    content_desc: str = "",
    resource_id: str = "",
    clickable: bool = True,
    long_clickable: bool = False,
    scrollable: bool = False,
    editable: bool = False,
) -> Node:
    return Node(
        id=id,
        class_name=cls,
        text=text,
        content_desc=content_desc,
        resource_id=resource_id,
        bounds=(0, 0, 100, 100),
        clickable=clickable,
        long_clickable=long_clickable,
        scrollable=scrollable,
        editable=editable,
    )


def test_prose_renderer_button_with_text():
    r = ProseRenderer()
    assert r.node(_node(text="Settings")) == '[1] Button "Settings" (clickable)'


def test_prose_renderer_node_with_resource_id_when_requested():
    r = ProseRenderer()
    n = _node(text="Settings", resource_id="com.android.settings:id/settings_row")
    assert r.node(n, with_resource_id=True) == '[1] Button "Settings" #settings_row (clickable)'
    # By default the resource-id is hidden.
    assert "#settings_row" not in r.node(n)


def test_prose_renderer_editable_field_shows_placeholder_when_empty():
    r = ProseRenderer()
    field = _node(cls="android.widget.EditText", content_desc="Search", clickable=False, editable=True)
    assert r.node(field) == '[1] EditText placeholder="Search" (editable)'


def test_prose_renderer_editable_field_with_current_text():
    r = ProseRenderer()
    field = _node(cls="android.widget.EditText", text="hello", clickable=False, editable=True)
    assert r.node(field) == '[1] EditText "hello" (editable)'


def test_prose_renderer_observation_joins_node_lines_with_newline():
    r = ProseRenderer()
    obs = Observation(nodes=[_node(id=1, text="A"), _node(id=2, text="B")])
    rendered = r.observation(obs)
    assert rendered == '[1] Button "A" (clickable)\n[2] Button "B" (clickable)'


def test_default_renderer_is_a_prose_renderer():
    """If we ever change the default, every caller (the agent, the runner's
    NO_PROGRESS detector, observation_summary) is affected — keep this
    asserted so the change is intentional, not silent."""
    assert isinstance(DEFAULT_RENDERER, ProseRenderer)


def test_node_format_delegates_to_default_renderer():
    """Backward compat: Node.format() is a thin shim over the renderer.
    Any future renderer swap (via DI) doesn't have to touch Node."""
    n = _node(text="Settings", resource_id="com.android.settings:id/settings_row")
    assert n.format() == DEFAULT_RENDERER.node(n)
    assert n.format(with_resource_id=True) == DEFAULT_RENDERER.node(n, with_resource_id=True)


def test_observation_render_delegates_to_default_renderer():
    obs = Observation(nodes=[_node(id=1, text="A"), _node(id=2, text="B")])
    assert obs.render() == DEFAULT_RENDERER.observation(obs)
    assert obs.render(with_resource_ids=True) == DEFAULT_RENDERER.observation(
        obs, with_resource_id=True
    )


def test_renderer_protocol_accepts_a_custom_implementation():
    """The whole point of the split: a denser format can be a drop-in. This
    proves the Protocol surface is actually pluggable. Real candidates
    (TOON, YAML-columnar) will live in this module too once benchmarked."""

    class CompactRenderer:
        """Single-line-per-node, no spaces in traits, no quoted labels."""

        def node(self, n: Node, *, with_resource_id: bool = False) -> str:
            label = n.text or n.content_desc or "-"
            tag = f"#{n.resource_id.rsplit('/', 1)[-1]}" if with_resource_id and n.resource_id else ""
            return f"{n.id}:{n.short_class}:{label}{tag}"

        def observation(self, obs: Observation, *, with_resource_id: bool = False) -> str:
            return "\n".join(self.node(n, with_resource_id=with_resource_id) for n in obs.nodes)

    r: Renderer = CompactRenderer()
    n = _node(text="Settings")
    assert r.node(n) == "1:Button:Settings"
    obs = Observation(nodes=[n, _node(id=2, text="Wi-Fi")])
    assert r.observation(obs) == "1:Button:Settings\n2:Button:Wi-Fi"
