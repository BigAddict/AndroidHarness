from __future__ import annotations

import io

from PIL import Image


def quantize_png(png_bytes: bytes) -> bytes:
    """Convert a PNG to a 256-color palette PNG to shrink token cost.

    Typical reduction is 30-50% for screen content. Quality loss is visible on
    photographic regions but negligible for app UI screenshots.
    """
    src = Image.open(io.BytesIO(png_bytes))
    src.load()
    if src.mode == "RGBA":
        src = src.convert("RGB")
    quantized = src.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    out = io.BytesIO()
    quantized.save(out, format="PNG", optimize=True)
    return out.getvalue()
