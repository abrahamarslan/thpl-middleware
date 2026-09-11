"""Identifier resolution: email | username | phone -> local user.

Login and password reset both accept a single ``identifier``; this is the one
place that decides which column to match. Order is shape-driven (an '@' means
email, a phone-shaped string means phone) with a username fallback, and it
never leaks which column matched.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users import crud
from app.modules.users.model import User

_PHONE_SHAPE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,}$")


def looks_like_email(value: str) -> bool:
    return "@" in value


def looks_like_phone(value: str) -> bool:
    if not _PHONE_SHAPE.match(value.strip()):
        return False
    return len(re.sub(r"\D", "", value)) >= 7


def normalize_phone(value: str) -> str:
    return re.sub(r"[^\d+]", "", value)


async def resolve_user_by_identifier(
    db: AsyncSession, identifier: str, *, include_deleted: bool = False
) -> User | None:
    value = (identifier or "").strip()
    if not value:
        return None
    if looks_like_email(value):
        user = await crud.get_by_email(db, value, include_deleted=include_deleted)
        if user is not None:
            return user
    if looks_like_phone(value):
        user = await crud.get_by_phone(db, value, include_deleted=include_deleted)
        if user is None:
            user = await crud.get_by_phone(db, normalize_phone(value), include_deleted=include_deleted)
        if user is not None:
            return user
    return await crud.get_by_username(db, value)
