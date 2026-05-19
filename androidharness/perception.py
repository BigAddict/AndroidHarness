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

    @property
    def short_class(self) -> str:
        return self.class_name.rsplit(".", 1)[-1] if self.class_name else ""

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def summary(self) -> str:
        traits: list[str] = []
        # Editable (EditText) subsumes clickable — don't double-list it
        if self.clickable and not self.editable:
            traits.append("clickable")
        if self.long_clickable:
            traits.append("long-clickable")
        if self.scrollable:
            traits.append("scrollable")
        if self.editable:
            traits.append("editable")
        traits_str = f" ({', '.join(traits)})" if traits else ""

        label_source = self.text or self.content_desc
        if self.editable and not self.text:
            label = f'placeholder="{self.content_desc}"' if self.content_desc else "(empty)"
        elif label_source:
            label = f'"{label_source}"'
        else:
            label = ""

        parts = [f"[{self.id}]", self.short_class]
        if label:
            parts.append(label)
        return (" ".join(parts) + traits_str).rstrip()


@dataclass
class Observation:
    nodes: list[Node] = field(default_factory=list)

    def resolve(self, node_id: int) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def render(self) -> str:
        return "\n".join(n.summary for n in self.nodes)


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
    """Collect text from non-interactable descendants only (depth-first, first label wins per branch)."""
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


def parse_hierarchy(xml: str) -> Observation:
    root = etree.fromstring(xml.encode("utf-8"))
    obs = Observation()
    next_id = 1

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
