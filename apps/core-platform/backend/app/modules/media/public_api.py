"""Deliberately UNAUTHENTICATED router, mounted at ``/public/m`` (not under /api).

This is the one door in the system that is intentionally open, so it stays in
its own file and behind its own Traefik router (docker-compose.yml, label
``public-media``) — never merged into the authenticated API router. Any
application can embed a public image with a plain GET: no key, no session, no
CORS handling.

    <img src="https://<host>/public/m/{media_id}/medium">

Bytes are served from wherever the row says (``media.disk``), never from the
current ``MEDIA_STORAGE_DRIVER`` — so a URL issued under one driver keeps
working after the default changes.
"""

from __future__ import annotations

import re
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response

from app.database.db import async_session_factory
from app.modules.media.repository import get_media_by_uuid
from app.modules.media.storage import get_storage_provider
from app.modules.media.storage_common import content_type_for

logger = structlog.get_logger("app.media.public")

router = APIRouter(prefix="/public/m", tags=["public-media"])

# name, optionally followed by an extension: "medium" or "medium.webp"
_VARIANT_RE = re.compile(r"^(?P<name>[a-z0-9_-]{1,32})(?:\.(?P<ext>[a-z0-9]{2,5}))?$")

# Keys are content-addressed by media uuid: a replaced avatar gets a brand-new
# uuid and never overwrites this one, so the bytes behind a URL never change.
_IMMUTABLE = "public, max-age=31536000, immutable"

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Other applications embed these images; a default same-origin CORP would block that.
    "Cross-Origin-Resource-Policy": "cross-origin",
}


def _not_found() -> Response:
    # ALWAYS 404, never 403: a caller must not be able to tell "doesn't exist"
    # from "exists but private". no-store so an edge never caches a variant
    # that is merely not generated yet. Returned (not raised) on purpose: the
    # global HTTPException handler would drop the header and wrap the body in
    # the JSON envelope, which is noise for an image URL.
    return Response(status_code=404, headers={"Cache-Control": "no-store", **_HEADERS})


def _etag(media_id: UUID, variant: str) -> str:
    return f'"{media_id.hex}-{variant}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = {c.strip().removeprefix("W/") for c in if_none_match.split(",")}
    return "*" in candidates or etag in candidates


@router.api_route("/{media_id}/{variant}", methods=["GET", "HEAD"])
async def serve_public_media(media_id: str, variant: str, request: Request) -> Response:
    try:
        uid = UUID(media_id)
    except ValueError:
        return _not_found()
    m = _VARIANT_RE.match(variant)
    if m is None:
        return _not_found()
    name, requested_ext = m["name"], m["ext"]

    # A short-lived session: the connection goes back to the pool BEFORE the
    # (potentially slow) storage read below.
    async with async_session_factory() as db:
        media = await get_media_by_uuid(db, uid, all_tenants=True)      # public = no tenant context
    if media is None or media.visibility != "public":
        return _not_found()

    if name == "original":
        key = media.file_name
    else:
        info = (media.conversions or {}).get(name)
        if not info or info.get("status") != "done":
            return _not_found()
        key = info["file_name"]

    ext = key.rsplit(".", 1)[-1]
    if requested_ext is not None and requested_ext != ext:
        return _not_found()

    etag = _etag(uid, name)
    headers = {**_HEADERS, "Cache-Control": _IMMUTABLE, "ETag": etag}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    # Per-row disk, NOT the current env driver.
    try:
        body = await get_storage_provider(media.disk).read(key, visibility="public")
    except FileNotFoundError:
        logger.warning("public_media_bytes_missing", media_id=str(uid), variant=name, disk=media.disk)
        return _not_found()

    return Response(content=body, media_type=content_type_for(ext), headers=headers)
