"""Forward RabbitMQ telemetry records to the configured Foundry stream."""

import json
import logging
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import pika
import requests
from pika.adapters.blocking_connection import BlockingChannel
from pydantic import ValidationError

from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TelemetryRecord

LOGGER = logging.getLogger(__name__)


class FoundryDeliveryError(RuntimeError):
    """Raised when Foundry does not accept a queued telemetry record."""

    def __init__(self, message: str, transient: bool) -> None:
        """Describe whether the failed request is safe to retry automatically."""
        super().__init__(message)
        self.transient = transient


def required_setting(name: str) -> str:
    """Read required runtime configuration without including values in errors."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"required environment variable {name} is not set")
    return value


def decode_record(body: bytes) -> TelemetryRecord:
    """Decode a JSON broker message into the flat telemetry-record shape."""
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"message is not valid UTF-8 JSON: {error}") from error
    if not isinstance(decoded, Mapping):
        raise ValueError("message JSON must be an object")
    required_fields = set(TelemetryRecord.__annotations__)
    if not required_fields.issubset(decoded):
        raise ValueError("message JSON is missing required telemetry fields")
    return cast(TelemetryRecord, dict(decoded))


@dataclass(frozen=True, slots=True)
class FoundryTarget:
    """Non-secret Foundry target configuration plus a runtime bearer token."""

    hostname: str
    dataset_rid: str
    branch: str
    token: str
    preview: str

    @classmethod
    def from_environment(cls) -> "FoundryTarget":
        """Load the verified Foundry endpoint configuration from environment variables."""
        return cls(
            hostname=required_setting("FOUNDRY_HOSTNAME").removeprefix("https://").rstrip("/"),
            dataset_rid=required_setting("FOUNDRY_STREAM_RID"),
            branch=os.environ.get("FOUNDRY_BRANCH", "master"),
            token=required_setting("FOUNDRY_TOKEN"),
            preview=os.environ.get("FOUNDRY_PREVIEW", "true"),
        )

    @property
    def publish_url(self) -> str:
        """Return Foundry's environment-generated high-scale stream endpoint."""
        return (
            f"https://{self.hostname}/api/v2/highScale/streams/datasets/"
            f"{self.dataset_rid}/streams/{self.branch}/publishRecords"
        )

    def publish(self, record: TelemetryRecord) -> None:
        """Send one queued record to Foundry or raise a delivery error."""
        try:
            response = requests.post(
                self.publish_url,
                params={"preview": self.preview},
                json={"records": [record]},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else "no response"
            transient = status == "no response" or status == 408 or status == 429 or int(status) >= 500
            raise FoundryDeliveryError(
                f"Foundry delivery failed (status: {status})", transient=transient
            ) from error


@dataclass(slots=True)
class DeliveryMetrics:
    """In-memory counts emitted in worker logs for operational visibility."""

    delivered: int = 0
    retried: int = 0
    failed: int = 0


class RabbitMQForwardingWorker:
    """Consume telemetry manually and acknowledge only after Foundry accepts it."""

    def __init__(self, settings: RabbitMQSettings, target: FoundryTarget) -> None:
        """Configure a worker; resources are opened only by :meth:`run`."""
        self._settings = settings
        self._target = target
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None
        self._metrics = DeliveryMetrics()

    def run(self) -> None:
        """Consume messages until interrupted, logging periodic idle heartbeats."""
        try:
            self._connection = pika.BlockingConnection(pika.URLParameters(self._settings.rabbitmq_url))
            self._channel = self._connection.channel()
            self._channel.exchange_declare(
                exchange=self._settings.rabbitmq_exchange,
                exchange_type="direct",
                durable=True,
            )
            self._channel.queue_declare(queue=self._settings.rabbitmq_failed_queue, durable=True)
            self._channel.queue_bind(
                queue=self._settings.rabbitmq_failed_queue,
                exchange=self._settings.rabbitmq_exchange,
                routing_key=f"{self._settings.rabbitmq_routing_key}.failed",
            )
            self._channel.confirm_delivery()
            self._channel.basic_qos(prefetch_count=self._settings.rabbitmq_prefetch_count)
            LOGGER.info("Waiting for telemetry messages on %s", self._settings.rabbitmq_queue)
            for method, properties, body in self._channel.consume(
                queue=self._settings.rabbitmq_queue,
                auto_ack=False,
                inactivity_timeout=self._settings.worker_idle_heartbeat_seconds,
            ):
                if method is None:
                    LOGGER.info(
                        "Still waiting for telemetry messages on %s",
                        self._settings.rabbitmq_queue,
                    )
                    continue
                if body is None:
                    raise RuntimeError("RabbitMQ delivery did not include a message body")
                self._on_message(self._channel, method, properties, body)
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"RabbitMQ worker failure: {error}") from error
        finally:
            self.close()

    def _on_message(self, channel: BlockingChannel, method: object, _properties: object, body: bytes) -> None:
        """Forward one delivery and retain it in RabbitMQ if Foundry delivery fails."""
        delivery_tag = getattr(method, "delivery_tag", None)
        if not isinstance(delivery_tag, int):
            raise RuntimeError("RabbitMQ delivery did not include an integer delivery tag")
        try:
            record = decode_record(body)
        except ValueError as error:
            self._send_to_failed_queue(channel, body, str(error))
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        for attempt in range(1, self._settings.worker_max_delivery_attempts + 1):
            try:
                self._target.publish(record)
                channel.basic_ack(delivery_tag=delivery_tag)
                self._metrics.delivered += 1
                LOGGER.info("Foundry accepted event %s; metrics=%s", record["event_id"], self._metrics)
                return
            except FoundryDeliveryError as error:
                if not error.transient or attempt == self._settings.worker_max_delivery_attempts:
                    self._send_to_failed_queue(channel, body, str(error))
                    channel.basic_ack(delivery_tag=delivery_tag)
                    return
                delay = self._settings.worker_retry_base_seconds * (2 ** (attempt - 1))
                self._metrics.retried += 1
                LOGGER.warning("Retrying event %s in %.1fs: %s", record["event_id"], delay, error)
                time.sleep(delay)

    def _send_to_failed_queue(self, channel: BlockingChannel, body: bytes, reason: str) -> None:
        """Persist a permanently failed delivery before acknowledging the source message."""
        failure_record = json.dumps(
            {"failure_reason": reason, "failed_at": time.time(), "original_body": body.decode("utf-8", "replace")}
        ).encode("utf-8")
        try:
            confirmed = channel.basic_publish(
                exchange=self._settings.rabbitmq_exchange,
                routing_key=f"{self._settings.rabbitmq_routing_key}.failed",
                body=failure_record,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=pika.DeliveryMode.Persistent),
                mandatory=True,
            )
        except pika.exceptions.AMQPError as error:
            raise RuntimeError(f"unable to preserve failed delivery: {error}") from error
        if confirmed is False:
            raise RuntimeError("broker did not confirm failed delivery")
        self._metrics.failed += 1
        LOGGER.error("Moved delivery to failed queue; metrics=%s; reason=%s", self._metrics, reason)

    def close(self) -> None:
        """Close the worker's resources while preserving unacknowledged deliveries."""
        try:
            if self._channel is not None and self._channel.is_open:
                self._channel.close()
            if self._connection is not None and self._connection.is_open:
                self._connection.close()
        except pika.exceptions.AMQPError as error:
            LOGGER.warning("RabbitMQ worker close failed: %s", error)


def main() -> None:
    """Run the worker with Foundry credentials supplied by the local environment."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        worker = RabbitMQForwardingWorker(RabbitMQSettings(), FoundryTarget.from_environment())
        worker.run()
    except (ValidationError, ValueError, RuntimeError) as error:
        print(f"Forwarding worker stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("Forwarding worker stopped by Ctrl-C.", file=sys.stderr)


if __name__ == "__main__":
    main()
