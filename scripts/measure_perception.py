"""Manual dev tool — measure rendering size with and without each compression
flag. Not part of the package; not tested. Run from the repo root:

    uv run python scripts/measure_perception.py
"""

from __future__ import annotations

from pathlib import Path

from androidharness.perception import parse_hierarchy
from androidharness.render import DEFAULT_RENDERER

SCREENS = ["settings_list", "app_drawer", "notification_shade"]


def render(obs, *, resource_ids: bool, sibling_collapse: bool) -> str:
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
                text = render(obs, resource_ids=False, sibling_collapse=sc)
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
