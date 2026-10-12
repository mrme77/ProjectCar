"""Combine route progression and telemetry-event creation for one local trip."""

from datetime import datetime
from uuid import UUID

from car_project.domain.telemetry import TelemetryEvent
from car_project.simulator.progress import RouteProgressor
from car_project.simulator.road_speed import RoadSpeedPlan
from car_project.simulator.sample import TelemetrySampleFactory
from car_project.simulator.route import Route
from car_project.simulator.speed import GaussianSampler, NormalSpeedProfile
from car_project.simulator.traffic import TrafficStopController


class LocalTripSimulator:
    """Produce ordered telemetry events for one vehicle moving on a saved route.

    A future FastAPI-controlled loop will call :meth:`tick` once each wall-clock
    second. Keeping ticking synchronous and transport-free makes its movement logic
    easy to test and lets the future RabbitMQ publisher remain separate.
    """

    def __init__(
        self,
        route: Route,
        speed_kmh: float,
        trip_id: UUID | None = None,
        vehicle_id: str = "car-001",
        speed_variation_kmh: float = 5.0,
        random_seed: int | None = None,
        random_source: GaussianSampler | None = None,
        traffic_stop_count: int = 30,
        urban_speed_kmh: float = 60.0,
    ) -> None:
        """Start a trip with a bounded normal-distribution speed profile."""
        self._progressor = RouteProgressor(route=route, speed_kmh=urban_speed_kmh)
        self._events = TelemetrySampleFactory(trip_id=trip_id, vehicle_id=vehicle_id)
        self._speed_profile = NormalSpeedProfile(
            target_speed_kmh=urban_speed_kmh,
            standard_deviation_kmh=speed_variation_kmh,
            random_seed=random_seed,
            random_source=random_source,
        )
        self._traffic = TrafficStopController(
            route_distance_km=route.total_distance_km,
            stop_count=traffic_stop_count,
            random_seed=random_seed,
        )
        self._road_speeds = RoadSpeedPlan(
            route_distance_km=route.total_distance_km,
            highway_speed_kmh=speed_kmh,
            urban_speed_kmh=urban_speed_kmh,
            highway_variation_kmh=speed_variation_kmh,
            urban_variation_kmh=speed_variation_kmh,
        )

    @property
    def trip_id(self) -> UUID:
        """Return the identifier assigned to this simulated journey."""
        return self._events.trip_id

    @property
    def distance_travelled_km(self) -> float:
        """Return the current progress along the routed distance."""
        return self._progressor.distance_travelled_km

    @property
    def speed_kmh(self) -> float:
        """Return the current sampled speed used for the latest movement event."""
        return self._speed_profile.current_speed_kmh

    @property
    def target_speed_kmh(self) -> float:
        """Return the normal road-zone target before variation is applied."""
        return self._road_speeds.directive_at(self._progressor.distance_travelled_km).target_speed_kmh

    @property
    def highway_speed_kmh(self) -> float:
        """Return the configured central-highway target speed."""
        return self._road_speeds.highway_speed_kmh

    @property
    def urban_speed_kmh(self) -> float:
        """Return the configured urban target speed near route endpoints."""
        return self._road_speeds.urban_speed_kmh

    @property
    def speed_variation_kmh(self) -> float:
        """Return the normal-distribution standard deviation in km/h."""
        return self._speed_profile.standard_deviation_kmh

    @property
    def traffic_stop_count(self) -> int:
        """Return the number of planned traffic stops for this trip."""
        return len(self._traffic.stops)

    @property
    def vehicle_id(self) -> str:
        """Return the vehicle identifier assigned to this trip."""
        return self._events.vehicle_id

    def set_speed(self, speed_kmh: float) -> None:
        """Update the central-highway target without changing urban behavior."""
        self._speed_profile.set_target_speed(speed_kmh)
        self._road_speeds.set_highway_speed(speed_kmh)

    def tick(self, elapsed_seconds: float, event_time: datetime | None = None) -> TelemetryEvent:
        """Advance the trip and create its next telemetry event.

        Args:
            elapsed_seconds: Time since the previous report, measured by the caller.
            event_time: Event timestamp supplied by the caller, if deterministic
                local testing is required.

        Returns:
            A flat, validated telemetry event describing the new trip state.
        """
        road_directive = self._road_speeds.directive_at(self._progressor.distance_travelled_km)
        directive = self._traffic.next_speed_directive(
            distance_travelled_km=self._progressor.distance_travelled_km,
            current_speed_kmh=self._speed_profile.current_speed_kmh,
            normal_directive=road_directive,
            elapsed_seconds=elapsed_seconds,
        )
        sampled_speed = self._speed_profile.next_speed(
            elapsed_seconds,
            target_speed_kmh=directive.target_speed_kmh,
            variation_kmh=directive.variation_kmh,
            minimum_speed_kmh=directive.minimum_speed_kmh,
            maximum_speed_kmh=directive.maximum_speed_kmh,
        )
        self._progressor.set_speed(sampled_speed)
        position, status = self._progressor.advance(elapsed_seconds)
        return self._events.create_event(
            latitude=position.latitude,
            longitude=position.longitude,
            speed_kmh=sampled_speed,
            distance_travelled_km=self._progressor.distance_travelled_km,
            status=status,
            event_time=event_time,
        )
