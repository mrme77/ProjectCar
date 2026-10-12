"""Tests for forwarding-worker decoding and delivery outcomes."""

import logging
from types import SimpleNamespace
from typing import cast

import pytest

from car_project.broker.publisher import encode_event
from car_project.broker.settings import RabbitMQSettings
from car_project.broker.worker import (
    FoundryDeliveryError,
    FoundryTarget,
    RabbitMQForwardingWorker,
    decode_record,
)
from car_project.domain.telemetry import TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


def test_decode_record_preserves_a_valid_telemetry_payload() -> None:
    """A publisher payload can be decoded into the Foundry delivery record."""
    event = TelemetrySampleFactory().create_event(
        latitude=39.554673,
        longitude=15.878057,
        speed_kmh=0.0,
        distance_travelled_km=0.0,
        status=TripStatus.STATIONARY,
    )

    record = decode_record(encode_event(event))

    assert record["event_id"] == str(event.event_id)
    assert record["status"] == "stationary"


def test_decode_record_rejects_non_json_messages() -> None:
    """Malformed broker bodies are surfaced instead of sent to Foundry."""
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        decode_record(b"not-json")


class FakeChannel:
    """Record worker acknowledgements and failed-delivery publications."""

    def __init__(self) -> None:
        """Start with no broker interactions."""
        self.acknowledged_tags: list[int] = []
        self.failed_bodies: list[bytes] = []

    def basic_ack(self, delivery_tag: int) -> None:
        """Record that the source delivery was acknowledged."""
        self.acknowledged_tags.append(delivery_tag)

    def basic_publish(self, **kwargs: object) -> None:
        """Record the durable failed-delivery body and emulate confirmation."""
        body = kwargs["body"]
        assert isinstance(body, bytes)
        self.failed_bodies.append(body)
        return None


class IdleChannel:
    """Minimal channel that emits one idle heartbeat before test shutdown."""

    is_open = False

    def exchange_declare(self, **_kwargs: object) -> None:
        """Accept the worker's topology declaration."""

    def queue_declare(self, **_kwargs: object) -> None:
        """Accept the worker's failed-queue declaration."""

    def queue_bind(self, **_kwargs: object) -> None:
        """Accept the worker's failed-queue binding."""

    def confirm_delivery(self) -> None:
        """Accept publisher-confirmation setup."""

    def basic_qos(self, **_kwargs: object) -> None:
        """Accept consumer prefetch setup."""

    def consume(self, **_kwargs: object) -> object:
        """Yield one idle timeout, then simulate a terminal interruption."""
        yield None, None, None
        raise KeyboardInterrupt


class IdleConnection:
    """Minimal connection that returns the idle-only test channel."""

    is_open = False

    def __init__(self, channel: IdleChannel) -> None:
        """Keep the prepared channel for worker setup."""
        self._channel = channel

    def channel(self) -> IdleChannel:
        """Return the channel used by this connection."""
        return self._channel


class SequencedTarget:
    """Return configured delivery outcomes without making HTTP calls."""

    def __init__(self, outcomes: list[FoundryDeliveryError | None]) -> None:
        """Store one result for each Foundry delivery attempt."""
        self._outcomes = outcomes
        self.attempt_count = 0

    def publish(self, _record: object) -> None:
        """Raise the next planned error, if any."""
        outcome = self._outcomes[self.attempt_count]
        self.attempt_count += 1
        if outcome is not None:
            raise outcome


def _valid_body() -> bytes:
    """Return one schema-compatible AMQP telemetry payload."""
    event = TelemetrySampleFactory().create_event(
        latitude=39.554673,
        longitude=15.878057,
        speed_kmh=80.0,
        distance_travelled_km=0.0,
        status=TripStatus.MOVING,
    )
    return encode_event(event)


def test_worker_retries_a_transient_foundry_failure_then_acknowledges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary HTTP failure is retried before the source message is acknowledged."""
    target = SequencedTarget(
        [FoundryDeliveryError("Foundry unavailable", transient=True), None]
    )
    worker = RabbitMQForwardingWorker(
        RabbitMQSettings(worker_retry_base_seconds=0.01), cast(FoundryTarget, target)
    )
    channel = FakeChannel()
    waits: list[float] = []
    monkeypatch.setattr("car_project.broker.worker.time.sleep", waits.append)

    worker._on_message(cast(object, channel), SimpleNamespace(delivery_tag=7), object(), _valid_body())

    assert target.attempt_count == 2
    assert waits == [0.01]
    assert channel.acknowledged_tags == [7]
    assert channel.failed_bodies == []


def test_worker_preserves_a_permanent_foundry_failure_before_acknowledging() -> None:
    """A rejected event reaches the failed queue before its source is acknowledged."""
    target = SequencedTarget([FoundryDeliveryError("Foundry rejected record", transient=False)])
    worker = RabbitMQForwardingWorker(RabbitMQSettings(), cast(FoundryTarget, target))
    channel = FakeChannel()

    worker._on_message(cast(object, channel), SimpleNamespace(delivery_tag=9), object(), _valid_body())

    assert target.attempt_count == 1
    assert channel.acknowledged_tags == [9]
    assert len(channel.failed_bodies) == 1
    assert b"Foundry rejected record" in channel.failed_bodies[0]


def test_worker_logs_an_idle_heartbeat_without_receiving_a_message(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty queue remains visibly healthy without busy polling."""
    caplog.set_level(logging.INFO, logger="car_project.broker.worker")
    channel = IdleChannel()
    connection = IdleConnection(channel)
    monkeypatch.setattr("car_project.broker.worker.pika.BlockingConnection", lambda _params: connection)
    worker = RabbitMQForwardingWorker(
        RabbitMQSettings(worker_idle_heartbeat_seconds=0.01),
        FoundryTarget("example.test", "dataset", "master", "token", "true"),
    )

    with pytest.raises(KeyboardInterrupt):
        worker.run()

    assert "Still waiting for telemetry messages" in caplog.text
