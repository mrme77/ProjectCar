"""Tests for planned urban traffic stops and braking behavior."""

import pytest

from car_project.simulator.traffic import TrafficStopController
from car_project.simulator.road_speed import SpeedDirective


def test_traffic_plan_places_equal_stops_at_both_urban_route_ends() -> None:
    """Thirty stops are concentrated before and after the simulated highway."""
    controller = TrafficStopController(route_distance_km=100.0, random_seed=42)

    assert len(controller.stops) == 30
    assert all(stop.distance_km <= 3.0 for stop in controller.stops[:15])
    assert all(stop.distance_km >= 97.0 for stop in controller.stops[15:])
    assert all(20.0 <= stop.duration_seconds <= 60.0 for stop in controller.stops)


def test_traffic_controller_brakes_stops_then_resumes_after_planned_duration() -> None:
    """Traffic behavior creates a zero-speed stationary period without losing the route."""
    controller = TrafficStopController(
        route_distance_km=10.0,
        stop_count=2,
        urban_zone_fraction=0.1,
        minimum_stop_seconds=10.0,
        maximum_stop_seconds=10.0,
    )

    normal = SpeedDirective(80.0, 5.0, 0.0, 250.0)
    braking = controller.next_speed_directive(0.45, 80.0, normal, 1.0)
    stopped = controller.next_speed_directive(0.5, 0.0, normal, 0.0)
    still_stopped = controller.next_speed_directive(0.5, 0.0, normal, 5.0)
    resumed = controller.next_speed_directive(0.5, 0.0, normal, 5.0)

    assert braking.target_speed_kmh < 80.0
    assert braking.variation_kmh == 0.0
    assert stopped.target_speed_kmh == 0.0
    assert still_stopped.target_speed_kmh == 0.0
    assert resumed.target_speed_kmh == pytest.approx(80.0)
