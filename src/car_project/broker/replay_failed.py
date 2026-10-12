"""Replay operator-approved telemetry records from RabbitMQ's failed queue."""

import argparse
import json
import logging
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pydantic import ValidationError

from car_project.broker.settings import RabbitMQSettings
from car_project.broker.worker import decode_record
from car_project.domain.telemetry import TelemetryRecord

LOGGER = logging.getLogger(__name__)


class FailedReplayError(RuntimeError):
    """Raised when a failed record cannot be safely replayed or preserved."""


@dataclass(frozen=True, slots=True)
class FailedTelemetryEnvelope:
    """A worker-created failed-delivery record plus its original telemetry body."""

    failure_reason: str
    original_body: bytes
    original_record: TelemetryRecord

    @classmethod
    def from_body(cls, body: bytes) -> "FailedTelemetryEnvelope":
        """Decode and validate a failed-queue envelope before replaying it."""
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"failed message is not valid UTF-8 JSON: {error}") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("failed message JSON must be an object")
        failure_reason = decoded.get("failure_reason")
        original_body = decoded.get("original_body")
        if not isinstance(failure_reason, str) or not failure_reason:
            raise ValueError("failed message is missing failure_reason")
        if not isinstance(original_body, str):
            raise ValueError("failed message is missing original_body")
        original_bytes = original_body.encode("utf-8")
        return cls(
            failure_reason=failure_reason,
            original_body=original_bytes,
            original_record=decode_record(original_bytes),
        )


@dataclass(slots=True)
class ReplayMetrics:
    """Counts from one deliberately bounded replay run."""

    replayed: int = 0
    quarantined: int = 0


class FailedMessageReplayer:
    """Manually replay a bounded number of valid failed deliveries.

    This is an operator tool, not an automatic retry path. Run it only after the
    underlying cause has been fixed, for example after restoring valid Foundry
    credentials. It acknowledges a failed message only after RabbitMQ confirms the
    original telemetry body is back on the normal telemetry queue.
    """

    def __init__(self, settings: RabbitMQSettings) -> None:
        """Store the RabbitMQ topology used for replay operations."""
        self._settings = settings
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None
        self._metrics = ReplayMetrics()

    def run(self, limit: int) -> ReplayMetrics:
        """Replay at most ``limit`` messages and return confirmed outcome counts."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            self._connection = pika.BlockingConnection(pika.URLParameters(self._settings.rabbitmq_url))
            self._channel = self._connection.channel()
            self._declare_topology(self._channel)
            for _ in range(limit):
                method, _properties, body = self._channel.basic_get(
                    queue=self._settings.rabbitmq_failed_queue,
                    auto_ack=False,
                )
                if method is None or body is None:
                    break
                self._replay_delivery(self._channel, method, body)
            LOGGER.info("Replay completed; metrics=%s", self._metrics)
            return self._metrics
        except pika.exceptions.AMQPError as error:
            raise FailedReplayError(f"RabbitMQ replay failure: {error}") from error
        finally:
            self.close()

    def _declare_topology(self, channel: BlockingChannel) -> None:
        """Ensure normal, failed, and unreplayable paths exist before any transfer."""
        channel.exchange_declare(
            exchange=self._settings.rabbitmq_exchange,
            exchange_type="direct",
            durable=True,
        )
        channel.queue_declare(queue=self._settings.rabbitmq_failed_queue, durable=True)
        channel.queue_declare(queue=self._settings.rabbitmq_replay_invalid_queue, durable=True)
        channel.queue_bind(
            queue=self._settings.rabbitmq_replay_invalid_queue,
            exchange=self._settings.rabbitmq_exchange,
            routing_key=f"{self._settings.rabbitmq_routing_key}.failed.invalid",
        )
        channel.confirm_delivery()

    def _replay_delivery(self, channel: BlockingChannel, method: object, body: bytes) -> None:
        """Transfer one valid original event, or quarantine an invalid envelope."""
        delivery_tag = getattr(method, "delivery_tag", None)
        if not isinstance(delivery_tag, int):
            raise FailedReplayError("failed delivery did not include an integer delivery tag")
        try:
            envelope = FailedTelemetryEnvelope.from_body(body)
        except ValueError as error:
            self._quarantine_invalid(channel, body, str(error))
            channel.basic_ack(delivery_tag=delivery_tag)
            self._metrics.quarantined += 1
            LOGGER.error("Quarantined unreplayable failed message: %s", error)
            return

        try:
            confirmed = channel.basic_publish(
                exchange=self._settings.rabbitmq_exchange,
                routing_key=self._settings.rabbitmq_routing_key,
                body=envelope.original_body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    message_id=envelope.original_record["event_id"],
                    headers={"x-projectcar-replayed": True},
                ),
                mandatory=True,
            )
        except pika.exceptions.AMQPError as error:
            raise FailedReplayError(f"unable to replay failed delivery: {error}") from error
        if confirmed is False:
            raise FailedReplayError("broker did not confirm replayed delivery")
        channel.basic_ack(delivery_tag=delivery_tag)
        self._metrics.replayed += 1
        LOGGER.info(
            "Replayed event %s after original failure: %s; metrics=%s",
            envelope.original_record["event_id"],
            envelope.failure_reason,
            self._metrics,
        )

    def _quarantine_invalid(self, channel: BlockingChannel, body: bytes, reason: str) -> None:
        """Durably preserve a malformed failed envelope before acknowledging it."""
        quarantine_body = json.dumps(
            {
                "replay_error": reason,
                "quarantined_at": time.time(),
                "failed_envelope": body.decode("utf-8", "replace"),
            }
        ).encode("utf-8")
        try:
            confirmed = channel.basic_publish(
                exchange=self._settings.rabbitmq_exchange,
                routing_key=f"{self._settings.rabbitmq_routing_key}.failed.invalid",
                body=quarantine_body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                ),
                mandatory=True,
            )
        except pika.exceptions.AMQPError as error:
            raise FailedReplayError(f"unable to preserve unreplayable delivery: {error}") from error
        if confirmed is False:
            raise FailedReplayError("broker did not confirm unreplayable delivery")

    def close(self) -> None:
        """Close AMQP resources while leaving any unacknowledged message durable."""
        try:
            if self._channel is not None and self._channel.is_open:
                self._channel.close()
            if self._connection is not None and self._connection.is_open:
                self._connection.close()
        except pika.exceptions.AMQPError as error:
            LOGGER.warning("RabbitMQ replay close failed: %s", error)


def _parse_arguments() -> int:
    """Parse the intentionally bounded replay batch size."""
    parser = argparse.ArgumentParser(description="Replay validated ProjectCar failed-queue records.")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of failed records to replay after the root cause is fixed.",
    )
    arguments = parser.parse_args()
    return arguments.limit


def main() -> None:
    """Run an operator-approved failed-message replay batch."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        metrics = FailedMessageReplayer(RabbitMQSettings()).run(_parse_arguments())
        print(f"Replay completed: replayed={metrics.replayed}, quarantined={metrics.quarantined}")
    except (ValidationError, ValueError, FailedReplayError) as error:
        print(f"Replay stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("Replay stopped by Ctrl-C.", file=sys.stderr)


if __name__ == "__main__":
    main()
