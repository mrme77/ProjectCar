"""Tests for safe, operator-approved failed-message replay behavior."""

import json
from types import SimpleNamespace
from typing import cast

from car_project.broker.publisher import encode_event
from car_project.broker.replay_failed import FailedMessageReplayer
from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


class FakeReplayChannel:
    """Record the message-transfer order used by the replay tool."""

    def __init__(self) -> None:
        """Start with no confirmed publishes or acknowledgements."""
        self.published: list[dict[str, object]] = []
        self.acknowledged_tags: list[int] = []

    def basic_publish(self, **kwargs: object) -> None:
        """Record a publisher-confirmed message transfer."""
        self.published.append(kwargs)
        return None

    def basic_ack(self, delivery_tag: int) -> None:
        """Record the source failed-message acknowledgement."""
        self.acknowledged_tags.append(delivery_tag)


def _failed_envelope() -> tuple[bytes, bytes]:
    """Build the same failed-message shape written by the forwarding worker."""
    event = TelemetrySampleFactory().create_event(
        latitude=39.554673,
        longitude=15.878057,
        speed_kmh=80.0,
        distance_travelled_km=0.0,
        status=TripStatus.MOVING,
    )
    original_body = encode_event(event)
    envelope = json.dumps(
        {
            "failure_reason": "Foundry delivery failed (status: 401)",
            "failed_at": 0.0,
            "original_body": original_body.decode("utf-8"),
        }
    ).encode("utf-8")
    return envelope, original_body


def test_replay_republishes_original_body_before_acknowledging_failed_delivery() -> None:
    """A valid envelope returns the exact original record to the normal routing key."""
    replayer = FailedMessageReplayer(RabbitMQSettings())
    channel = FakeReplayChannel()
    envelope, original_body = _failed_envelope()

    replayer._replay_delivery(cast(object, channel), SimpleNamespace(delivery_tag=12), envelope)

    assert channel.published[0]["routing_key"] == "telemetry"
    assert channel.published[0]["body"] == original_body
    assert channel.acknowledged_tags == [12]


def test_replay_quarantines_invalid_envelopes_before_acknowledging() -> None:
    """A broken failed message is preserved separately instead of being discarded."""
    replayer = FailedMessageReplayer(RabbitMQSettings())
    channel = FakeReplayChannel()

    replayer._replay_delivery(cast(object, channel), SimpleNamespace(delivery_tag=13), b"not-json")

    assert channel.published[0]["routing_key"] == "telemetry.failed.invalid"
    assert channel.acknowledged_tags == [13]
    assert b"replay_error" in cast(bytes, channel.published[0]["body"])
