from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass(frozen=True)
class Node:
    id: int
    class_name: str
    text: str
    content_desc: str
    resource_id: str
    bounds: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    clickable: bool
    long_clickable: bool
    scrollable: bool
    editable: bool
    # State flags from the XML the agent needs to be able to see:
    #   * enabled=False — control is greyed out, taps will not fire.
    #   * focused=True — this is where the keyboard / next type() lands.
    #   * checked=True — switches / radios / checkboxes in the on state.
    #   * password=True — secure input; the policy layer can gate on it.
    # All four default to "normal" so existing fixtures stay valid.
    enabled: bool = True
    focused: bool = False
    checked: bool = False
    password: bool = False

    @property
    def short_class(self) -> str:
        return self.class_name.rsplit(".", 1)[-1] if self.class_name else ""

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def format(self, *, with_resource_id: bool = False) -> str:
        # Delegate to the rendering module. Rendering is intentionally
        # decoupled so we can experiment with denser formats (TOON, columnar)
        # without touching perception.
        from androidharness.render import DEFAULT_RENDERER

        return DEFAULT_RENDERER.node(self, with_resource_id=with_resource_id)

    @property
    def summary(self) -> str:
        return self.format()


@dataclass
class Observation:
    nodes: list[Node] = field(default_factory=list)

    def resolve(self, node_id: int) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

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


def _parse_bounds(raw: str) -> tuple[int, int, int, int]:
    m = _BOUNDS_RE.match(raw or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(v) for v in m.groups())  # type: ignore[return-value]


def _attr_bool(elem: etree._Element, name: str) -> bool:
    return elem.get(name, "false") == "true"


def _is_editable(elem: etree._Element) -> bool:
    return "EditText" in elem.get("class", "")


def _is_interactable(elem: etree._Element) -> bool:
    return (
        _attr_bool(elem, "clickable")
        or _attr_bool(elem, "long-clickable")
        or _attr_bool(elem, "scrollable")
        or _is_editable(elem)
    )


def _own_label(elem: etree._Element) -> str:
    """Return the element's own text or content-desc (empty string if neither)."""
    return elem.get("text", "") or elem.get("content-desc", "") or ""


def _collect_descendant_text(elem: etree._Element) -> str:
    """Collect text from non-interactable descendants only.

    Depth-first traversal; first label wins per branch.
    """
    parts: list[str] = []
    for child in elem:
        if child.tag != "node":
            continue
        if _is_interactable(child):
            # Interactable descendants are independent nodes — don't absorb
            continue
        label = _own_label(child)
        if label:
            parts.append(label)
        else:
            deeper = _collect_descendant_text(child)
            if deeper:
                parts.append(deeper)
    return " ".join(parts)


def _is_offscreen(
    bounds: tuple[int, int, int, int],
    screen_rect: tuple[int, int, int, int] | None,
) -> bool:
    """A node is off-screen if its bounds are degenerate (zero or inverted
    area) or it sits fully outside the screen rect. When `screen_rect` is
    None, fall back to dropping only nodes fully above/left of the origin."""
    x1, y1, x2, y2 = bounds
    if x1 >= x2 or y1 >= y2:
        return True
    if screen_rect is None:
        return x2 <= 0 or y2 <= 0
    sx1, sy1, sx2, sy2 = screen_rect
    return x2 <= sx1 or y2 <= sy1 or x1 >= sx2 or y1 >= sy2


def parse_hierarchy(xml: str, *, viewport_filter: bool = False) -> Observation:
    root = etree.fromstring(xml.encode("utf-8"))
    obs = Observation()
    next_id = 1

    # When the viewport filter is on, take the screen rect from the top-level
    # window node (typical uiautomator dumps: first child of <hierarchy>).
    screen_rect: tuple[int, int, int, int] | None = None
    if viewport_filter:
        for child in root:
            if child.tag == "node":
                screen_rect = _parse_bounds(child.get("bounds", ""))
                break

    def walk(elem: etree._Element, *, suppress_text: bool) -> None:
        """
        Recursively process a node element.

        suppress_text:
            True only when this element is a non-interactable descendant whose
            text was already absorbed into a parent's label.  In that case we
            skip emitting a node for this element but still recurse into any
            children that are independently interactable (suppress_text resets
            to False for those children).
        """
        nonlocal next_id

        # Viewport filter: drop nodes that are degenerate, off-screen, or
        # explicitly visibility="gone". A `gone` subtree is dropped entirely
        # (children also do not lay out). Off-screen subtrees still recurse
        # in case a child re-enters the viewport — rare but harmless.
        if viewport_filter:
            if elem.get("visibility") == "gone":
                return
            if _is_offscreen(_parse_bounds(elem.get("bounds", "")), screen_rect):
                for child in elem:
                    if child.tag == "node":
                        walk(child, suppress_text=False)
                return

        interactable = _is_interactable(elem)
        own_label = _own_label(elem)
        editable = _is_editable(elem)

        if suppress_text and not interactable:
            # Text consumed by parent — skip this node, but let interactable
            # grandchildren through (suppress_text=False for them).
            for child in elem:
                if child.tag == "node":
                    walk(child, suppress_text=False)
            return

        # Determine effective label.
        if interactable and not own_label:
            effective_label = _collect_descendant_text(elem)
        else:
            effective_label = own_label

        has_label = bool(effective_label)

        if not (interactable or has_label):
            # Pure structural container — skip, recurse normally.
            for child in elem:
                if child.tag == "node":
                    walk(child, suppress_text=False)
            return

        # This node qualifies — emit it.
        own_text = elem.get("text", "") or ""
        own_content_desc = elem.get("content-desc", "") or ""

        # Three distinct cases for display_text:
        #   1. The element has its own text — use it directly.
        #   2. No own text, but also no content-desc — effective_label came
        #      from absorbed descendants; surface it as text.
        #   3. No own text, but has a content-desc — leave text empty so the
        #      content-desc field carries the label on its own.
        if own_text:
            display_text = own_text
        elif not own_content_desc:
            display_text = effective_label
        else:
            display_text = ""

        display_content_desc = own_content_desc

        node = Node(
            id=next_id,
            class_name=elem.get("class", ""),
            text=display_text,
            content_desc=display_content_desc,
            resource_id=elem.get("resource-id", "") or "",
            bounds=_parse_bounds(elem.get("bounds", "")),
            clickable=_attr_bool(elem, "clickable"),
            long_clickable=_attr_bool(elem, "long-clickable"),
            scrollable=_attr_bool(elem, "scrollable"),
            editable=editable,
            # `enabled` defaults to True in the XML when absent — same here.
            enabled=elem.get("enabled", "true") != "false",
            focused=_attr_bool(elem, "focused"),
            checked=_attr_bool(elem, "checked"),
            password=_attr_bool(elem, "password"),
        )
        obs.nodes.append(node)
        next_id += 1

        # Children of a node that absorbed descendant text should have their
        # non-interactable text nodes suppressed to avoid double-emission.
        absorbed = interactable and not own_label and bool(effective_label)

        for child in elem:
            if child.tag == "node":
                walk(child, suppress_text=absorbed)

    for child in root:
        if child.tag == "node":
            walk(child, suppress_text=False)

    return obs
