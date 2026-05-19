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
