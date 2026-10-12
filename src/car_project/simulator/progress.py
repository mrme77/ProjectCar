"""Stateful distance advancement for a vehicle travelling along a saved route."""

from dataclasses import dataclass

from car_project.domain.telemetry import TripStatus
from car_project.simulator.route import Coordinate, Route


@dataclass(slots=True)
class RouteProgressor:
    """Advance one vehicle by elapsed wall-clock time without changing report rate."""

    route: Route
    speed_kmh: float = 0.0
    distance_travelled_km: float = 0.0

    def __post_init__(self) -> None:
        """Validate the initial state before progression begins."""
        if self.speed_kmh < 0.0:
            raise ValueError("speed_kmh must not be negative")
        if self.distance_travelled_km < 0.0:
            raise ValueError("distance_travelled_km must not be negative")

    def set_speed(self, speed_kmh: float) -> None:
        """Set the simulated driving speed in kilometres per hour."""
        if speed_kmh < 0.0:
            raise ValueError("speed_kmh must not be negative")
        self.speed_kmh = speed_kmh

    def advance(self, elapsed_seconds: float) -> tuple[Coordinate, TripStatus]:
        """Move by speed times elapsed time and return the current position/status."""
        if elapsed_seconds < 0.0:
            raise ValueError("elapsed_seconds must not be negative")
        if self.distance_travelled_km >= self.route.total_distance_km:
            return self.route.destination, TripStatus.ARRIVED
        self.distance_travelled_km = min(
            self.distance_travelled_km + (self.speed_kmh * elapsed_seconds / 3600.0),
            self.route.total_distance_km,
        )
        position, arrived = self.route.position_at_distance(self.distance_travelled_km)
        if arrived:
            return position, TripStatus.ARRIVED
        if self.speed_kmh == 0.0:
            return position, TripStatus.STATIONARY
        return position, TripStatus.MOVING
