"""Transport schemas for /api/geocoding."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.geo.geocoding.types import GeocodeResult


class ForwardRequest(BaseModel):
    """Address text → coordinates."""

    text: str = Field(..., min_length=2, max_length=500, description="The address to find")
    country: str | None = Field(
        None, min_length=2, max_length=2,
        description="ISO 3166-1 alpha-2 bias; defaults to GEOCODING_DEFAULT_COUNTRY",
    )
    latitude: float | None = Field(None, ge=-90, le=90, description="Bias towards this point")
    longitude: float | None = Field(None, ge=-180, le=180)
    bias_radius_m: float | None = Field(None, gt=0, le=200_000)
    language: str | None = Field(None, max_length=10)
    limit: int = Field(5, ge=1, le=10)
    provider: str | None = Field(
        None, description="Force one provider instead of the configured chain",
    )

    @model_validator(mode="after")
    def _bias_is_a_pair(self) -> ForwardRequest:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class ReverseRequest(BaseModel):
    """Coordinates → address."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    language: str | None = Field(None, max_length=10)
    limit: int = Field(1, ge=1, le=10)
    provider: str | None = None


class GeocodeMatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    latitude: float
    longitude: float
    formatted_address: str | None = None
    provider_place_id: str | None = None
    components: dict = {}
    place_types: list[str] = []
    confidence: float | None = None
    plus_code: str | None = None
    timezone: str | None = None
    viewport: list[float] | None = None

    @classmethod
    def of(cls, result: GeocodeResult) -> GeocodeMatch:
        # `raw` is never exposed: it is the provider's payload, kept once in
        # geo.geocode_api_calls under its licence, not echoed to clients.
        return cls(
            provider=result.provider,
            latitude=result.latitude,
            longitude=result.longitude,
            formatted_address=result.formatted_address,
            provider_place_id=result.provider_place_id,
            components=dict(result.components),
            place_types=list(result.place_types),
            confidence=result.confidence,
            plus_code=result.plus_code,
            timezone=result.timezone,
            viewport=list(result.viewport) if result.viewport else None,
        )


class GeocodeResponse(BaseModel):
    """The answer, and what it cost to get it."""

    results: list[GeocodeMatch] = []
    provider: str | None = None
    cached: bool = Field(False, description="Served from geo.geocode_api_calls — no upstream call")
    call_id: int | None = Field(None, description="geo.geocode_api_calls.id — the provenance row")
    providers_tried: list[str] = []
    errors: dict[str, str] = Field({}, description="Why each failing provider was skipped")


class ProviderInfo(BaseModel):
    name: str
    label: str
    kind: str                        # geocoding | routing
    configured: bool
    missing_settings: list[str] = []
    in_chain: bool
    chain_position: int | None = None
    cost_per_call: float
    cache_days: int | None = None
    max_calls_per_minute: int | None = None
    circuit: str | None = Field(None, description="closed | open")


class PlaceGeocodeRequest(BaseModel):
    provider: str | None = None
    overwrite_address: bool = Field(
        True,
        description="Also write the provider's postal fields. Always false for a "
                    "Zoho-linked place, whose address Zoho owns.",
    )


class RouteRequest(BaseModel):
    """Travel between two points, by the configured routing provider."""

    origin_latitude: float = Field(..., ge=-90, le=90)
    origin_longitude: float = Field(..., ge=-180, le=180)
    destination_latitude: float = Field(..., ge=-90, le=90)
    destination_longitude: float = Field(..., ge=-180, le=180)
    mode: str = Field("driving", pattern="^(driving|two_wheeler|walking|truck|transit)$")
    provider: str | None = None


class RouteResponse(BaseModel):
    distance_m: float
    duration_s: float | None = Field(
        None, description="Null when the distance is a straight line — no road was measured",
    )
    provider: str
    mode: str
