"""Reliable AMQP publisher for locally generated telemetry events."""

import json
import logging
from dataclasses import dataclass

import pika
from pika.adapters.blocking_connection import BlockingChannel

from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TelemetryEvent

LOGGER = logging.getLogger(__name__)


class TelemetryPublishError(RuntimeError):
    """Raised when a telemetry event cannot be safely accepted by RabbitMQ."""


def encode_event(event: TelemetryEvent) -> bytes:
    """Serialize a typed event to a compact UTF-8 AMQP message body."""
    try:
        return json.dumps(event.to_record(), separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TelemetryPublishError(f"unable to serialize event {event.event_id}: {error}") from error


@dataclass(slots=True)
class RabbitMQPublisher:
    """Publish persistent telemetry messages after broker confirmation."""

    settings: RabbitMQSettings
    _connection: pika.BlockingConnection | None = None
    _channel: BlockingChannel | None = None

    def connect(self) -> None:
        """Connect and declare the durable exchange and bounded queue.

        Raises:
            TelemetryPublishError: If RabbitMQ cannot be reached or configured.
        """
        try:
            self._connection = pika.BlockingConnection(pika.URLParameters(self.settings.rabbitmq_url))
            self._channel = self._connection.channel()
            self._channel.exchange_declare(
                exchange=self.settings.rabbitmq_exchange,
                exchange_type="direct",
                durable=True,
            )
            self._channel.queue_declare(
                queue=self.settings.rabbitmq_queue,
                durable=True,
                arguments={
                    "x-max-length": self.settings.rabbitmq_max_queue_messages,
                    "x-overflow": "reject-publish",
                },
            )
            self._channel.queue_bind(
                queue=self.settings.rabbitmq_queue,
                exchange=self.settings.rabbitmq_exchange,
                routing_key=self.settings.rabbitmq_routing_key,
            )
            self._channel.confirm_delivery()
        except pika.exceptions.AMQPError as error:
            self.close()
            raise TelemetryPublishError(f"unable to connect to RabbitMQ: {error}") from error

    def publish(self, event: TelemetryEvent) -> None:
        """Publish one persistent event and require broker confirmation.

        Raises:
            TelemetryPublishError: If the broker rejects, cannot route, or loses
                the message before publisher confirmation.
        """
        if self._channel is None or self._channel.is_closed:
            raise TelemetryPublishError("RabbitMQ publisher is not connected")
        try:
            confirmed = self._channel.basic_publish(
                exchange=self.settings.rabbitmq_exchange,
                routing_key=self.settings.rabbitmq_routing_key,
                body=encode_event(event),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    message_id=str(event.event_id),
                    timestamp=int(event.event_time.timestamp()),
                ),
                mandatory=True,
            )
        except (pika.exceptions.AMQPError, OSError) as error:
            raise TelemetryPublishError(f"unable to publish event {event.event_id}: {error}") from error
        # In Pika confirmation mode, a broker rejection raises an AMQP exception.
        # Some supported Pika versions return ``None`` after a successful confirm,
        # while others return ``True``; only an explicit ``False`` is rejection.
        if confirmed is False:
            raise TelemetryPublishError(f"broker did not confirm event {event.event_id}")

    def close(self) -> None:
        """Close open AMQP resources without masking an earlier failure."""
        try:
            if self._channel is not None and self._channel.is_open:
                self._channel.close()
            if self._connection is not None and self._connection.is_open:
                self._connection.close()
        except pika.exceptions.AMQPError as error:
            LOGGER.warning("RabbitMQ resource close failed: %s", error)
        finally:
            self._channel = None
            self._connection = None
