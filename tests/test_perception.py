from pathlib import Path

import pytest

from androidharness.perception import Node, parse_hierarchy

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_hierarchy_keeps_interactable_and_text_nodes():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    summaries = [n.summary for n in obs.nodes]
    assert summaries == [
        '[1] Button "Settings" (clickable)',
        '[2] Button "Wi-Fi" (clickable)',
        '[3] EditText placeholder="Search" (editable)',
        '[4] TextView "Welcome back"',
    ]


def test_parse_hierarchy_assigns_dense_ids_starting_at_one():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    assert [n.id for n in obs.nodes] == [1, 2, 3, 4]


def test_observation_resolve_returns_node_for_known_id():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    node = obs.resolve(1)
    assert isinstance(node, Node)
    assert node.text == "Settings"


def test_observation_resolve_raises_for_unknown_id():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    with pytest.raises(KeyError):
        obs.resolve(99)


def test_node_center_is_midpoint_of_bounds():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    node = obs.resolve(1)  # bounds=[40,200][520,320]
    assert node.center == (280, 260)


def test_settings_fixture_drops_pure_layout_containers():
    obs = parse_hierarchy(_load("hierarchy_settings.xml"))
    summaries = [n.summary for n in obs.nodes]
    assert summaries == [
        '[1] TextView "Settings"',
        "[2] RecyclerView (scrollable)",
        '[3] LinearLayout "Network & internet" (clickable)',
        '[4] LinearLayout "Display" (clickable)',
        '[5] LinearLayout "About phone" (clickable, long-clickable)',
    ]


def test_observation_render_is_newline_joined_summaries():
    obs = parse_hierarchy(_load("hierarchy_minimal.xml"))
    rendered = obs.render()
    assert rendered.splitlines() == [n.summary for n in obs.nodes]


def test_empty_hierarchy_produces_empty_observation():
    xml = "<hierarchy rotation='0'></hierarchy>"
    obs = parse_hierarchy(xml)
    assert obs.nodes == []
    assert obs.render() == ""


# -- Viewport filter (spec §7 step 2) -----------------------------------------

_OFFSCREEN_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Visible" clickable="true"/>
    <node bounds="[0,0][0,0]" class="android.widget.Button" text="Degenerate" clickable="true"/>
    <node bounds="[40,-100][520,-50]" class="android.widget.Button" text="Above" clickable="true"/>
    <node bounds="[40,2500][520,2600]" class="android.widget.Button" text="Below" clickable="true"/>
    <node bounds="[-200,200][-50,300]" class="android.widget.Button" text="Left" clickable="true"/>
    <node bounds="[1200,200][1400,300]" class="android.widget.Button" text="Right" clickable="true"/>
    <node bounds="[40,400][520,500]" class="android.widget.Button" text="Hidden" visibility="gone" clickable="true"/>
  </node>
</hierarchy>
"""


def test_viewport_filter_off_by_default_keeps_offscreen_nodes():
    obs = parse_hierarchy(_OFFSCREEN_XML)
    texts = [n.text for n in obs.nodes]
    # Without the filter, every clickable child shows up (degenerate still emits
    # — current behavior — because the existing renderer doesn't drop them).
    assert "Visible" in texts
    assert "Above" in texts
    assert "Below" in texts


def test_viewport_filter_drops_degenerate_bounds():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Degenerate" not in texts


def test_viewport_filter_drops_nodes_fully_above_screen():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Above" not in texts


def test_viewport_filter_drops_nodes_fully_below_screen():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Below" not in texts


def test_viewport_filter_drops_nodes_fully_left_of_screen():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Left" not in texts


def test_viewport_filter_drops_nodes_fully_right_of_screen():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Right" not in texts


def test_viewport_filter_drops_visibility_gone():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Hidden" not in texts


def test_viewport_filter_keeps_onscreen_node():
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Visible" in texts


def test_viewport_filter_keeps_partially_offscreen_node():
    """A node that has some pixels above the screen but extends down into the
    viewport must NOT be dropped — its center may still be on-screen."""
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout">
    <node bounds="[40,-10][520,100]" class="android.widget.Button" text="Partial" clickable="true"/>
  </node>
</hierarchy>
"""
    obs = parse_hierarchy(xml, viewport_filter=True)
    texts = [n.text for n in obs.nodes]
    assert "Partial" in texts


def test_viewport_filter_dense_ids_after_drops():
    """Ids must remain dense (1, 2, 3, ...) after off-screen nodes are filtered."""
    obs = parse_hierarchy(_OFFSCREEN_XML, viewport_filter=True)
    ids = [n.id for n in obs.nodes]
    assert ids == list(range(1, len(ids) + 1))


# -- Resource-id in render (spec §7 step 3) -----------------------------------

_WITH_RESOURCE_IDS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings"
          resource-id="com.android.settings:id/settings_row" clickable="true"/>
    <node bounds="[40,360][520,480]" class="android.widget.EditText"
          resource-id="com.android.settings:id/search_box" content-desc="Search" clickable="true"/>
    <node bounds="[40,520][520,640]" class="android.widget.Button" text="No-Resource"
          clickable="true"/>
  </node>
</hierarchy>
"""


def test_node_summary_property_unchanged_omits_resource_id():
    """`Node.summary` is the legacy property — must NOT include resource-id so
    existing callers keep working."""
    obs = parse_hierarchy(_WITH_RESOURCE_IDS_XML)
    n = obs.nodes[0]
    assert "#settings_row" not in n.summary
    assert n.summary == '[1] Button "Settings" (clickable)'


def test_node_format_with_resource_id_inserts_short_id_before_traits():
    obs = parse_hierarchy(_WITH_RESOURCE_IDS_XML)
    n = obs.nodes[0]
    assert n.format(with_resource_id=True) == '[1] Button "Settings" #settings_row (clickable)'


def test_node_format_without_resource_id_attribute_omits_marker():
    obs = parse_hierarchy(_WITH_RESOURCE_IDS_XML)
    no_rid = obs.nodes[2]
    assert no_rid.resource_id == ""
    assert "#" not in no_rid.format(with_resource_id=True)


def test_observation_render_with_resource_ids_uses_short_form_per_node():
    obs = parse_hierarchy(_WITH_RESOURCE_IDS_XML)
    rendered = obs.render(with_resource_ids=True)
    lines = rendered.splitlines()
    assert lines[0] == '[1] Button "Settings" #settings_row (clickable)'
    # Second node: EditText with content-desc but no own text.
    assert "#search_box" in lines[1]
    # Third node has no resource-id — line unchanged
    assert "#" not in lines[2]


def test_observation_render_default_omits_resource_ids():
    obs = parse_hierarchy(_WITH_RESOURCE_IDS_XML)
    rendered = obs.render()
    assert "#settings_row" not in rendered
    assert "#search_box" not in rendered


def test_short_resource_id_handles_missing_slash():
    """If `resource-id` has no slash (rare but possible), use it verbatim."""
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="X"
          resource-id="plain_id" clickable="true"/>
  </node>
</hierarchy>
"""
    obs = parse_hierarchy(xml)
    assert obs.nodes[0].format(with_resource_id=True) == '[1] Button "X" #plain_id (clickable)'
