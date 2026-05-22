"""Form helpers.

HTML forms can't natively post nested JSON. We use dotted keys
(`policy.default_mode`) and un-flatten them server-side before handing to
Pydantic for validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FormError(ValueError):
    """Raised when a posted form is structurally inconsistent (e.g., key collision)."""


def unflatten(flat: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        node: dict[str, Any] = out
        for part in parts[:-1]:
            existing = node.get(part)
            if existing is None:
                existing = {}
                node[part] = existing
            elif not isinstance(existing, dict):
                raise FormError(
                    f"form key collision: {part!r} is both a leaf and a parent (key={key!r})"
                )
            node = existing
        if value == "":
            # Empty field: ensure the parent dict exists but don't set the leaf.
            continue
        leaf = parts[-1]
        if isinstance(node.get(leaf), dict):
            raise FormError(
                f"form key collision: {leaf!r} cannot be both a value and a parent"
            )
        node[leaf] = value
    return out


__all__ = ["FormError", "unflatten"]
