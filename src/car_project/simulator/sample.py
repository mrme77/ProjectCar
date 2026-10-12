"""Generate local telemetry records before route simulation is introduced."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from car_project.domain.telemetry import TelemetryEvent, TripStatus


class TelemetrySampleFactory:
    """Create sequential telemetry events for one simulated trip.

    This temporary local generator verifies the event contract independently of a
    route, broker, web API, and Foundry stream. A later route simulator will own
    movement calculations while continuing to use the same event contract.
    """

    def __init__(self, trip_id: UUID | None = None, vehicle_id: str = "car-001") -> None:
        """Initialize a new trip's event sequence.

        Args:
            trip_id: Existing identifier to reuse, or ``None`` to create one.
            vehicle_id: Identifier emitted with every event for the trip.
        """
        self._trip_id = trip_id or uuid4()
        self._vehicle_id = vehicle_id
        self._next_sequence_number = 1

    @property
    def trip_id(self) -> UUID:
        """Return the identifier shared by events from this factory."""
        return self._trip_id

    @property
    def vehicle_id(self) -> str:
        """Return the vehicle identifier shared by events from this factory."""
        return self._vehicle_id

    def create_event(
        self,
        latitude: float,
        longitude: float,
        speed_kmh: float,
        distance_travelled_km: float,
        status: TripStatus,
        event_time: datetime | None = None,
    ) -> TelemetryEvent:
        """Create the next event in the trip sequence.

        Args:
            latitude: WGS84 latitude in decimal degrees.
            longitude: WGS84 longitude in decimal degrees.
            speed_kmh: Current simulated speed in kilometres per hour.
            distance_travelled_km: Completed distance along the saved route.
            status: Current trip lifecycle state.
            event_time: UTC event time, or ``None`` to use the current time.

        Returns:
            A validated event with a new stable event identifier.
        """
        timestamp = event_time or datetime.now(timezone.utc)
        event = TelemetryEvent(
            event_id=uuid4(),
            trip_id=self._trip_id,
            vehicle_id=self._vehicle_id,
            sequence_number=self._next_sequence_number,
            event_time=timestamp,
            latitude=latitude,
            longitude=longitude,
            speed_kmh=speed_kmh,
            distance_travelled_km=distance_travelled_km,
            status=status,
        )
        self._next_sequence_number += 1
        return event


def main() -> None:
    """Print one example event as the local publisher's future payload shape."""
    factory = TelemetrySampleFactory()
    event = factory.create_event(
        latitude=39.367,
        longitude=15.838,
        speed_kmh=80.0,
        distance_travelled_km=0.0,
        status=TripStatus.MOVING,
    )
    print(json.dumps(event.to_record(), indent=2))


if __name__ == "__main__":
    main()
