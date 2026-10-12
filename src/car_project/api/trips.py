"""In-memory trip lifecycle management for the FastAPI control plane."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol
from uuid import UUID

from car_project.api.models import StartTripRequest, TripResponse
from car_project.broker.publisher import RabbitMQPublisher, TelemetryPublishError
from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TelemetryEvent, TripStatus
from car_project.simulator.route import Route
from car_project.simulator.stream import DEFAULT_ROUTE_PATH
from car_project.simulator.trip import LocalTripSimulator

LOGGER = logging.getLogger(__name__)


class TelemetryPublisher(Protocol):
    """The small publisher boundary needed by a trip control loop."""

    def connect(self) -> None:
        """Open the publisher connection before a trip starts."""

    def publish(self, event: TelemetryEvent) -> None:
        """Persist one event or raise a transport-specific error."""

    def close(self) -> None:
        """Release publisher resources after a trip ends."""


class TripNotFoundError(LookupError):
    """Raised when an API operation references an unknown trip."""


class ActiveTripError(RuntimeError):
    """Raised because this learning service intentionally runs one trip at a time."""


@dataclass(slots=True)
class ManagedTrip:
    """Mutable runtime state owned and protected by :class:`TripManager`."""

    simulator: LocalTripSimulator
    publisher: TelemetryPublisher
    stop_requested: Event
    started_at: datetime
    status: str = "running"
    latest_event: TelemetryEvent | None = None
    error: str | None = None
    thread: Thread | None = None


class TripManager:
    """Start, inspect, update, and stop one broker-backed local trip at a time."""

    def __init__(
        self,
        route_path: Path = DEFAULT_ROUTE_PATH,
        publisher_factory: Callable[[], TelemetryPublisher] | None = None,
        interval_seconds: float = 1.0,
    ) -> None:
        """Create a thread-safe manager with injectable local dependencies."""
        if interval_seconds <= 0.0:
            raise ValueError("interval_seconds must be positive")
        self._route_path = route_path
        self._publisher_factory = publisher_factory or self._create_rabbitmq_publisher
        self._interval_seconds = interval_seconds
        self._lock = RLock()
        self._trips: dict[UUID, ManagedTrip] = {}
        self._active_trip_id: UUID | None = None

    @staticmethod
    def _create_rabbitmq_publisher() -> RabbitMQPublisher:
        """Build the production publisher without connecting until trip creation."""
        return RabbitMQPublisher(RabbitMQSettings())

    def start_trip(self, request: StartTripRequest) -> TripResponse:
        """Connect a publisher and begin emitting one event per configured interval."""
        with self._lock:
            if self._active_trip_id is not None:
                active = self._trips[self._active_trip_id]
                if active.status in {"running", "stopping"}:
                    raise ActiveTripError("a trip is already active; stop it before starting another")

            route = Route.from_geojson(self._route_path)
            simulator = LocalTripSimulator(
                route=route,
                speed_kmh=request.speed_kmh,
                vehicle_id=request.vehicle_id,
                speed_variation_kmh=request.speed_variation_kmh,
                random_seed=request.random_seed,
                traffic_stop_count=request.traffic_stop_count,
                urban_speed_kmh=request.urban_speed_kmh,
            )
            publisher = self._publisher_factory()
            try:
                publisher.connect()
            except TelemetryPublishError as error:
                publisher.close()
                raise RuntimeError(f"unable to connect to RabbitMQ: {error}") from error

            managed = ManagedTrip(
                simulator=simulator,
                publisher=publisher,
                stop_requested=Event(),
                started_at=datetime.now(timezone.utc),
            )
            self._trips[simulator.trip_id] = managed
            self._active_trip_id = simulator.trip_id
            thread = Thread(
                target=self._run_trip,
                args=(simulator.trip_id,),
                name=f"projectcar-trip-{simulator.trip_id}",
                daemon=True,
            )
            managed.thread = thread
            thread.start()
            return self._to_response(managed)

    def get_trip(self, trip_id: UUID) -> TripResponse:
        """Return a snapshot of a known trip without exposing mutable state."""
        with self._lock:
            return self._to_response(self._get_managed_trip(trip_id))

    def set_speed(self, trip_id: UUID, speed_kmh: float) -> TripResponse:
        """Change the speed used by the next generated telemetry event."""
        with self._lock:
            managed = self._get_managed_trip(trip_id)
            if managed.status != "running":
                raise ValueError(f"cannot change speed while trip status is {managed.status}")
            managed.simulator.set_speed(speed_kmh)
            return self._to_response(managed)

    def stop_trip(self, trip_id: UUID) -> TripResponse:
        """Request clean shutdown; the worker loop closes its publisher itself."""
        with self._lock:
            managed = self._get_managed_trip(trip_id)
            if managed.status == "running":
                managed.status = "stopping"
                managed.stop_requested.set()
            return self._to_response(managed)

    def active_trip_id(self) -> UUID | None:
        """Return the running trip identifier, if the service has one."""
        with self._lock:
            return self._active_trip_id

    def shutdown(self) -> None:
        """Signal any active trip and wait briefly for its publisher to close."""
        with self._lock:
            active_id = self._active_trip_id
        if active_id is None:
            return
        self.stop_trip(active_id)
        with self._lock:
            thread = self._trips[active_id].thread
        if thread is not None:
            thread.join(timeout=self._interval_seconds + 1.0)

    def _run_trip(self, trip_id: UUID) -> None:
        """Run the broker-confirmed emission loop for one managed trip."""
        previous_tick = monotonic()
        first_event = True
        try:
            while True:
                with self._lock:
                    managed = self._get_managed_trip(trip_id)
                    if managed.stop_requested.is_set():
                        managed.status = "stopped"
                        return
                    now = monotonic()
                    elapsed_seconds = 0.0 if first_event else max(0.0, now - previous_tick)
                    event = managed.simulator.tick(elapsed_seconds)
                    managed.publisher.publish(event)
                    managed.latest_event = event
                    previous_tick = now
                    first_event = False
                    if event.status is TripStatus.ARRIVED:
                        managed.status = "arrived"
                        return
                if managed.stop_requested.wait(self._interval_seconds):
                    with self._lock:
                        managed.status = "stopped"
                    return
        except (TelemetryPublishError, ValueError, RuntimeError) as error:
            with self._lock:
                managed = self._get_managed_trip(trip_id)
                managed.status = "failed"
                managed.error = str(error)
            LOGGER.exception("Trip %s stopped after a simulator or RabbitMQ failure", trip_id)
        finally:
            with self._lock:
                managed = self._get_managed_trip(trip_id)
                if self._active_trip_id == trip_id:
                    self._active_trip_id = None
            try:
                managed.publisher.close()
            except (TelemetryPublishError, RuntimeError) as error:
                LOGGER.warning("Unable to close publisher for trip %s: %s", trip_id, error)

    def _get_managed_trip(self, trip_id: UUID) -> ManagedTrip:
        """Look up one managed trip with a consistent public error type."""
        try:
            return self._trips[trip_id]
        except KeyError as error:
            raise TripNotFoundError(f"trip {trip_id} was not found") from error

    @staticmethod
    def _to_response(managed: ManagedTrip) -> TripResponse:
        """Convert internal runtime state into a stable API response."""
        latest_event_time = managed.latest_event.event_time if managed.latest_event else None
        return TripResponse(
            trip_id=managed.simulator.trip_id,
            vehicle_id=managed.simulator.vehicle_id,
            speed_kmh=managed.simulator.speed_kmh,
            target_speed_kmh=managed.simulator.target_speed_kmh,
            highway_speed_kmh=managed.simulator.highway_speed_kmh,
            urban_speed_kmh=managed.simulator.urban_speed_kmh,
            speed_variation_kmh=managed.simulator.speed_variation_kmh,
            traffic_stop_count=managed.simulator.traffic_stop_count,
            distance_travelled_km=managed.simulator.distance_travelled_km,
            status=managed.status,
            started_at=managed.started_at,
            latest_event_time=latest_event_time,
            error=managed.error,
        )
