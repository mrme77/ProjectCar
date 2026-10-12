"""Tests for the HTTP trip-control surface without a live RabbitMQ broker."""

from time import monotonic, sleep

from fastapi.testclient import TestClient

from car_project.api.main import create_app
from car_project.api.trips import TripManager
from car_project.domain.telemetry import TelemetryEvent


class FakePublisher:
    """In-memory publisher used to verify the control loop deterministically."""

    def __init__(self) -> None:
        """Start disconnected with no emitted events."""
        self.connected = False
        self.closed = False
        self.events: list[TelemetryEvent] = []

    def connect(self) -> None:
        """Record connection instead of contacting RabbitMQ."""
        self.connected = True

    def publish(self, event: TelemetryEvent) -> None:
        """Keep each simulated event in memory."""
        self.events.append(event)

    def close(self) -> None:
        """Record that the controller released the publisher."""
        self.closed = True


def _wait_for_status(client: TestClient, trip_id: str, expected_status: str) -> dict[str, object]:
    """Poll a short-lived test trip until its background state becomes expected."""
    deadline = monotonic() + 1.0
    while monotonic() < deadline:
        response = client.get(f"/trips/{trip_id}")
        payload = response.json()
        if payload["status"] == expected_status:
            return payload
        sleep(0.01)
    raise AssertionError(f"trip {trip_id} did not reach {expected_status}")


def test_trip_api_starts_updates_and_stops_a_broker_backed_simulator() -> None:
    """The API controls a background publisher loop and retains its latest state."""
    publisher = FakePublisher()
    manager = TripManager(publisher_factory=lambda: publisher, interval_seconds=0.01)

    with TestClient(create_app(manager)) as client:
        created = client.post("/trips", json={"speed_kmh": 80.0, "vehicle_id": "car-api"})

        assert created.status_code == 201
        trip = created.json()
        assert trip["status"] == "running"
        assert publisher.connected is True
        assert client.post("/trips", json={}).status_code == 409

        running = _wait_for_status(client, trip["trip_id"], "running")
        assert running["latest_event_time"] is not None
        assert len(publisher.events) >= 1

        changed = client.patch(f"/trips/{trip['trip_id']}/speed", json={"speed_kmh": 45.0})
        assert changed.status_code == 200
        assert changed.json()["highway_speed_kmh"] == 45.0

        stopping = client.post(f"/trips/{trip['trip_id']}/stop")
        assert stopping.status_code == 202
        stopped = _wait_for_status(client, trip["trip_id"], "stopped")
        assert stopped["status"] == "stopped"

    assert publisher.closed is True


def test_trip_api_returns_not_found_for_an_unknown_trip() -> None:
    """Unknown identifiers are reported as ordinary HTTP 404 responses."""
    manager = TripManager(publisher_factory=FakePublisher)

    with TestClient(create_app(manager)) as client:
        response = client.get("/trips/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
