"""Outbound email provider adapters — the only place the app speaks SMTP/HTTP.

Everything above this layer (services, Celery tasks) hands an ``OutboundEmail``
value object to a provider and gets a ``ProviderResult`` back; no caller knows
the provider's HTTP shape, auth header, or payload quirks. Registering a new
provider is one ``register_provider`` line + a class with ``async def send`` —
callers never branch on provider (registries-over-conditionals doctrine).

``get_email_provider()`` is a lazy, process-wide factory so tests patch a
single symbol (``mocker.patch.object(provider, "get_email_provider")``) rather
than the network.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx
import structlog

from app.common.exception.errors import UpstreamError
from app.core.conf import settings

logger = structlog.get_logger("app.emails.provider")


class EmailProviderError(UpstreamError):
    """A mail provider rejected or could not complete the send (520-class)."""

    code = "email_provider_error"


@dataclass(slots=True)
class EmailAttachment:
    """Provider-neutral attachment. Bytes in, provider payload out."""

    filename: str
    content: bytes
    content_type: str | None = None
    content_id: str | None = None  # inline CID, e.g. "logo"

    def to_resend(self) -> dict:
        payload: dict = {
            "filename": self.filename,
            "content": base64.b64encode(self.content).decode(),
        }
        if self.content_type:
            payload["content_type"] = self.content_type
        if self.content_id:
            payload["content_id"] = self.content_id
        return payload


@dataclass(slots=True)
class OutboundEmail:
    """The provider-neutral message value object."""

    to: list[str]
    subject: str
    sender: str
    html: str | None = None
    text: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    tags: list[dict[str, str]] = field(default_factory=list)
    attachments: list[EmailAttachment] = field(default_factory=list)


@dataclass(slots=True)
class ProviderResult:
    provider: str
    message_id: str | None
    raw: dict


@runtime_checkable
class EmailProvider(Protocol):
    name: str

    async def send(self, message: OutboundEmail) -> ProviderResult: ...


class ResendProvider:
    """Resend (https://resend.com) over its REST API."""

    name = "resend"

    def __init__(self, *, api_key: str, api_url: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._timeout = timeout

    def _payload(self, message: OutboundEmail) -> dict:
        payload: dict = {
            "from": message.sender,
            "to": message.to,
            "subject": message.subject,
        }
        if message.html:
            payload["html"] = message.html
        if message.text:
            payload["text"] = message.text
        if message.cc:
            payload["cc"] = message.cc
        if message.bcc:
            payload["bcc"] = message.bcc
        if message.reply_to:
            payload["reply_to"] = message.reply_to
        if message.headers:
            payload["headers"] = message.headers
        if message.tags:
            payload["tags"] = message.tags
        if message.attachments:
            payload["attachments"] = [a.to_resend() for a in message.attachments]
        return payload

    async def send(self, message: OutboundEmail) -> ProviderResult:
        if not self._api_key:
            raise EmailProviderError("RESEND_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._api_url,
                json=self._payload(message),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        if response.status_code >= 400:
            raise EmailProviderError(
                f"Resend rejected the email ({response.status_code}): {response.text[:500]}"
            )
        data = response.json()
        return ProviderResult(provider=self.name, message_id=data.get("id"), raw=data)


# Provider registry: key -> factory(settings) -> EmailProvider.
ProviderFactory = Callable[[], "EmailProvider"]

_PROVIDERS: dict[str, ProviderFactory] = {}


def register_provider(key: str, factory: ProviderFactory) -> None:
    _PROVIDERS[key.lower()] = factory


def build_provider(key: str | None = None) -> EmailProvider:
    name = (key or settings.EMAIL_PROVIDER or "resend").lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise EmailProviderError(f"Unknown email provider: {name}")
    return factory()


register_provider(
    "resend",
    lambda: ResendProvider(
        api_key=settings.RESEND_API_KEY,
        api_url=settings.RESEND_API_URL,
        timeout=settings.EMAIL_TIMEOUT_SECONDS,
    ),
)


_provider: EmailProvider | None = None


def get_email_provider() -> EmailProvider:
    """Lazy process-wide provider singleton (the test patch point)."""
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider
