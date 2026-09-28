"""Declarative conversion specs, Spatie-style: a collection names the variants
it needs and the pipeline (app/tasks/media.py) produces each one independently."""

from __future__ import annotations

from typing import Literal, TypedDict


class ConversionSpec(TypedDict, total=False):
    width: int
    height: int
    fit: Literal["contain", "cover", "fill"]
    format: Literal["webp", "png", "jpeg"]
    quality: int


USER_AVATAR_CONVERSIONS: dict[str, ConversionSpec] = {
    "thumb":  {"width": 150, "height": 150, "fit": "cover", "format": "webp", "quality": 85},
    "medium": {"width": 400, "height": 400, "fit": "cover", "format": "webp", "quality": 88},
    "large":  {"width": 800, "height": 800, "fit": "cover", "format": "webp", "quality": 90},
}

#: Per-collection policy. ``visibility`` decides the bucket (and whether the
#: public router may ever serve the row); unknown collections are private.
COLLECTION_DEFAULTS: dict[str, dict] = {
    "avatar":    {"visibility": "public",  "conversions": USER_AVATAR_CONVERSIONS},
    "documents": {"visibility": "private", "conversions": {}},
}

AVATAR_COLLECTION = "avatar"
USER_MODEL_TYPE = "user"
