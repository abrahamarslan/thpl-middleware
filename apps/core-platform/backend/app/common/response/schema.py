"""Unified success envelope (mirrors the error envelope in exception handlers)."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    code: str = "ok"
    msg: str = "success"
    data: T | None = None
    request_id: str | None = None
    meta: dict | None = None


class PageModel(BaseModel, Generic[T]):
    items: list[T]
    # Legacy offset pagination (keep for simple UI tables)
    page: int | None = None
    page_size: int
    total: int | None = None
    has_more: bool = False
    # Modern cursor pagination (for infinite scrolling / mobile apps)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
