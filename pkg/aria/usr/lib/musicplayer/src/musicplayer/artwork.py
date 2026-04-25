"""Artwork presentation helpers."""

from __future__ import annotations

from pathlib import Path

from gi.repository import GdkPixbuf


def load_pixbuf(path: str, size: int) -> GdkPixbuf.Pixbuf | None:
    """Load artwork into a constrained pixbuf."""
    if not path or not Path(path).exists():
        return None
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)


def dominant_color_css(path: str) -> str:
    """Derive a simple dominant color for hero backgrounds."""
    pixbuf = load_pixbuf(path, 32)
    if pixbuf is None:
        return "rgba(60, 60, 60, 0.18)"

    pixels = pixbuf.get_pixels()
    stride = pixbuf.get_rowstride()
    width = pixbuf.get_width()
    height = pixbuf.get_height()
    channels = pixbuf.get_n_channels()
    red = green = blue = count = 0

    for y in range(height):
        for x in range(width):
            offset = y * stride + x * channels
            red += pixels[offset]
            green += pixels[offset + 1]
            blue += pixels[offset + 2]
            count += 1

    if count == 0:
        return "rgba(60, 60, 60, 0.18)"

    return f"rgba({red // count}, {green // count}, {blue // count}, 0.20)"
