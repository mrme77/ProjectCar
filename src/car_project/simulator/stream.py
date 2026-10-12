"""Run the local trip simulator as a real-time JSON event stream."""

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
from time import monotonic, sleep

from car_project.broker.publisher import RabbitMQPublisher, TelemetryPublishError
from car_project.broker.settings import RabbitMQSettings
from car_project.domain.telemetry import TelemetryEvent, TripStatus
from car_project.simulator.route import Route
from car_project.simulator.trip import LocalTripSimulator

DEFAULT_ROUTE_PATH = (
    Path(__file__).resolve().parents[3] / "data/routes/cittadella-del-capo-to-napoli.geojson"
)


@dataclass(frozen=True, slots=True)
class StreamArguments:
    """Validated command-line settings for a local stream process."""

    speed_kmh: float
    vehicle_id: str
    urban_speed_kmh: float
    speed_variation_kmh: float
    random_seed: int | None
    traffic_stop_count: int
    event_limit: int | None
    publish_rabbitmq: bool
    print_events: bool


def run_stream(
    simulator: LocalTripSimulator,
    emit: Callable[[TelemetryEvent], None],
    event_limit: int | None = None,
    interval_seconds: float = 1.0,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> None:
    """Emit telemetry at a fixed wall-clock cadence until arrival or a limit.

    Args:
        simulator: Local trip source to advance and report.
        emit: Function receiving each generated telemetry event.
        event_limit: Optional maximum number of events to produce.
        interval_seconds: Wall-clock interval between reports.
        clock: Monotonic clock dependency used for elapsed movement time.
        sleeper: Sleep dependency used to wait for the next report.
    """
    if event_limit is not None and event_limit < 1:
        raise ValueError("event_limit must be at least 1 when provided")
    if interval_seconds <= 0.0:
        raise ValueError("interval_seconds must be positive")

    previous_tick = clock()
    next_scheduled_tick = previous_tick
    emitted_count = 0
    while event_limit is None or emitted_count < event_limit:
        now = clock()
        elapsed_seconds = 0.0 if emitted_count == 0 else max(0.0, now - previous_tick)
        event = simulator.tick(elapsed_seconds)
        emit(event)
        emitted_count += 1
        if event.status is TripStatus.ARRIVED:
            return

        previous_tick = now
        next_scheduled_tick += interval_seconds
        sleeper(max(0.0, next_scheduled_tick - clock()))


def _print_json(event: TelemetryEvent) -> None:
    """Write one JSON event line immediately so terminals display a live stream."""
    print(json.dumps(event.to_record()), flush=True)


def make_emitter(
    publisher: RabbitMQPublisher | None, print_events: bool
) -> Callable[[TelemetryEvent], None]:
    """Create a transport callback with optional terminal JSON diagnostics."""
    if publisher is None and not print_events:
        raise ValueError("select --publish-rabbitmq, --print-events, or both")

    def emit(event: TelemetryEvent) -> None:
        """Publish first so printed records represent broker-confirmed events."""
        if publisher is not None:
            publisher.publish(event)
        if print_events:
            _print_json(event)

    return emit


def _parse_arguments() -> StreamArguments:
    """Parse command-line arguments into a typed stream configuration."""
    parser = argparse.ArgumentParser(description="Run a local ProjectCar telemetry stream.")
    parser.add_argument(
        "--speed-kmh",
        type=float,
        default=140.0,
        help="Target speed for the central highway segment.",
    )
    parser.add_argument(
        "--vehicle-id",
        type=str,
        default="car-001",
        help="Vehicle identifier emitted with every event for this trip.",
    )
    parser.add_argument(
        "--urban-speed-kmh",
        type=float,
        default=60.0,
        help="Target speed in the two urban route sections; must be between 50 and 70.",
    )
    parser.add_argument(
        "--speed-variation-kmh",
        type=float,
        default=5.0,
        help="Normal-distribution speed variation in km/h; use 0 for constant speed.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help="Optional seed that makes speed variation reproducible for testing.",
    )
    parser.add_argument(
        "--traffic-stop-count",
        type=int,
        default=30,
        help="Even number of simulated urban traffic stops; use 0 to disable them.",
    )
    parser.add_argument(
        "--events",
        type=int,
        default=None,
        help="Optional number of one-second events to print; omit to run until stopped.",
    )
    parser.add_argument(
        "--publish-rabbitmq",
        action="store_true",
        help="Publish each event to RabbitMQ using the configured durable queue.",
    )
    parser.add_argument(
        "--print-events",
        action="store_true",
        help="Print JSON events to stdout after any RabbitMQ publish succeeds.",
    )
    parsed = parser.parse_args()
    return StreamArguments(
        speed_kmh=parsed.speed_kmh,
        vehicle_id=parsed.vehicle_id,
        urban_speed_kmh=parsed.urban_speed_kmh,
        speed_variation_kmh=parsed.speed_variation_kmh,
        random_seed=parsed.random_seed,
        traffic_stop_count=parsed.traffic_stop_count,
        event_limit=parsed.events,
        publish_rabbitmq=parsed.publish_rabbitmq,
        print_events=parsed.print_events,
    )


def main() -> None:
    """Start a continuous local stream and handle normal terminal shutdown safely."""
    publisher: RabbitMQPublisher | None = None
    try:
        arguments = _parse_arguments()
        route = Route.from_geojson(DEFAULT_ROUTE_PATH)
        simulator = LocalTripSimulator(
            route=route,
            speed_kmh=arguments.speed_kmh,
            vehicle_id=arguments.vehicle_id,
            speed_variation_kmh=arguments.speed_variation_kmh,
            random_seed=arguments.random_seed,
            traffic_stop_count=arguments.traffic_stop_count,
            urban_speed_kmh=arguments.urban_speed_kmh,
        )
        if arguments.publish_rabbitmq:
            publisher = RabbitMQPublisher(RabbitMQSettings())
            publisher.connect()
        print(
            f"Starting trip {simulator.trip_id}: highway target {arguments.speed_kmh:g} km/h, "
            f"urban target {arguments.urban_speed_kmh:g} km/h, "
            f"with ±{arguments.speed_variation_kmh:g} km/h variation; "
            f"{arguments.traffic_stop_count} planned traffic stops; "
            f"route distance {route.total_distance_km:.3f} km.",
            file=sys.stderr,
        )
        run_stream(
            simulator,
            make_emitter(publisher, print_events=arguments.print_events),
            event_limit=arguments.event_limit,
        )
    except KeyboardInterrupt:
        print("Simulator stopped by Ctrl-C.", file=sys.stderr)
    except ValueError as error:
        print(f"Simulator configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except (OSError, BrokenPipeError) as error:
        print(f"Simulator output or file error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except TelemetryPublishError as error:
        print(f"RabbitMQ publish error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if publisher is not None:
            publisher.close()


if __name__ == "__main__":
    main()
