"""Tests for distance-based urban and highway speed regimes."""

from car_project.simulator.road_speed import RoadSpeedPlan


def test_road_speed_plan_uses_bounded_urban_and_highway_targets() -> None:
    """Route ends use city speeds while the center uses the faster highway target."""
    plan = RoadSpeedPlan(route_distance_km=100.0, highway_speed_kmh=140.0)

    origin = plan.directive_at(1.0)
    highway = plan.directive_at(50.0)
    destination = plan.directive_at(99.0)

    assert (origin.target_speed_kmh, origin.minimum_speed_kmh, origin.maximum_speed_kmh) == (60.0, 50.0, 70.0)
    assert highway.target_speed_kmh == 140.0
    assert (destination.target_speed_kmh, destination.minimum_speed_kmh, destination.maximum_speed_kmh) == (60.0, 50.0, 70.0)
