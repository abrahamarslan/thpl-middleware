"""Client request audit context: IP, device and GeoIP location.

One reusable dependency (``ClientInfoDep``) gives auth endpoints the
"who/where/from-what" facts security emails and audit logs need. Device
parsing is a small, testable local parser (no extra dependency); location
comes from :mod:`app.common.geoip` and is simply absent when GeoIP is off.

The IP resolution is the single source of truth also used by the request
middleware, so logs and emails never disagree about the caller's address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from app.common.geoip import GeoLocation, lookup_ip

_BROWSERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Tarrina|THApp", re.IGNORECASE), "Tarrina App"),
    (re.compile(r"Edg/"), "Edge"),
    (re.compile(r"OPR/|Opera"), "Opera"),
    (re.compile(r"CriOS/"), "Chrome"),
    (re.compile(r"Chrome/"), "Chrome"),
    (re.compile(r"Firefox/"), "Firefox"),
    (re.compile(r"Version/.*Safari"), "Safari"),
    (re.compile(r"curl/|Wget/|python-httpx|okhttp|Dart"), "API client"),
)

_OPERATING_SYSTEMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Windows NT 10"), "Windows"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"iPhone|iPad|iPod"), "iOS"),
    (re.compile(r"Mac OS X"), "macOS"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"Linux"), "Linux"),
)


def client_ip_from_request(request: Request) -> str | None:
    """Best-effort real client IP (shared by middleware and dependencies).

    Traefik sets ``X-Forwarded-For`` (left-most entry = original client);
    fall back to ``X-Real-IP`` then the socket peer for dev/direct access.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def parse_user_agent(user_agent: str | None) -> str:
    """'<Browser> on <OS>' — e.g. 'Chrome on macOS'. Bounded and testable."""
    if not user_agent:
        return "Unknown device"
    browser = next((name for pattern, name in _BROWSERS if pattern.search(user_agent)), None)
    os_name = next((name for pattern, name in _OPERATING_SYSTEMS if pattern.search(user_agent)), None)
    if browser and os_name:
        return f"{browser} on {os_name}"
    return browser or os_name or "Unknown device"


def format_utc(moment: datetime | None = None) -> str:
    """'September 10, 2026, 21:30 UTC' (platform-independent, no leading zero)."""
    moment = moment or datetime.now(UTC)
    return f"{moment:%B} {moment.day}, {moment:%Y, %H:%M} UTC"


@dataclass(slots=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None
    device: str = "Unknown device"
    location: str = "Unknown location"
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_code: str | None = None
    timezone: str | None = None

    def email_context(self, *, at: datetime | None = None) -> dict:
        """Fields injected into every auth security email's template context."""
        return {
            "ip": self.ip or "Unknown",
            "location": self.location,
            "device": self.device,
            "requested_at": format_utc(at),
        }


def build_client_info(request: Request) -> ClientInfo:
    ip = client_ip_from_request(request)
    user_agent = request.headers.get("user-agent")
    geo: GeoLocation | None = lookup_ip(ip)
    return ClientInfo(
        ip=ip,
        user_agent=user_agent,
        device=parse_user_agent(user_agent),
        location=geo.display if geo else "Unknown location",
        city=geo.city if geo else None,
        region=geo.region if geo else None,
        country=geo.country if geo else None,
        country_code=geo.country_code if geo else None,
        timezone=geo.timezone if geo else None,
    )


async def get_client_info(request: Request) -> ClientInfo:
    """FastAPI dependency — use `ClientInfoDep` on auth endpoints."""
    return build_client_info(request)


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]
