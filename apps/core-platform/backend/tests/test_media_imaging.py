"""Pillow layer of the media module: validation, EXIF/GPS strip, variant rendering. Hermetic."""

import io

import pytest
from PIL import Image

from app.modules.media.conversions import USER_AVATAR_CONVERSIONS
from app.modules.media.imaging import InvalidImageError, render_variant, sanitize_original
from tests.media_helpers import (
    has_any_exif,
    has_exif_gps,
    make_huge_png,
    make_jpeg,
    make_png,
    make_webp,
)


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


# ── sanitising the original ──────────────────────────────────────────────────

def test_jpeg_gps_exif_is_stripped_from_the_stored_original():
    raw = make_jpeg(gps=True)
    assert has_exif_gps(raw), "fixture must actually carry GPS"

    clean = sanitize_original(raw)

    assert clean.ext == "jpeg" and clean.mime_type == "image/jpeg"
    assert not has_exif_gps(clean.data)
    assert not has_any_exif(clean.data)
    assert b"Exif" not in clean.data


def test_webp_exif_is_stripped_too():
    raw = make_webp(gps=True)
    assert has_exif_gps(raw)
    clean = sanitize_original(raw)
    assert clean.ext == "webp"
    assert not has_exif_gps(clean.data) and not has_any_exif(clean.data)


def test_orientation_is_baked_into_the_pixels_before_metadata_is_dropped():
    """Dropping EXIF without applying it would turn every phone portrait sideways."""
    raw = make_jpeg(size=(60, 40), gps=True, orientation=6)          # 6 = rotate 90° CW on display
    clean = sanitize_original(raw)
    assert (clean.width, clean.height) == (40, 60)
    assert _size(clean.data) == (40, 60)


def test_png_transparency_survives_sanitising():
    clean = sanitize_original(make_png(alpha=True))
    with Image.open(io.BytesIO(clean.data)) as img:
        assert img.mode == "RGBA"


def test_format_comes_from_the_bytes_not_from_the_claimed_type():
    # a PNG payload is still a PNG whatever the client's Content-Type said
    assert sanitize_original(make_png()).mime_type == "image/png"


def test_more_than_40_megapixels_is_rejected():
    huge = make_huge_png()
    with Image.open(io.BytesIO(huge)) as probe:
        assert probe.width * probe.height > 40_000_000       # 1x-2x the limit: Pillow would only WARN
    with pytest.raises(InvalidImageError, match="megapixels"):
        sanitize_original(huge)


@pytest.mark.parametrize("payload", [b"", b"not an image at all", b"GIF89a" + b"\x00" * 32, b"\xff\xd8\xff" + b"\x00" * 8])
def test_garbage_is_rejected(payload):
    with pytest.raises(InvalidImageError):
        sanitize_original(payload)


def test_a_truncated_image_fails_here_not_later_in_celery():
    good = make_png(size=(400, 400))
    with pytest.raises(InvalidImageError):
        sanitize_original(good[: len(good) // 2])


def test_gif_is_not_an_allowed_type():
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(out, format="GIF")
    with pytest.raises(InvalidImageError, match="unsupported"):
        sanitize_original(out.getvalue())


# ── conversion variants ──────────────────────────────────────────────────────

@pytest.mark.parametrize(("name", "side"), [("thumb", 150), ("medium", 400), ("large", 800)])
def test_avatar_variants_are_square_webp(name, side):
    source = sanitize_original(make_jpeg(size=(900, 600), gps=False)).data
    data, w, h = render_variant(source, USER_AVATAR_CONVERSIONS[name])
    assert (w, h) == (side, side) == _size(data)
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "WEBP"


def test_fit_modes():
    source = make_png(size=(200, 100))
    _, w, h = render_variant(source, {"width": 50, "height": 50, "fit": "cover", "format": "png"})
    assert (w, h) == (50, 50)
    _, w, h = render_variant(source, {"width": 50, "height": 50, "fit": "contain", "format": "png"})
    assert (w, h) == (50, 25)                                   # aspect preserved, fits the box
    _, w, h = render_variant(source, {"width": 50, "height": 70, "fit": "fill", "format": "png"})
    assert (w, h) == (50, 70)


def test_contain_never_upscales():
    _, w, h = render_variant(make_png(size=(20, 10)), {"width": 500, "height": 500, "fit": "contain", "format": "png"})
    assert (w, h) == (20, 10)


def test_jpeg_output_is_flattened_and_png_webp_keep_alpha():
    src = make_png(size=(40, 40), alpha=True)
    for fmt, expect_alpha in (("jpeg", False), ("png", True), ("webp", True)):
        data, _, _ = render_variant(src, {"width": 20, "height": 20, "fit": "cover", "format": fmt})
        with Image.open(io.BytesIO(data)) as img:
            assert ("A" in img.getbands()) is expect_alpha, fmt


def test_unknown_fit_and_format_are_errors():
    with pytest.raises(ValueError):
        render_variant(make_png(), {"width": 10, "height": 10, "fit": "zoom", "format": "png"})
    with pytest.raises(ValueError):
        render_variant(make_png(), {"width": 10, "height": 10, "fit": "cover", "format": "bmp"})   # type: ignore[typeddict-item]


def test_variants_carry_no_metadata():
    source = make_jpeg(gps=True)                                # NOT sanitised: the worker must not leak either
    data, _, _ = render_variant(source, {"width": 30, "height": 30, "fit": "cover", "format": "jpeg"})
    assert not has_any_exif(data)
