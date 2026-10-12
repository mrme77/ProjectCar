"""Distance-based urban and highway speed regimes for the saved route."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpeedDirective:
    """A speed target, normal variation, and bounds for one route segment."""

    target_speed_kmh: float
    variation_kmh: float
    minimum_speed_kmh: float
    maximum_speed_kmh: float


class RoadSpeedPlan:
    """Choose urban or highway driving behavior from route progress."""

    def __init__(
        self,
        route_distance_km: float,
        highway_speed_kmh: float = 140.0,
        urban_speed_kmh: float = 60.0,
        urban_zone_fraction: float = 0.03,
        highway_variation_kmh: float = 5.0,
        urban_variation_kmh: float = 5.0,
    ) -> None:
        """Configure smooth route zones with bounded urban driving speeds."""
        if route_distance_km <= 0.0:
            raise ValueError("route_distance_km must be positive")
        if highway_speed_kmh < 0.0:
            raise ValueError("highway_speed_kmh must not be negative")
        if not 50.0 <= urban_speed_kmh <= 70.0:
            raise ValueError("urban_speed_kmh must be between 50 and 70")
        if not 0.0 < urban_zone_fraction < 0.5:
            raise ValueError("urban_zone_fraction must be between 0 and 0.5")
        if highway_variation_kmh < 0.0 or urban_variation_kmh < 0.0:
            raise ValueError("road speed variation must not be negative")
        self._route_distance_km = route_distance_km
        self._highway_speed_kmh = highway_speed_kmh
        self._urban_speed_kmh = urban_speed_kmh
        self._urban_zone_km = route_distance_km * urban_zone_fraction
        self._highway_variation_kmh = highway_variation_kmh
        self._urban_variation_kmh = urban_variation_kmh

    @property
    def highway_speed_kmh(self) -> float:
        """Return the target speed used in the central highway segment."""
        return self._highway_speed_kmh

    @property
    def urban_speed_kmh(self) -> float:
        """Return the target speed used near the two urban route ends."""
        return self._urban_speed_kmh

    def set_highway_speed(self, speed_kmh: float) -> None:
        """Update the central highway target without changing urban safety bounds."""
        if speed_kmh < 0.0:
            raise ValueError("speed_kmh must not be negative")
        self._highway_speed_kmh = speed_kmh

    def directive_at(self, distance_travelled_km: float) -> SpeedDirective:
        """Return the normal driving regime at one route distance."""
        if not 0.0 <= distance_travelled_km <= self._route_distance_km:
            raise ValueError("distance_travelled_km must be within the route")
        if self._highway_speed_kmh == 0.0:
            return SpeedDirective(0.0, 0.0, 0.0, 0.0)
        if (
            distance_travelled_km <= self._urban_zone_km
            or distance_travelled_km >= self._route_distance_km - self._urban_zone_km
        ):
            return SpeedDirective(
                target_speed_kmh=self._urban_speed_kmh,
                variation_kmh=self._urban_variation_kmh,
                minimum_speed_kmh=50.0,
                maximum_speed_kmh=70.0,
            )
        return SpeedDirective(
            target_speed_kmh=self._highway_speed_kmh,
            variation_kmh=self._highway_variation_kmh,
            minimum_speed_kmh=0.0,
            maximum_speed_kmh=250.0,
        )
