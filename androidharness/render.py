"""Observation rendering — the seam between the typed perception layer and
the text the LLM actually sees.

`perception.py` produces `Node` / `Observation` dataclasses. This module
turns them into the string form the agent puts in `contents`. Splitting
rendering out lets us experiment with denser formats (TOON, YAML-columnar,
JSON-lines, …) without touching the perception logic. New formats subclass
`Renderer`; ship one only after a fixture-driven benchmark proves both a
token-count win and no tool-call accuracy regression.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from androidharness.perception import Node, Observation


class Renderer(Protocol):
    """Strategy for turning Observations into the text the LLM sees.

    Implementations must be pure functions of the Observation — no I/O, no
    device access. The contract:
      * `node(n, with_resource_id)` returns the single-node form used as the
        `summary` for diagnostic output.
      * `observation(obs, with_resource_id)` returns the full Observation
        rendered as one string. Typically newline-joined `node(...)` calls,
        but a renderer is free to add headers, group by container, etc.
    """

    def node(self, n: Node, *, with_resource_id: bool = False) -> str: ...

    def observation(self, obs: Observation, *, with_resource_id: bool = False) -> str: ...


class ProseRenderer:
    """The format the agent has used since v1. Each node is one line:
        [id] ClassName "label" #resource_id (traits)
    Resource-id and traits are optional. This is intentionally prose-y —
    LLMs handle it well and it doubles as something a human can scan.
    """

    def node(self, n: Node, *, with_resource_id: bool = False) -> str:
        traits: list[str] = []
        # Editable (EditText) subsumes clickable — don't double-list it
        if n.clickable and not n.editable:
            traits.append("clickable")
        if n.long_clickable:
            traits.append("long-clickable")
        if n.scrollable:
            traits.append("scrollable")
        if n.editable:
            traits.append("editable")
        # State traits — only surface when non-default so they cost zero
        # bytes on the typical screen but pop visibly when they matter.
        if not n.enabled:
            traits.append("disabled")
        if n.focused:
            traits.append("focused")
        if n.checked:
            traits.append("checked")
        if n.password:
            traits.append("password")
        traits_str = f" ({', '.join(traits)})" if traits else ""

        label_source = n.text or n.content_desc
        if n.editable and not n.text:
            label = f'placeholder="{n.content_desc}"' if n.content_desc else "(empty)"
        elif label_source:
            label = f'"{label_source}"'
        else:
            label = ""

        parts = [f"[{n.id}]", n.short_class]
        if label:
            parts.append(label)

        if with_resource_id and n.resource_id:
            rid = n.resource_id
            short = rid.rsplit("/", 1)[-1] if "/" in rid else rid
            parts.append(f"#{short}")

        return (" ".join(parts) + traits_str).rstrip()

    def observation(self, obs: Observation, *, with_resource_id: bool = False) -> str:
        return "\n".join(self.node(n, with_resource_id=with_resource_id) for n in obs.nodes)


# The agent and every test rely on this concrete default. Replace via DI
# (e.g. Agent(..., renderer=...)) when experimenting with alternatives.
DEFAULT_RENDERER: Renderer = ProseRenderer()
