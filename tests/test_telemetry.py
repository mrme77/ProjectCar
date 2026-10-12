"""Tests for the local telemetry event contract."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from car_project.domain.telemetry import TelemetryEvent, TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


def make_event(**overrides: object) -> TelemetryEvent:
    """Create a valid baseline event with optional field overrides."""
    values: dict[str, object] = {
        "event_id": uuid4(),
        "trip_id": uuid4(),
        "vehicle_id": "car-001",
        "sequence_number": 1,
        "event_time": datetime(2026, 10, 11, 19, 44, 23, tzinfo=timezone.utc),
        "latitude": 39.367,
        "longitude": 15.838,
        "speed_kmh": 80.0,
        "distance_travelled_km": 0.022,
        "status": TripStatus.MOVING,
    }
    values.update(overrides)
    return TelemetryEvent(**values)  # type: ignore[arg-type]


def test_to_record_returns_flat_utc_telemetry() -> None:
    """Events serialize into a flat contract suitable for external delivery."""
    record = make_event().to_record()

    assert record["vehicle_id"] == "car-001"
    assert record["event_time"] == "2026-10-11T19:44:23Z"
    assert record["status"] == "moving"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sequence_number", 0, "sequence_number"),
        ("latitude", 91.0, "latitude"),
        ("speed_kmh", -1.0, "speed_kmh"),
    ],
)
def test_rejects_invalid_telemetry(field: str, value: object, message: str) -> None:
    """Impossible telemetry is rejected before it reaches a broker."""
    with pytest.raises(ValueError, match=message):
        make_event(**{field: value})


def test_sample_factory_increments_sequence_within_one_trip() -> None:
    """The local generator preserves its trip ID and increments event sequence."""
    factory = TelemetrySampleFactory()
    timestamp = datetime(2026, 10, 11, 19, 44, 23, tzinfo=timezone.utc)

    first = factory.create_event(39.367, 15.838, 0.0, 0.0, TripStatus.STATIONARY, timestamp)
    second = factory.create_event(39.367, 15.838, 30.0, 0.008, TripStatus.MOVING, timestamp)

    assert first.trip_id == second.trip_id == factory.trip_id
    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert first.event_id != second.event_id
