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

    @classmethod
    def ok(
        cls,
        data: T | None = None,
        *,
        msg: str | None = None,
        module: str | None = None,
        msg_key: str | None = None,
        lang: str | None = None,
        code: str = "ok",
        meta: dict | None = None,
        **kwargs,
    ) -> "ResponseModel[T]":
        """Construct a ResponseModel resolving localized message if module & msg_key are provided."""
        from app.common.response.messages import get_message

        if module and msg_key:
            resolved_msg = get_message(module, msg_key, lang=lang, default=msg, **kwargs)
        else:
            resolved_msg = msg or "success"
        return cls(code=code, msg=resolved_msg, data=data, meta=meta)


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
