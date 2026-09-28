"""Pillow processing — pure functions over bytes, no I/O.

Used twice: the API sanitises the ORIGINAL before persisting it (validation,
EXIF/GPS strip, orientation bake-in), and the Celery worker renders each
conversion variant from that original.

Pillow's own ``MAX_IMAGE_PIXELS`` only *warns* at 1x the limit and raises at
2x, so the guard below checks the declared dimensions explicitly — a 60 MP
upload must be rejected, not merely warned about.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.modules.media.conversions import ConversionSpec

MAX_SOURCE_PIXELS = 40_000_000  # ~40 MP: decompression-bomb guard

# Still set the library-wide limit so a code path that forgets the explicit
# check is at least caught at 2x instead of being unbounded.
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS

#: Pillow format -> (extension used in storage keys, mime type)
ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpeg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}

_SAVE_FORMAT = {"webp": "WEBP", "png": "PNG", "jpeg": "JPEG"}
_MIME = {"webp": "image/webp", "png": "image/png", "jpeg": "image/jpeg"}


class InvalidImageError(ValueError):
    """The bytes are not an acceptable image (undecodable, wrong type, too large)."""


@dataclass(frozen=True, slots=True)
class SanitizedImage:
    data: bytes
    ext: str
    mime_type: str
    width: int
    height: int


def mime_for_format(fmt: str) -> str:
    return _MIME[fmt]


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def _flatten_for(img: Image.Image, out_format: str) -> Image.Image:
    """Colour mode the target format can store. JPEG has no alpha; PNG/WebP keep it."""
    if out_format != "jpeg" and _has_alpha(img):
        return img.convert("RGBA")
    return img.convert("RGB")


def _encode(img: Image.Image, out_format: str, quality: int) -> bytes:
    out = io.BytesIO()
    # Deliberately NO exif= / icc_profile= / pnginfo=: nothing from the source
    # metadata is carried into the output.
    if out_format == "png":
        img.save(out, format="PNG", optimize=True)
    elif out_format == "jpeg":
        img.save(out, format="JPEG", quality=quality, optimize=True)
    else:
        img.save(out, format="WEBP", quality=quality)
    return out.getvalue()


def _open_checked(raw: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as e:
        raise InvalidImageError("image is too large") from e
    except Exception as e:  # noqa: BLE001 — anything Pillow cannot identify is "not an image"
        raise InvalidImageError("invalid or unsupported image file") from e
    if img.format not in ALLOWED_FORMATS:
        img.close()
        raise InvalidImageError(f"unsupported image type: {img.format}")
    if img.width * img.height > MAX_SOURCE_PIXELS:
        img.close()
        raise InvalidImageError(f"image exceeds {MAX_SOURCE_PIXELS // 1_000_000} megapixels")
    return img


def sanitize_original(raw: bytes) -> SanitizedImage:
    """Validate an upload and return a clean re-encode of it.

    * decodes the WHOLE image, so truncated/corrupt files fail here and not
      later inside a Celery task (``Image.verify()`` does not decode pixels);
    * bakes the EXIF orientation into the pixels, then drops ALL metadata —
      field-staff phone photos routinely carry GPS, and the original is served
      as-is at ``/original``;
    * the format comes from the bytes, never from the client's Content-Type.
    """
    img = _open_checked(raw)
    try:
        ext, mime = ALLOWED_FORMATS[img.format]
        try:
            img.load()
            img = ImageOps.exif_transpose(img)
        except Exception as e:  # noqa: BLE001 — truncated / corrupt pixel data
            raise InvalidImageError("invalid or corrupt image file") from e
        clean = _flatten_for(img, ext)
        clean.info = {}
        data = _encode(clean, ext, quality=92)
        return SanitizedImage(data=data, ext=ext, mime_type=mime, width=clean.width, height=clean.height)
    finally:
        img.close()


def render_variant(source: bytes, spec: ConversionSpec) -> tuple[bytes, int, int]:
    """One conversion variant of ``source``. Returns (bytes, width, height)."""
    out_format = spec.get("format", "webp")
    if out_format not in _SAVE_FORMAT:
        raise ValueError(f"unknown output format: {out_format}")
    target_w, target_h = spec["width"], spec["height"]
    fit = spec.get("fit", "cover")

    img = _open_checked(source)
    try:
        img.load()
        img = ImageOps.exif_transpose(img)
        img = _flatten_for(img, out_format)
        if fit == "cover":
            img = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)
        elif fit == "contain":
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        elif fit == "fill":
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        else:
            raise ValueError(f"unknown fit mode: {fit}")
        return _encode(img, out_format, quality=spec.get("quality", 85)), img.width, img.height
    finally:
        img.close()
