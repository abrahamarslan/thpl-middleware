"""Request/response DTOs for the Zoho core layer (port of the PHP DTOs)."""

from typing import Any

from pydantic import BaseModel, Field


class ZohoPageContext(BaseModel):
    """Zoho's `page_context` node on every list response."""

    page: int = 1
    per_page: int = 200
    has_more_page: bool = False
    report_name: str | None = None
    sort_column: str | None = None
    sort_order: str | None = None


class ZohoResponse(BaseModel):
    """Normalised Zoho API response.

    `data` holds the resource payload with the envelope stripped, i.e. for
    GET /contacts it is the value of the "contacts" key, for GET /items/{id}
    the value of "item". Use `raw` when you need the untouched body.
    """

    request_id: str
    http_status: int
    zoho_code: int = 0
    message: str = ""
    data: Any = None
    page_context: ZohoPageContext | None = None
    raw: dict = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.zoho_code == 0 and 200 <= self.http_status < 300

    @classmethod
    def from_payload(cls, *, request_id: str, http_status: int, payload: dict) -> "ZohoResponse":
        envelope_keys = {"code", "message", "page_context", "instrumentation"}
        resource_keys = [k for k in payload if k not in envelope_keys]
        # Single resource key is the Zoho convention; fall back to full body
        data = payload[resource_keys[0]] if len(resource_keys) == 1 else (
            {k: payload[k] for k in resource_keys} or None
        )
        page_ctx = payload.get("page_context")
        return cls(
            request_id=request_id,
            http_status=http_status,
            zoho_code=int(payload.get("code", 0)),
            message=str(payload.get("message", "")),
            data=data,
            page_context=ZohoPageContext(**page_ctx) if isinstance(page_ctx, dict) else None,
            raw=payload,
        )
