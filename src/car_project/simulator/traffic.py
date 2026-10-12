"""Deterministic urban traffic-stop planning for the local route simulator."""

from math import sqrt
from random import Random

from dataclasses import dataclass

from car_project.simulator.road_speed import SpeedDirective


@dataclass(frozen=True, slots=True)
class TrafficStop:
    """One planned stationary period at a distance along the route."""

    distance_km: float
    duration_seconds: float


class TrafficStopController:
    """Plan urban stops and provide a safe speed target before each one.

    Stops are intentionally simulated rather than inferred from the saved route:
    half are distributed through the first urban zone and half through the final
    urban zone. Highway travel between those zones has no planned traffic lights.
    """

    def __init__(
        self,
        route_distance_km: float,
        stop_count: int = 30,
        urban_zone_fraction: float = 0.03,
        minimum_stop_seconds: float = 20.0,
        maximum_stop_seconds: float = 60.0,
        maximum_braking_mps2: float = 2.78,
        random_seed: int | None = None,
    ) -> None:
        """Create a reproducible plan of city stops before and after highway travel."""
        if route_distance_km <= 0.0:
            raise ValueError("route_distance_km must be positive")
        if stop_count < 0 or stop_count % 2 != 0:
            raise ValueError("stop_count must be a non-negative even number")
        if not 0.0 < urban_zone_fraction < 0.5:
            raise ValueError("urban_zone_fraction must be between 0 and 0.5")
        if minimum_stop_seconds <= 0.0 or maximum_stop_seconds < minimum_stop_seconds:
            raise ValueError("traffic-stop durations must be positive and ordered")
        if maximum_braking_mps2 <= 0.0:
            raise ValueError("maximum_braking_mps2 must be positive")

        self._maximum_braking_mps2 = maximum_braking_mps2
        self._random = Random(random_seed)
        self._stops = self._build_stops(
            route_distance_km,
            stop_count,
            urban_zone_fraction,
            minimum_stop_seconds,
            maximum_stop_seconds,
        )
        self._next_stop_index = 0
        self._active_stop_remaining_seconds: float | None = None

    @property
    def stops(self) -> tuple[TrafficStop, ...]:
        """Return the immutable traffic-stop plan for inspection and testing."""
        return self._stops

    def next_speed_directive(
        self,
        distance_travelled_km: float,
        current_speed_kmh: float,
        normal_directive: SpeedDirective,
        elapsed_seconds: float,
    ) -> SpeedDirective:
        """Return a target that brakes for, waits at, or leaves a planned stop."""
        if distance_travelled_km < 0.0:
            raise ValueError("distance_travelled_km must not be negative")
        if current_speed_kmh < 0.0 or normal_directive.target_speed_kmh < 0.0:
            raise ValueError("speed values must not be negative")
        if elapsed_seconds < 0.0:
            raise ValueError("elapsed_seconds must not be negative")

        if self._active_stop_remaining_seconds is not None:
            self._active_stop_remaining_seconds -= elapsed_seconds
            if self._active_stop_remaining_seconds > 0.0:
                return SpeedDirective(0.0, 0.0, 0.0, normal_directive.maximum_speed_kmh)
            self._active_stop_remaining_seconds = None
            self._next_stop_index += 1

        next_stop = self._next_stop()
        if next_stop is None:
            return normal_directive
        if distance_travelled_km >= next_stop.distance_km:
            self._active_stop_remaining_seconds = next_stop.duration_seconds
            return SpeedDirective(0.0, 0.0, 0.0, normal_directive.maximum_speed_kmh)

        remaining_distance_meters = (next_stop.distance_km - distance_travelled_km) * 1000.0
        braking_target_kmh = sqrt(2.0 * self._maximum_braking_mps2 * remaining_distance_meters) * 3.6
        if braking_target_kmh < normal_directive.target_speed_kmh:
            return SpeedDirective(
                target_speed_kmh=braking_target_kmh,
                variation_kmh=0.0,
                minimum_speed_kmh=0.0,
                maximum_speed_kmh=normal_directive.maximum_speed_kmh,
            )
        return normal_directive

    def _next_stop(self) -> TrafficStop | None:
        """Return the next not-yet-completed traffic stop, if one remains."""
        if self._next_stop_index >= len(self._stops):
            return None
        return self._stops[self._next_stop_index]

    def _build_stops(
        self,
        route_distance_km: float,
        stop_count: int,
        urban_zone_fraction: float,
        minimum_stop_seconds: float,
        maximum_stop_seconds: float,
    ) -> tuple[TrafficStop, ...]:
        """Distribute equal stop counts through the two non-highway route ends."""
        if stop_count == 0:
            return ()
        stops_per_zone = stop_count // 2
        urban_zone_km = route_distance_km * urban_zone_fraction
        origin_distances = tuple(
            urban_zone_km * index / (stops_per_zone + 1)
            for index in range(1, stops_per_zone + 1)
        )
        destination_distances = tuple(
            route_distance_km - urban_zone_km + (urban_zone_km * index / (stops_per_zone + 1))
            for index in range(1, stops_per_zone + 1)
        )
        return tuple(
            TrafficStop(
                distance_km=distance_km,
                duration_seconds=self._random.uniform(minimum_stop_seconds, maximum_stop_seconds),
            )
            for distance_km in (*origin_distances, *destination_distances)
        )
