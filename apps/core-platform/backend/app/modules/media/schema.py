"""Transport schemas for the media module."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class AvatarOut(BaseModel):
    """Result of an avatar upload.

    ``avatar_urls`` maps every variant to its public URL, or ``None`` while that
    variant is still being generated — poll ``GET /api/me/profile`` until the
    values are filled in. ``original`` is available immediately.
    """

    media_id: UUID
    status: str
    avatar_urls: dict[str, str | None]
