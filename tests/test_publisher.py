"""Tests for telemetry-to-AMQP message encoding."""

from car_project.broker.publisher import encode_event
from car_project.domain.telemetry import TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


def test_encode_event_returns_compact_json_bytes() -> None:
    """A typed event becomes a UTF-8 JSON AMQP payload."""
    event = TelemetrySampleFactory().create_event(
        latitude=39.554673,
        longitude=15.878057,
        speed_kmh=0.0,
        distance_travelled_km=0.0,
        status=TripStatus.STATIONARY,
    )

    payload = encode_event(event)

    assert isinstance(payload, bytes)
    assert b'"event_id"' in payload
    assert b'"status":"stationary"' in payload
