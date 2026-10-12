# ProjectCar Architecture

## Purpose

ProjectCar simulates one car's telemetry locally, buffers events reliably, and
publishes them to a Palantir Foundry streaming dataset.

## Current validated flow

```text
Python direct probe on Mac
    |
    | HTTPS: Foundry stream Push API
    v
Foundry streaming dataset
    |
    v
Foundry Dataset app
```

The direct probe has been verified: Foundry returned `204 No Content`, and the
stationary test records appeared in the Dataset app.

The complete moving path is also verified: the simulator published five moving
events to RabbitMQ, the worker forwarded them, and they appeared in Foundry.

## Local control and delivery flow

```text
FastAPI control API
    |
    | start / speed / status / stop
    v
Python route simulator -- one typed event per wall-clock second
    |
    | AMQP persistent publish + broker confirmation
    v
RabbitMQ durable queue
    |
    | manual delivery
    v
Python forwarding worker
    |
    | HTTPS stream Push API
    v
Foundry streaming dataset
    |
    v
Foundry streaming pipeline and downstream analytics
```

## Component responsibilities

| Component | Responsibility | Current state |
| --- | --- | --- |
| Route simulator | Builds positions and telemetry events along saved road geometry. | Implemented locally. |
| FastAPI | Controls one trip; it does not deliver events to Foundry. | Implemented and unit-tested locally. |
| RabbitMQ | Buffers persistent telemetry between producer and worker. | Running locally; sample publish verified. |
| Forwarding worker | Sends RabbitMQ records to Foundry and acknowledges after acceptance. | Implemented and live verified. |
| Foundry stream | Receives schema-compatible telemetry records. | Created and direct API publish verified. |
| Foundry pipeline | Validates, transforms, and handles duplicate events downstream. | Not implemented. |

## API control semantics

- The FastAPI process exposes interactive documentation at `/docs` and uses an
  in-memory `TripManager`; it is a control plane, not a dashboard or broker.
- `POST /trips` connects a RabbitMQ publisher before it starts its background
  simulator loop. A connection failure returns an HTTP error rather than creating
  a trip that cannot deliver.
- The controller intentionally permits one active trip at a time for this learning
  project. It emits an initial origin event immediately and then one event per
  second until stopped or the route arrives.
- `PATCH /trips/{trip_id}/speed` changes the speed used by the next event.
  `POST /trips/{trip_id}/stop` signals the loop and releases the publisher.
- API lifecycle state is not durable. RabbitMQ remains the durable boundary: once
  an event has a broker confirmation, it survives API-process restart.

## Event delivery semantics

- The simulator treats `speed_kmh` as the actual sampled speed for an event. It
  uses a bounded normal distribution around a target speed and limits acceleration
  and braking to 10 km/h per second. A supplied random seed makes that test pattern
  reproducible; variation `0` produces constant speed.
- The default traffic model creates 30 simulated stops, split equally across the
  first and final 3% of the route. Each stop lasts 20–60 seeded-random seconds;
  traffic approach disables speed variation and brakes toward the light. During a
  stop, the event has zero speed, unchanged distance, and `stationary` status.
  This is a simulation rule, not real traffic-light data from the GeoJSON route.
- Normal driving is zone-based: the first and final 3% use an urban target of
  60 km/h bounded to 50–70 km/h, while the central route uses a 140 km/h highway
  target. The existing acceleration limit makes zone transitions gradual.
- Events have stable `event_id` values and retain their original `event_time` on retry.
- RabbitMQ publisher confirmation means the broker accepted an event, not that Foundry did.
- The worker acknowledges a message only after Foundry accepts it.
- Transient Foundry failures are retried with bounded exponential backoff. Permanent
  or malformed deliveries are copied to the durable failed-events queue before the
  source delivery is acknowledged.
- After an operator fixes the root cause, the bounded replay command validates each
  failed-envelope, republishes its original telemetry body to the normal queue, and
  acknowledges the failed message only after broker confirmation. An invalid
  envelope is preserved separately in `projectcar.telemetry.failed.invalid`.
- Delivery is at least once: a worker failure after Foundry accepts an event but before
  RabbitMQ acknowledgment can cause redelivery.
- Downstream Foundry processing must use `event_id` for duplicate handling.

## Local observability

The simulator's `--print-events` option is an optional JSON-lines diagnostic sink.
`--publish-rabbitmq` is the actual transport option; both can be enabled together,
and records are printed only after RabbitMQ confirms the publish.

## Configuration and security

- Foundry credentials remain outside the repository. `FOUNDRY_TOKEN` is loaded from
  the user's Keychain into the local process environment.
- RabbitMQ is containerized, bound to localhost, and stores data in a Docker volume.
- Dataset RID, branch, hostname, and queue settings are configuration—not secrets.
- The FastAPI process does not need Foundry credentials; only the forwarding worker
  requires the `FOUNDRY_*` configuration.
- The replay command requires only RabbitMQ configuration; it never receives or
  uses the Foundry token.
