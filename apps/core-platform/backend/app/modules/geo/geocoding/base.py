"""The provider contract.

**A provider builds requests and parses responses. It does not make HTTP
calls.** That one rule is what makes this layer worth having:

* every provider is testable against a saved payload, with no network, no
  mocking of an HTTP client, and no flaky test;
* timeouts, retries, rate limits, the circuit breaker, caching, cost
  accounting and the audit trail live in ``service.py`` — written once
  instead of five times, and impossible for a new provider to forget;
* adding a provider is two methods and a parser, not a subsystem.

Keys never appear in ``cache_params``. They go in ``params``/``headers``,
which are used for the call and thrown away; ``cache_params`` is what gets
hashed and written to ``geo.geocode_api_calls``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.modules.geo.enums import GeoApiType
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeoQuery,
    ProviderNotConfigured,
    ProviderRequest,
    ReverseQuery,
    RouteLeg,
)


class GeocodingProvider(ABC):
    """Forward and reverse geocoding against one upstream."""

    #: Registry key — the value of ``GEOCODING_PROVIDER``.
    name: ClassVar[str]
    #: Human label for the providers endpoint.
    label: ClassVar[str] = ""
    #: Settings attributes that must be non-empty for this provider to run.
    requires: ClassVar[tuple[str, ...]] = ()
    #: Billing units per call, for spend tracking in ``cost_units``.
    cost_per_call: ClassVar[float] = 1.0
    #: How long a result may be cached, per the provider's licence.
    #: Google allows 30 days for geocodes; self-hosted has no such limit.
    cache_days: ClassVar[int | None] = None
    #: Upper bound the operator must not exceed (public Nominatim: 1 req/s).
    max_calls_per_minute: ClassVar[int | None] = None

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    # -- configuration ----------------------------------------------------
    @property
    def cache_variant(self) -> str:
        """Anything about this provider's configuration that changes the shape
        of its answers, and so must not share a cache entry with the other
        shape — a Mapbox account on v5 versus v6, say. Part of the cache key.
        """
        return ""

    def missing_settings(self) -> list[str]:
        return [key for key in self.requires if not getattr(self.settings, key, "")]

    def check_configured(self) -> None:
        missing = self.missing_settings()
        if missing:
            raise ProviderNotConfigured(
                f"geocoding provider '{self.name}' needs {', '.join(missing)} in the environment"
            )

    # -- request building -------------------------------------------------
    @abstractmethod
    def build_forward(self, query: GeoQuery) -> ProviderRequest: ...

    @abstractmethod
    def build_reverse(self, query: ReverseQuery) -> ProviderRequest: ...

    # -- response parsing -------------------------------------------------
    @abstractmethod
    def parse(self, payload: Any, api_type: GeoApiType) -> list[GeocodeResult]: ...

    def check_payload(self, payload: Any) -> str | None:
        """Provider-level status inside a 200 response.

        Google answers ``200 OK`` with ``status: REQUEST_DENIED`` and an
        ``error_message``; treating HTTP status as truth is how a broken API
        key becomes "no results found" for a week. Return a status string, or
        None when the payload carries none.
        """
        return None

    def is_rejection(self, status: str | None) -> bool:
        """True when the provider's status means "do not retry"."""
        return status in {"REQUEST_DENIED", "INVALID_REQUEST", "OVER_DAILY_LIMIT"}


class RoutingProvider(ABC):
    """Real-world travel between places, as opposed to straight lines.

    Separate from ``GeocodingProvider`` on purpose: **Valhalla is a routing
    engine and cannot geocode.** It has no address database — its ``/locate``
    snaps a coordinate to the road graph. The geocoder that pairs with it is
    Pelias, which is why both appear in this package. Google and Mapbox happen
    to sell both, so they implement both interfaces in separate classes.
    """

    name: ClassVar[str]
    label: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()
    cost_per_call: ClassVar[float] = 1.0
    #: Transport modes this provider understands, keyed by ours.
    mode_map: ClassVar[dict[str, str]] = {}

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def missing_settings(self) -> list[str]:
        return [key for key in self.requires if not getattr(self.settings, key, "")]

    def check_configured(self) -> None:
        missing = self.missing_settings()
        if missing:
            raise ProviderNotConfigured(
                f"routing provider '{self.name}' needs {', '.join(missing)} in the environment"
            )

    def upstream_mode(self, mode: str) -> str:
        return self.mode_map.get(mode, next(iter(self.mode_map.values()), mode))

    @abstractmethod
    def build_matrix(
        self, origins: list[tuple[float, float]], destinations: list[tuple[float, float]], mode: str,
    ) -> ProviderRequest: ...

    @abstractmethod
    def parse_matrix(self, payload: Any, mode: str) -> list[list[RouteLeg]]: ...


__all__ = ["GeocodingProvider", "RoutingProvider"]
