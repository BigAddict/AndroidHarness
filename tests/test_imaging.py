from __future__ import annotations

import io

import pytest
from PIL import Image

from androidharness.imaging import quantize_png


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _gradient_rgb_png(width: int = 256, height: int = 256) -> bytes:
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (x, y, (x + y) % 256)
    return _png_bytes(img)


def _noisy_rgb_png(width: int = 256, height: int = 256) -> bytes:
    """A noisy RGB image with thousands of unique colors. Defeats PNG's own
    DEFLATE so quantization-down-to-256-colors is a real win."""
    import random

    rng = random.Random(42)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
    return _png_bytes(img)


def test_quantize_png_returns_valid_png_bytes():
    src = _gradient_rgb_png(64, 64)
    out = quantize_png(src)
    decoded = Image.open(io.BytesIO(out))
    decoded.load()
    assert decoded.size == (64, 64)


def test_quantize_png_reduces_size_on_color_rich_input():
    # Use noise so PNG's own compression can't compete; quantization to 256
    # colors should produce a meaningfully smaller file.
    src = _noisy_rgb_png(256, 256)
    out = quantize_png(src)
    assert len(out) < len(src)


def test_quantize_png_palette_image_uses_palette_mode():
    src = _gradient_rgb_png(32, 32)
    out = quantize_png(src)
    decoded = Image.open(io.BytesIO(out))
    assert decoded.mode == "P"


def test_quantize_png_accepts_rgba_input():
    img = Image.new("RGBA", (16, 16), (10, 20, 30, 255))
    src = _png_bytes(img)
    out = quantize_png(src)
    decoded = Image.open(io.BytesIO(out))
    decoded.load()
    assert decoded.size == (16, 16)


def test_quantize_png_rejects_non_png():
    from PIL import UnidentifiedImageError

    with pytest.raises(UnidentifiedImageError):
        quantize_png(b"not a png")
