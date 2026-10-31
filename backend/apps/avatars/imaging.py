"""Image validation and processing (design doc, section 8).

Deliberately independent of Django so it is easy to test: limits are passed in by the caller.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

# Formats accepted from users, detected from the file CONTENT (never from the file name or the browser's claim).
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_CONTENT_TYPES = tuple(ALLOWED_FORMATS.values())

_READ_ERRORS = (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError, EOFError)


class InvalidImage(Exception):
    """The uploaded file cannot be accepted. The message is safe to show to the user."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int


def _to_rgb_or_rgba(image):
    if image.mode in ("RGB", "RGBA"):
        return image
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    return image.convert("RGBA" if has_alpha else "RGB")


def process_upload(data, max_dimension, quality=95):
    """Validates an uploaded image and returns a clean, full-size WebP.

    - the format must be JPEG, PNG or WebP (checked from the content)
    - width and height must not exceed max_dimension (checked BEFORE decoding, against decompression bombs)
    - the EXIF orientation is applied, then re-encoding drops all metadata (GPS location, camera info, ...)
    """
    try:
        image = Image.open(io.BytesIO(data))
    except _READ_ERRORS:
        raise InvalidImage("The file is not a valid image.") from None

    if image.format not in ALLOWED_FORMATS:
        raise InvalidImage("Only JPEG, PNG and WebP images are accepted.")

    width, height = image.size
    if width > max_dimension or height > max_dimension:
        raise InvalidImage(f"The image is too large (at most {max_dimension} x {max_dimension} pixels).")

    try:
        image.load()  # full decode: catches truncated or damaged files
        image = ImageOps.exif_transpose(image)
    except _READ_ERRORS:
        raise InvalidImage("The image could not be read. It may be damaged.") from None

    image = _to_rgb_or_rgba(image)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=4)  # no exif/icc passed, so metadata is dropped
    return ProcessedImage(buffer.getvalue(), image.width, image.height)


def make_square(data, size, quality=80):
    """Center-crops an image to a square and resizes it to size x size, as WebP."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        square = ImageOps.fit(_to_rgb_or_rgba(image), (size, size), method=Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        square.save(buffer, format="WEBP", quality=quality, method=4)
        return buffer.getvalue()