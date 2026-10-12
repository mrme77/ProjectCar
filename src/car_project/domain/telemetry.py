"""Typed, locally validated telemetry events emitted by the simulator."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class TripStatus(StrEnum):
    """Lifecycle states represented in emitted telemetry."""

    MOVING = "moving"
    STATIONARY = "stationary"
    ARRIVED = "arrived"
    STOPPED = "stopped"


class TelemetryRecord(TypedDict):
    """Flat JSON-compatible payload accepted by the future broker publisher."""

    event_id: str
    trip_id: str
    vehicle_id: str
    sequence_number: int
    event_time: str
    latitude: float
    longitude: float
    speed_kmh: float
    distance_travelled_km: float
    status: str


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    """One immutable vehicle position report.

    The model deliberately contains only flat, Foundry-friendly values. Its event
    identifier and original event time must be retained when delivery is retried.
    """

    event_id: UUID
    trip_id: UUID
    vehicle_id: str
    sequence_number: int
    event_time: datetime
    latitude: float
    longitude: float
    speed_kmh: float
    distance_travelled_km: float
    status: TripStatus

    def __post_init__(self) -> None:
        """Validate transport-independent telemetry invariants."""
        if not self.vehicle_id.strip():
            raise ValueError("vehicle_id must not be blank")
        if self.sequence_number < 1:
            raise ValueError("sequence_number must be at least 1")
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("event_time must be timezone-aware")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        if self.speed_kmh < 0.0:
            raise ValueError("speed_kmh must not be negative")
        if self.distance_travelled_km < 0.0:
            raise ValueError("distance_travelled_km must not be negative")

    def to_record(self) -> TelemetryRecord:
        """Return a JSON-compatible flat record for a broker or stream client."""
        event_time_utc = self.event_time.astimezone(timezone.utc)
        return {
            "event_id": str(self.event_id),
            "trip_id": str(self.trip_id),
            "vehicle_id": self.vehicle_id,
            "sequence_number": self.sequence_number,
            "event_time": event_time_utc.isoformat().replace("+00:00", "Z"),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "speed_kmh": self.speed_kmh,
            "distance_travelled_km": self.distance_travelled_km,
            "status": self.status.value,
        }
