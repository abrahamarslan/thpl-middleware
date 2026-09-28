"""Image builders shared by the media tests."""

import io

from PIL import Image

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def gps_exif(orientation: int | None = None) -> Image.Exif:
    """EXIF carrying a GPS position (Bengaluru) and optionally an orientation."""
    exif = Image.Exif()
    gps = exif.get_ifd(GPS_IFD)
    gps[1], gps[2] = "N", (12.0, 58.0, 0.0)
    gps[3], gps[4] = "E", (77.0, 35.0, 0.0)
    if orientation is not None:
        exif[ORIENTATION] = orientation
    return exif


def make_jpeg(size=(60, 40), *, gps: bool = True, orientation: int | None = None, color=(200, 40, 40)) -> bytes:
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    kwargs = {"exif": gps_exif(orientation)} if gps else {}
    img.save(out, format="JPEG", **kwargs)
    return out.getvalue()


def make_png(size=(60, 40), *, alpha: bool = False, color=(20, 120, 220)) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", size, (*color, 128) if alpha else color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def make_webp(size=(60, 40), *, gps: bool = False) -> bytes:
    img = Image.new("RGB", size, (30, 200, 90))
    out = io.BytesIO()
    kwargs = {"exif": gps_exif()} if gps else {}
    img.save(out, format="WEBP", **kwargs)
    return out.getvalue()


def make_huge_png(pixels_over: int = 48_000_000) -> bytes:
    """A PNG whose DECLARED size exceeds the 40 MP limit, cheap to build: a
    1-bit image compresses to a few KB (48 MP of mode '1' is only 6 MB in memory)."""
    width = 8000
    img = Image.new("1", (width, pixels_over // width), 0)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


def has_exif_gps(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as img:
        exif = img.getexif()
        return bool(exif.get_ifd(GPS_IFD)) or GPS_IFD in exif


def has_any_exif(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as img:
        return len(img.getexif()) > 0 or "exif" in img.info
