"""Geocoding API — mounted at /api/geocoding.

| Route | Who | What |
|---|---|---|
| `POST /forward` | member | address text → coordinates |
| `POST /reverse` | member | coordinates → address |
| `POST /route` | member | distance and duration between two points |
| `GET /providers` | member | what is configured, what is missing, circuit state |
| `POST /providers/{name}/reset` | tenant admin | close a tripped circuit |
| `POST /purge` | tenant admin | drop payloads past their licence window |

These are POSTs, not GETs, for a reason: an address typed into a search box is
personal data, and query strings end up in access logs, proxy caches and
browser history. The body does not.

Every call is billable. The response says which provider answered and whether
it came from the cache, so a caller can see what it cost.
"""

from fastapi import APIRouter, Query

from app.common.exception.errors import AppError
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.geo.geocoding import cache, registry, service, transport
from app.modules.geo.geocoding.schema import (
    ForwardRequest,
    GeocodeMatch,
    GeocodeResponse,
    ProviderInfo,
    ReverseRequest,
    RouteRequest,
    RouteResponse,
)
from app.modules.geo.geocoding.types import (
    GeocodingUnavailable,
    GeoQuery,
    ProviderNotConfigured,
    ReverseQuery,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "geo"


class GeocodingUnavailableError(AppError):
    """503: nothing is configured, or every provider failed."""

    status_code = 503
    code = "geocoding_unavailable"


def _response(outcome: service.GeocodeOutcome) -> GeocodeResponse:
    return GeocodeResponse(
        results=[GeocodeMatch.of(result) for result in outcome.results],
        provider=outcome.provider,
        cached=outcome.cached,
        call_id=outcome.call_id,
        providers_tried=outcome.providers_tried,
        errors=outcome.errors,
    )


@router.post("/forward", response_model=ResponseModel[GeocodeResponse])
async def forward(_: CurrentUser, db: DBSession, body: ForwardRequest):
    """Find the coordinates of an address."""
    bias = (body.latitude, body.longitude) if body.latitude is not None else None
    try:
        outcome = await service.geocode(db, GeoQuery(
            text=body.text, country=body.country, bias=bias,
            bias_radius_m=body.bias_radius_m, language=body.language, limit=body.limit,
        ), provider=body.provider)
    except (GeocodingUnavailable, ProviderNotConfigured) as exc:
        raise GeocodingUnavailableError(str(exc)) from exc
    return ResponseModel.ok(data=_response(outcome))


@router.post("/reverse", response_model=ResponseModel[GeocodeResponse])
async def reverse(_: CurrentUser, db: DBSession, body: ReverseRequest):
    """Find the address at a point."""
    try:
        outcome = await service.reverse_geocode(db, ReverseQuery(
            latitude=body.latitude, longitude=body.longitude,
            language=body.language, limit=body.limit,
        ), provider=body.provider)
    except (GeocodingUnavailable, ProviderNotConfigured) as exc:
        raise GeocodingUnavailableError(str(exc)) from exc
    return ResponseModel.ok(data=_response(outcome))


@router.post("/route", response_model=ResponseModel[RouteResponse | None])
async def route(_: CurrentUser, db: DBSession, body: RouteRequest):
    """Distance and duration between two points.

    With no routing provider configured this answers with the straight-line
    distance and a null duration — never a travel time nobody measured.
    """
    try:
        leg = await service.distance_between(
            db, (body.origin_latitude, body.origin_longitude),
            (body.destination_latitude, body.destination_longitude),
            mode=body.mode, provider=body.provider,
        )
    except ProviderNotConfigured as exc:
        raise GeocodingUnavailableError(str(exc)) from exc
    if leg is None:
        return ResponseModel.ok(data=None)
    return ResponseModel.ok(data=RouteResponse(
        distance_m=leg.distance_m, duration_s=leg.duration_s,
        provider=leg.provider, mode=leg.mode,
    ))


@router.get("/providers", response_model=ResponseModel[list[ProviderInfo]])
async def providers(_: CurrentUser):
    """Which providers exist, which could run, and which are circuit-broken.

    Reports the NAMES of missing settings, never their values.
    """
    rows = []
    for row in registry.describe():
        circuit = await transport.breaker_state(row["name"]) if row["configured"] else None
        rows.append(ProviderInfo(**row, circuit=circuit))
    return ResponseModel.ok(data=rows)


@router.post("/providers/{name}/reset", response_model=ResponseModel[None])
async def reset_provider(_: TenantAdmin, name: str):
    """Close a tripped circuit without waiting out the recovery window."""
    await transport.reset_breaker(name)
    return ResponseModel.ok(data=None, module=_M, msg_key="provider_reset", name=name)


@router.post("/purge", response_model=ResponseModel[dict])
async def purge(_: TenantAdmin, db: DBSession,
                older_than_days: int = Query(0, ge=0, le=365)):
    """Delete provider payloads past their licence window.

    One sweep over ``geo.geocode_api_calls`` clears every raw response in the
    platform, because that is the only table holding one.
    """
    deleted = await cache.purge_expired(db, older_than_days=older_than_days)
    return ResponseModel.ok(data={"deleted": deleted}, module=_M, msg_key="purged", count=deleted)
