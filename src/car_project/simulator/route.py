"""Saved road-route loading and distance-based position interpolation."""

import json
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 geographic coordinate in decimal degrees."""

    latitude: float
    longitude: float


class Route:
    """An ordered route whose positions can be resolved by travelled distance."""

    def __init__(
        self, coordinates: tuple[Coordinate, ...], routing_distance_km: float | None = None
    ) -> None:
        """Create a route and precompute the distance for each geometry segment."""
        if len(coordinates) < 2:
            raise ValueError("a route requires at least two coordinates")
        self._coordinates = coordinates
        geometry_segment_lengths_km = tuple(
            self._haversine_km(start, end)
            for start, end in zip(coordinates, coordinates[1:])
        )
        geometry_distance_km = sum(geometry_segment_lengths_km)
        if geometry_distance_km == 0.0:
            raise ValueError("a route must have non-zero length")
        if routing_distance_km is not None and routing_distance_km <= 0.0:
            raise ValueError("routing_distance_km must be positive")
        self._total_distance_km = routing_distance_km or geometry_distance_km
        scale = self._total_distance_km / geometry_distance_km
        self._segment_lengths_km = tuple(length * scale for length in geometry_segment_lengths_km)

    @classmethod
    def from_geojson(cls, path: Path) -> "Route":
        """Load a GeoJSON LineString feature from a local route asset."""
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            geometry = document["geometry"]
            if geometry["type"] != "LineString":
                raise ValueError("route geometry must be a LineString")
            coordinates = tuple(
                Coordinate(latitude=float(latitude), longitude=float(longitude))
                for longitude, latitude in geometry["coordinates"]
            )
            routing_distance = document.get("properties", {}).get("routing_distance_km")
            routing_distance_km = float(routing_distance) if routing_distance is not None else None
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"unable to load route from {path}: {error}") from error
        return cls(coordinates, routing_distance_km=routing_distance_km)

    @property
    def total_distance_km(self) -> float:
        """Return the saved route's routing distance used for progression."""
        return self._total_distance_km

    @property
    def start(self) -> Coordinate:
        """Return the route origin."""
        return self._coordinates[0]

    @property
    def destination(self) -> Coordinate:
        """Return the route destination."""
        return self._coordinates[-1]

    def position_at_distance(self, distance_km: float) -> tuple[Coordinate, bool]:
        """Interpolate a coordinate by distance and report whether arrival occurred."""
        if distance_km < 0.0:
            raise ValueError("distance_km must not be negative")
        if distance_km >= self._total_distance_km:
            return self.destination, True
        remaining = distance_km
        for start, end, segment_length in zip(
            self._coordinates, self._coordinates[1:], self._segment_lengths_km
        ):
            if remaining <= segment_length:
                fraction = remaining / segment_length
                return Coordinate(
                    latitude=start.latitude + ((end.latitude - start.latitude) * fraction),
                    longitude=start.longitude + ((end.longitude - start.longitude) * fraction),
                ), False
            remaining -= segment_length
        return self.destination, True

    @staticmethod
    def _haversine_km(start: Coordinate, end: Coordinate) -> float:
        """Calculate the great-circle distance between two WGS84 coordinates."""
        latitude_delta = radians(end.latitude - start.latitude)
        longitude_delta = radians(end.longitude - start.longitude)
        start_latitude = radians(start.latitude)
        end_latitude = radians(end.latitude)
        half_chord = sin(latitude_delta / 2) ** 2 + cos(start_latitude) * cos(end_latitude) * sin(
            longitude_delta / 2
        ) ** 2
        return 6371.0088 * 2 * asin(sqrt(half_chord))
