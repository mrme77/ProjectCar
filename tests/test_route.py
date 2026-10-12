"""Tests for saved-route interpolation and movement progression."""

from pathlib import Path

import pytest

from car_project.domain.telemetry import TripStatus
from car_project.simulator.progress import RouteProgressor
from car_project.simulator.route import Coordinate, Route


def make_test_route() -> Route:
    """Return a short equatorial route with predictable interpolation."""
    return Route((Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)))


def test_position_at_distance_starts_at_origin_and_clamps_at_destination() -> None:
    """Distance lookup keeps positions within the saved route bounds."""
    route = make_test_route()
    start, is_at_start_destination = route.position_at_distance(0.0)
    destination, is_at_destination = route.position_at_distance(route.total_distance_km + 1.0)
    assert start == route.start
    assert not is_at_start_destination
    assert destination == route.destination
    assert is_at_destination


def test_progressor_changes_distance_by_speed_not_report_frequency() -> None:
    """One second of simulated movement reflects speed divided by 3600."""
    progressor = RouteProgressor(make_test_route(), speed_kmh=72.0)
    _, status = progressor.advance(1.0)
    assert progressor.distance_travelled_km == pytest.approx(0.02)
    assert status is TripStatus.MOVING


def test_progressor_emits_stationary_without_advancing_distance() -> None:
    """Zero speed is a reportable stationary state, not a stopped trip."""
    progressor = RouteProgressor(make_test_route())
    position, status = progressor.advance(1.0)
    assert position == progressor.route.start
    assert progressor.distance_travelled_km == 0.0
    assert status is TripStatus.STATIONARY


def test_saved_route_asset_loads_as_a_non_empty_road_route() -> None:
    """The checked-in local asset can be loaded without a routing API call."""
    route = Route.from_geojson(Path("data/routes/cittadella-del-capo-to-napoli.geojson"))
    assert route.total_distance_km == pytest.approx(257.1659)
    assert route.start.latitude == pytest.approx(39.554673)
    assert route.destination.longitude == pytest.approx(14.248293)
