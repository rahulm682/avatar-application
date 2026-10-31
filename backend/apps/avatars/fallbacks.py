"""Images served when a user has no current avatar (design doc, section 9.2): the generic default and identicons.

Independent of Django so it is easy to test. Everything is generated with Pillow, so there are no image files to ship.
Results are cached in memory: the output only depends on (hash, size), and the CDN caches them as well.
"""
import colorsys
import io
from functools import lru_cache

from PIL import Image, ImageDraw

_SUPERSAMPLE = 4  # draw at 4x and shrink, for smooth edges at every size
DEFAULT_VERSION = "v1"  # bump when the default picture changes, so cached ETags no longer match


def _encode(image):
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", lossless=True, method=4)
    return buffer.getvalue()


@lru_cache(maxsize=16)
def default_image(size):
    """A neutral grey person silhouette."""
    big = size * _SUPERSAMPLE
    image = Image.new("RGB", (big, big), (226, 232, 240))
    draw = ImageDraw.Draw(image)
    figure = (148, 163, 184)
    cx = big / 2
    head_radius = big * 0.17
    head_cy = big * 0.38
    draw.ellipse((cx - head_radius, head_cy - head_radius, cx + head_radius, head_cy + head_radius), fill=figure)
    shoulders_half_width = big * 0.38
    shoulders_top = big * 0.62
    draw.ellipse(
        (cx - shoulders_half_width, shoulders_top, cx + shoulders_half_width, shoulders_top + big * 0.7), fill=figure
    )
    return _encode(image.resize((size, size), Image.Resampling.LANCZOS))


@lru_cache(maxsize=1024)
def identicon(email_hash, size):
    """A symmetric 5x5 pattern whose shape and colour are derived from the hash (always the same for one hash)."""
    digest = bytes.fromhex(email_hash)
    red, green, blue = colorsys.hls_to_rgb(digest[0] / 255, 0.5, 0.6)
    foreground = (int(red * 255), int(green * 255), int(blue * 255))

    big = size * _SUPERSAMPLE
    image = Image.new("RGB", (big, big), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    cell = big / 7  # a 5x5 pattern inside a one-cell margin
    for row in range(5):
        for col in range(3):  # left half plus the middle column; the right half is mirrored
            if digest[1 + row * 3 + col] % 2:
                continue
            for column in (col, 4 - col):
                left, top = (column + 1) * cell, (row + 1) * cell
                draw.rectangle((round(left), round(top), round(left + cell) - 1, round(top + cell) - 1), fill=foreground)
    return _encode(image.resize((size, size), Image.Resampling.LANCZOS))