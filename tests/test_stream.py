"""Tests for the real-time local telemetry stream runner."""

import sys

import pytest
from car_project.domain.telemetry import TelemetryEvent, TripStatus
from car_project.simulator.route import Coordinate, Route
from car_project.simulator import stream
from car_project.simulator.stream import run_stream
from car_project.simulator.trip import LocalTripSimulator


class FakeClock:
    """A deterministic monotonic clock for stream cadence tests."""

    def __init__(self) -> None:
        """Initialize the clock at zero seconds."""
        self.current = 0.0

    def __call__(self) -> float:
        """Return the current synthetic monotonic time."""
        return self.current

    def sleep(self, seconds: float) -> None:
        """Advance synthetic time instead of blocking a test."""
        self.current += seconds


def test_run_stream_emits_one_event_per_interval() -> None:
    """A bounded stream emits ordered moving events at its requested cadence."""
    clock = FakeClock()
    route = Route((Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)))
    simulator = LocalTripSimulator(
        route,
        speed_kmh=60.0,
        urban_speed_kmh=60.0,
        speed_variation_kmh=0.0,
        traffic_stop_count=0,
    )
    events: list[TelemetryEvent] = []

    run_stream(simulator, events.append, event_limit=3, clock=clock, sleeper=clock.sleep)

    assert [event.sequence_number for event in events] == [1, 2, 3]
    assert [event.distance_travelled_km for event in events] == [0.0, 0.016666666666666666, 0.03333333333333333]
    assert events[0].latitude == route.start.latitude
    assert events[0].longitude == route.start.longitude
    assert all(event.status is TripStatus.MOVING for event in events)


def test_stream_arguments_accept_a_custom_vehicle_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Bash caller can emit a distinct vehicle identifier without code changes."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["stream", "--vehicle-id", "car-002", "--print-events"],
    )

    arguments = stream._parse_arguments()

    assert arguments.vehicle_id == "car-002"
