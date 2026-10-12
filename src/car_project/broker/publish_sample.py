"""Publish one locally generated telemetry record to RabbitMQ."""

import sys

from pydantic import ValidationError

from car_project.broker.publisher import RabbitMQPublisher, TelemetryPublishError
from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


def main() -> None:
    """Connect, publish one durable sample, and close the broker connection."""
    publisher: RabbitMQPublisher | None = None
    try:
        settings = RabbitMQSettings()
        publisher = RabbitMQPublisher(settings)
        publisher.connect()
        event = TelemetrySampleFactory().create_event(
            latitude=39.554673,
            longitude=15.878057,
            speed_kmh=0.0,
            distance_travelled_km=0.0,
            status=TripStatus.STATIONARY,
        )
        publisher.publish(event)
        print(f"Published confirmed event {event.event_id}.")
    except ValidationError as error:
        print(f"RabbitMQ configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except TelemetryPublishError as error:
        print(f"RabbitMQ publish error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("Sample publish stopped by Ctrl-C.", file=sys.stderr)
    finally:
        if publisher is not None:
            publisher.close()


if __name__ == "__main__":
    main()
