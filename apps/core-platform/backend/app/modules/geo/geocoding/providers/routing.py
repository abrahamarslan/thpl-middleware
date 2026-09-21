"""Routing providers — real travel between places, not straight lines.

Valhalla lives here rather than among the geocoders because **Valhalla cannot
geocode**. It is a routing engine over the OSM graph with no address
database; its ``/locate`` snaps a coordinate to the nearest road, which is not
the same question as "where is 12 MG Road". Its geocoding counterpart is
Pelias (``providers/osm.py``) — the two were built together and are usually
deployed together.

``HaversineRouting`` is the floor: no configuration, no network, no cost. It
answers with the great-circle distance and no duration, which is honest —
nobody should read a travel time that was never measured. It is what
``place_relationships`` falls back to when no routing provider is set, so the
distance column is always populated and always explicable.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.geo.distance import distance_m
from app.modules.geo.geocoding.base import RoutingProvider
from app.modules.geo.geocoding.types import ProviderRequest, RouteLeg

Coordinate = tuple[float, float]              # (latitude, longitude)


class ValhallaRouting(RoutingProvider):
    """Self-hosted Valhalla ``/sources_to_targets``."""

    name: ClassVar[str] = "valhalla"
    label: ClassVar[str] = "Valhalla (self-hosted routing)"
    requires: ClassVar[tuple[str, ...]] = ("ROUTING_VALHALLA_BASE_URL",)
    cost_per_call: ClassVar[float] = 0.0
    mode_map: ClassVar[dict[str, str]] = {
        "driving": "auto",
        "two_wheeler": "motor_scooter",
        "walking": "pedestrian",
        "truck": "truck",
        "transit": "multimodal",
    }

    def build_matrix(
        self, origins: list[Coordinate], destinations: list[Coordinate], mode: str,
    ) -> ProviderRequest:
        body = {
            "sources": [{"lat": lat, "lon": lng} for lat, lng in origins],
            "targets": [{"lat": lat, "lon": lng} for lat, lng in destinations],
            "costing": self.upstream_mode(mode),
            "units": "kilometers",
        }
        return ProviderRequest(
            url=f"{self.settings.ROUTING_VALHALLA_BASE_URL.rstrip('/')}/sources_to_targets",
            method="POST", json_body=body, cache_params=body,
        )

    def parse_matrix(self, payload: Any, mode: str) -> list[list[RouteLeg]]:
        # Valhalla answers in the units it was asked for; we asked for km and
        # every column in this platform is metres.
        scale = 1000.0 if (payload or {}).get("units", "kilometers") in ("km", "kilometers") else 1609.344
        matrix = []
        for row in (payload or {}).get("sources_to_targets", []):
            legs = []
            for cell in row or []:
                distance = cell.get("distance")
                if distance is None:                       # unreachable pair
                    continue
                legs.append(RouteLeg(
                    distance_m=float(distance) * scale,
                    duration_s=_float(cell.get("time")),
                    provider=self.name, mode=mode, raw=cell,
                ))
            matrix.append(legs)
        return matrix


class GoogleRouting(RoutingProvider):
    """Google Distance Matrix. ``two_wheeler`` is real and India-specific."""

    name: ClassVar[str] = "google"
    label: ClassVar[str] = "Google Distance Matrix"
    requires: ClassVar[tuple[str, ...]] = ("GOOGLE_MAPS_API_KEY",)
    cost_per_call: ClassVar[float] = 1.0
    mode_map: ClassVar[dict[str, str]] = {
        "driving": "driving",
        "two_wheeler": "two_wheeler",
        "walking": "walking",
        "truck": "driving",                    # no truck profile
        "transit": "transit",
    }

    def build_matrix(
        self, origins: list[Coordinate], destinations: list[Coordinate], mode: str,
    ) -> ProviderRequest:
        cache = {
            "origins": "|".join(f"{lat},{lng}" for lat, lng in origins),
            "destinations": "|".join(f"{lat},{lng}" for lat, lng in destinations),
            "mode": self.upstream_mode(mode),
        }
        return ProviderRequest(
            url="https://maps.googleapis.com/maps/api/distancematrix/json",
            params={**cache, "key": self.settings.GOOGLE_MAPS_API_KEY},
            cache_params=cache,
        )

    def parse_matrix(self, payload: Any, mode: str) -> list[list[RouteLeg]]:
        matrix = []
        for row in (payload or {}).get("rows", []):
            legs = []
            for element in row.get("elements", []):
                if element.get("status") != "OK":
                    continue
                legs.append(RouteLeg(
                    distance_m=float((element.get("distance") or {}).get("value", 0.0)),
                    duration_s=_float((element.get("duration") or {}).get("value")),
                    provider=self.name, mode=mode, raw=element,
                ))
            matrix.append(legs)
        return matrix


class MapboxRouting(RoutingProvider):
    """Mapbox Directions Matrix. Hard limit of 25 coordinates per call."""

    name: ClassVar[str] = "mapbox"
    label: ClassVar[str] = "Mapbox Directions Matrix"
    requires: ClassVar[tuple[str, ...]] = ("MAPBOX_ACCESS_TOKEN",)
    cost_per_call: ClassVar[float] = 1.0
    mode_map: ClassVar[dict[str, str]] = {
        "driving": "driving",
        "two_wheeler": "driving",
        "walking": "walking",
        "truck": "driving",
        "transit": "driving",
    }
    MAX_COORDINATES: ClassVar[int] = 25

    def build_matrix(
        self, origins: list[Coordinate], destinations: list[Coordinate], mode: str,
    ) -> ProviderRequest:
        coordinates = list(origins) + list(destinations)
        if len(coordinates) > self.MAX_COORDINATES:
            raise ValueError(
                f"mapbox matrix accepts {self.MAX_COORDINATES} coordinates; got {len(coordinates)}"
            )
        path = ";".join(f"{lng},{lat}" for lat, lng in coordinates)
        cache = {
            "path": path,
            "sources": ";".join(str(i) for i in range(len(origins))),
            "destinations": ";".join(str(i) for i in range(len(origins), len(coordinates))),
            "annotations": "distance,duration",
            "profile": self.upstream_mode(mode),
        }
        return ProviderRequest(
            url=f"https://api.mapbox.com/directions-matrix/v1/mapbox/{cache['profile']}/{path}",
            params={
                "sources": cache["sources"], "destinations": cache["destinations"],
                "annotations": cache["annotations"],
                "access_token": self.settings.MAPBOX_ACCESS_TOKEN,
            },
            cache_params=cache,
        )

    def parse_matrix(self, payload: Any, mode: str) -> list[list[RouteLeg]]:
        distances = (payload or {}).get("distances") or []
        durations = (payload or {}).get("durations") or []
        matrix = []
        for row_index, row in enumerate(distances):
            legs = []
            for column_index, distance in enumerate(row or []):
                if distance is None:
                    continue
                duration = None
                if row_index < len(durations) and column_index < len(durations[row_index] or []):
                    duration = durations[row_index][column_index]
                legs.append(RouteLeg(
                    distance_m=float(distance), duration_s=_float(duration),
                    provider=self.name, mode=mode,
                ))
            matrix.append(legs)
        return matrix


class HaversineRouting(RoutingProvider):
    """Straight-line distance, computed here. Always available.

    No duration: a great-circle distance says nothing about how long a road
    takes, and inventing a number by dividing by an assumed speed would be
    a guess that reads like a measurement.
    """

    name: ClassVar[str] = "haversine"
    label: ClassVar[str] = "Straight line (offline)"
    requires: ClassVar[tuple[str, ...]] = ()
    cost_per_call: ClassVar[float] = 0.0
    mode_map: ClassVar[dict[str, str]] = {"driving": "straight_line"}
    #: Answered locally — the service never issues an HTTP call for it.
    offline: ClassVar[bool] = True

    def build_matrix(
        self, origins: list[Coordinate], destinations: list[Coordinate], mode: str,
    ) -> ProviderRequest:
        raise NotImplementedError("HaversineRouting is computed locally; see solve()")

    def parse_matrix(self, payload: Any, mode: str) -> list[list[RouteLeg]]:
        raise NotImplementedError("HaversineRouting is computed locally; see solve()")

    def solve(
        self, origins: list[Coordinate], destinations: list[Coordinate], mode: str,
    ) -> list[list[RouteLeg]]:
        return [
            [
                RouteLeg(distance_m=distance_m(origin, destination), duration_s=None,
                         provider=self.name, mode=mode)
                for destination in destinations
            ]
            for origin in origins
        ]


def _float(value: Any) -> float | None:
    try:
        return float(value)                                  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
