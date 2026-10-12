"""Tests for creating telemetry from saved-route movement."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from car_project.domain.telemetry import TripStatus
from car_project.simulator.route import Coordinate, Route
from car_project.simulator.trip import LocalTripSimulator


def test_tick_emits_moving_events_with_increasing_sequence_and_distance() -> None:
    """A constant report cadence retains sequence order while movement changes."""
    route = Route((Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)))
    simulator = LocalTripSimulator(
        route,
        speed_kmh=60.0,
        urban_speed_kmh=60.0,
        speed_variation_kmh=0.0,
        trip_id=uuid4(),
        traffic_stop_count=0,
    )
    timestamp = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)

    first = simulator.tick(1.0, timestamp)
    second = simulator.tick(1.0, timestamp)

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert first.distance_travelled_km == pytest.approx(0.0166666667)
    assert second.distance_travelled_km == pytest.approx(0.0333333333)
    assert second.status is TripStatus.MOVING


def test_tick_keeps_emitting_when_speed_is_zero() -> None:
    """Stationary reporting is distinct from ending the trip."""
    route = Route((Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)))
    simulator = LocalTripSimulator(route, speed_kmh=0.0)

    event = simulator.tick(1.0)

    assert event.status is TripStatus.STATIONARY
    assert event.distance_travelled_km == 0.0


def test_tick_emits_stationary_records_while_waiting_at_a_traffic_stop() -> None:
    """A planned traffic light halts route progress and reports zero speed."""
    route = Route((Coordinate(0.0, 0.0), Coordinate(0.0, 0.01)))
    simulator = LocalTripSimulator(
        route,
        speed_kmh=80.0,
        speed_variation_kmh=0.0,
        traffic_stop_count=2,
        random_seed=42,
    )

    simulator.tick(1.0)
    simulator.tick(1.0)
    simulator.tick(1.0)
    stationary_event = simulator.tick(1.0)

    assert stationary_event.status is TripStatus.STATIONARY
    assert stationary_event.speed_kmh == 0.0
    assert stationary_event.distance_travelled_km > 0.0
