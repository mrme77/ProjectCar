# ProjectCar Handoff

## Status

The complete local-to-Foundry flow is working: route simulator -> RabbitMQ ->
forwarding worker -> Foundry streaming dataset. The `car-project` uv environment
contains the API server runtime, and the complete automated suite passes (30 tests).
RabbitMQ and the Foundry stream have been verified live. The downstream Foundry
pipeline remains future work.

## Repository setup

- Initialized this project as a local Git repository on the `main` branch.
- Added `car-project/` to `.gitignore` so the local virtual environment, like
  caches and `.env*` files, is not tracked.
- Created the initial baseline commit: `chore: initialize project repository`
  (`2b607da`). The working tree was clean after the commit.
- Verification: Git initialized successfully and staged 44 source, test,
  configuration, documentation, and route-data files; no virtual-environment or
  Python cache files were committed.
- Created the public `mrme77/ProjectCar` GitHub repository, added it as `origin`,
  and pushed `main`; the branch now tracks `origin/main`.
- Next: use a review branch and pull request for subsequent changes.

## Working practice

`HANDOFF.md` must be updated after every material project change. Each update must
record the change, available verification, and the next recommended task.

`ARCHITECTURE.md` must be updated whenever components, data flow, delivery
semantics, or external integrations change.

All Python must use concrete type annotations and structured payload types. Expected
errors at process, I/O, configuration, and external-service boundaries require
specific handling that surfaces useful context; do not silently swallow failures.

## Agreed design

The Python simulator is the source of a simulated telemetry stream. It emits a
flat, typed event roughly once per wall-clock second. RabbitMQ buffers the events,
and a separate Python worker forwards them to a Foundry stream later.

```text
Python simulator -> RabbitMQ -> Python forwarding worker -> Foundry stream
                         ^
                    FastAPI control API
```

The Foundry stream is the destination that will be created with the same schema as
the Python event contract. Python creates the ongoing source events; Foundry stores
the received records.

## Route phase

- Added `data/routes/cittadella-del-capo-to-napoli.geojson`, a one-time simplified
  driving route retrieved on 2026-10-11 from the OSRM public demo server using
  OpenStreetMap data. Attribution and source details are embedded in the GeoJSON
  properties and README.
- Source start: Nominatim result for Cittadella del Capo, Calabria
  (`39.5545894, 15.8778941`). The OSRM response snapped the saved route start to
  `39.554673, 15.878057` and its Napoli endpoint to Piazza del Plebiscito
  (`40.836504, 14.248293`). Reported routing distance: 257.1659 km.
- Added local route loading, Haversine segment measurement, distance-based linear
  interpolation, speed-based progression, zero-speed stationary reporting, and
  clamped arrival. None of this contacts a routing service at runtime.
- The simplified GeoJSON's raw geographic segments measure 246.810 km. The route
  progressor scales its segment distances proportionally to the saved OSRM routing
  distance of 257.1659 km, so speed-based arrival calculations use the latter.
- Verified: the local suite passes (9 tests).
- Added `LocalTripSimulator`, which joins route progression to the typed telemetry
  factory. Its `tick(elapsed_seconds)` method is transport-free and emits one
  ordered event with the current route position, speed, distance, and status.
- Added tests for moving and zero-speed event emission. Verified: the local suite
  passes (11 tests).
- Added `car_project.simulator.stream`, a real-time local JSON-lines stream runner.
  It emits an initial origin event and then calls the simulator at one-second
  monotonic-clock intervals; a bounded `--events` option makes it easy to inspect.
- Added a deterministic cadence test. Verified: the local suite passes (12 tests),
  and a three-event live terminal run emitted an origin event followed by two
  approximately one-second movement events at 80 km/h.
- The terminal stream now runs continuously unless `--events` is supplied, prints
  startup details to stderr, and handles Ctrl-C, route/configuration failures, and
  output/file failures at its process boundary. The flat delivery payload is now a
  concrete `TelemetryRecord` `TypedDict`. Verified: the local suite passes (12
  tests), and a bounded two-event terminal stream starts and emits correctly.

## RabbitMQ phase

- Confirmed Docker Desktop 28.4.0 and Docker Compose v2.39.4 are available.
- Added `compose.yaml` for localhost-only RabbitMQ Management with a persistent
  named volume, plus typed settings, a durable AMQP publisher, and a sample-publish
  CLI. The publisher declares a durable direct exchange/queue, requests publisher
  confirmations, marks messages persistent, and uses mandatory routing.
- Added a focused payload-encoding test. RabbitMQ has not yet been started or
  integration-tested; verification is pending.
- Docker Desktop was launched and the RabbitMQ container started. The suite passes
  with 13 tests. An initial live publish exposed a Pika confirmation return-value
  compatibility issue; the publisher now treats an exception or explicit `False`
  as rejection, which matches the observed client behavior.
- Verified: the suite passes (13 tests); a real sample event was publisher-confirmed
  and is retained as one persistent ready message in the durable
  `projectcar.telemetry` queue. The queue is configured with a 10,000-message
  limit and `reject-publish` overflow behavior. The broker remains running.

## Proposed event contract (not finalized)

| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | string | Stable UUID; unchanged on retry. |
| `trip_id` | string | Journey identifier. |
| `vehicle_id` | string | Initially `car-001`. |
| `sequence_number` | integer | Monotonic within a trip. |
| `event_time` | UTC timestamp | Original generated time; unchanged on retry. |
| `latitude` | float | WGS84 coordinate. |
| `longitude` | float | WGS84 coordinate. |
| `speed_kmh` | float | Simulated vehicle speed. |
| `distance_travelled_km` | float | Route-distance progress. |
| `status` | string | `moving`, `stationary`, `arrived`, or `stopped`. |

## Foundry observations

- Dev Tier stream-creation UI is available.
- The UI offers a normal, one-partition option (up to 5 MB/s) and a very-high,
  multi-partition option. Choose normal when the stream is eventually created:
  one car at one event/second requires very little throughput and ordered arrival
  helps debugging.
- Do not assume an endpoint, payload format, stream RID, branch, or credentials.
  Use the environment's generated **Connect -> Push** example and current official
  Foundry documentation when integration begins.

## FastAPI control phase

- Added a typed FastAPI control service at `car_project.api.main` and an in-memory
  `TripManager`. It starts exactly one RabbitMQ-backed route simulator, reports the
  latest in-memory state, updates speed, and requests a clean stop.
- Endpoints: `GET /health`, `POST /trips`, `GET /trips/{trip_id}`, `PATCH
  /trips/{trip_id}/speed`, and `POST /trips/{trip_id}/stop`. Interactive browser
  documentation is available at `/docs` when Uvicorn runs locally.
- The API intentionally needs RabbitMQ but not Foundry credentials. The separate
  worker remains the only process that reads `FOUNDRY_*` settings and delivers to
  Foundry.
- Added local API lifecycle tests using an in-memory publisher, including duplicate
  active-trip rejection, speed change, graceful stop, and unknown-trip `404`.
- Added worker tests for a transient Foundry failure (retry then acknowledgement)
  and permanent failure (durable failed queue before acknowledgement).
- Added `uvicorn` to `requirements.txt`; installed it in the `car-project` virtual
  environment. Verified: `PYTHONPATH=src car-project/bin/python -m compileall -q
  src tests && PYTHONPATH=src car-project/bin/python -m pytest` passes 19 tests.
- Updated `.env.example` with the worker retry/failed-queue settings and the
  current non-secret Foundry variable names. It contains no credential values.

## Failed-message replay phase

- Added `car_project.broker.replay_failed`, an operator-run, bounded replay command:
  `PYTHONPATH=src python -m car_project.broker.replay_failed --limit 10`.
- It unwraps and validates each failed delivery, republishes the original unchanged
  telemetry JSON to `projectcar.telemetry`, waits for RabbitMQ confirmation, and
  only then acknowledges the failed message. The original `event_id` remains intact
  for downstream Foundry deduplication.
- A malformed failed-envelope moves to the new durable
  `projectcar.telemetry.failed.invalid` queue rather than being discarded.
- Added replay transfer and invalid-envelope tests. Verified: compile succeeds and
  the suite passes 21 tests.
- Expanded `README.md` with a local operator guide: the three terminal roles,
  local RabbitMQ ports, Keychain-loaded worker configuration, FastAPI `/docs`
  usage, and plain-language meanings of `GET`, `POST`, and `PATCH`.
- The forwarding worker now uses RabbitMQ's blocking consumer with a 30-second
  inactivity timeout. It remains event-driven and logs a `Still waiting` heartbeat
  when the queue is empty, so an idle terminal is visibly healthy rather than
  appearing stalled. `WORKER_IDLE_HEARTBEAT_SECONDS` is documented in `.env.example`.

## Variable-speed simulation phase

- Added `NormalSpeedProfile`: speed samples vary around the requested target using
  a normal distribution, are bounded to 0–250 km/h, and can change by at most
  10 km/h per second. A zero target remains stationary.
- The terminal simulator accepts `--speed-variation-kmh` (default `5`) and optional
  `--random-seed`; setting variation to `0` preserves constant-speed behavior.
- FastAPI `POST /trips` now accepts `speed_variation_kmh` and `random_seed`.
  Responses distinguish the current sampled `speed_kmh` from `target_speed_kmh`.
- Added deterministic normal-profile tests; verification passes 25 tests.

## Traffic-stop simulation phase

- Added a traffic-stop controller with 30 default simulated lights: 15 across the
  first 3% of the route and 15 across the final 3%. The highway segment has no
  planned stops. This is deliberately a documented simulation rule, not map-derived
  traffic-light data.
- Each stop has a seeded-random 20–60 second duration. The car brakes toward it,
  emits stationary zero-speed events while waiting, then resumes normal speed
  variation. The terminal and FastAPI both accept an even `traffic_stop_count`;
  `0` disables the model.
- Added traffic-plan/braking/stationary-event tests. Verified: compile succeeds and
  the complete suite passes 28 tests.

## Road-speed zone phase

- Replaced the single normal driving target with route-speed zones: the first and
  final 3% use a 60 km/h urban target bounded from 50–70 km/h; the central highway
  uses a 140 km/h target. The traffic controller still overrides either zone to
  brake and stop at lights.
- The terminal `--speed-kmh` option now means highway target (default `140`), and
  `--urban-speed-kmh` controls the urban target (default `60`). FastAPI exposes the
  same fields and distinguishes highway, urban, normal-zone target, and sampled
  current speed in its responses.
- Added road-zone tests. Verified: compile succeeds and the complete suite passes
  29 tests.
- The terminal simulator now accepts `--vehicle-id` (default `car-001`) so Bash
  runs can emit distinct cars such as `car-002` without editing Python code. Added
  a CLI parsing test; the complete suite passes 30 tests.

## Next recommended task

With a known-valid Foundry worker running, replay the previously failed records in
small batches and verify they reach Foundry. Then implement the Foundry streaming
pipeline for validation and event-id-based deduplication.

## Foundry verification

- The direct Python probe successfully received `204 No Content` from the
  environment-generated Foundry stream publish endpoint. This verifies the personal
  token, stream Dataset RID, branch, request shape, and authentication path.
- The first accepted event used the current `FOUNDRY_PREVIEW` setting. Confirm its
  visibility in the stream's Dataset app before treating preview mode as the normal
  production-write setting.
- Verified in the Foundry Dataset app: the direct probe's accepted records appear
  in the stream. They are stationary by design because the probe currently emits
  `speed_kmh = 0.0` and zero travelled distance.
- Next: implement the RabbitMQ forwarding worker to call this same verified endpoint
  and acknowledge messages only after Foundry accepts them.
- Added the RabbitMQ forwarding worker. It uses manual acknowledgments with bounded
  prefetch, calls the verified Foundry endpoint, and acknowledges only after a
  successful HTTP response. On Foundry or malformed-message failure it requeues the
  delivery and stops, preventing a busy retry loop. Added focused decoding tests;
  local verification passes (15 tests). Live verification succeeded on 2026-10-12:
  the worker forwarded two queued events, Foundry accepted both, and the worker
  acknowledged them afterward.
- The simulator runner now supports `--publish-rabbitmq` as the real transport and
  `--print-events` as an optional JSON diagnostic sink. Verified: all 15 local
  tests pass and a bounded two-event JSON diagnostic run succeeds.
- Live end-to-end movement verification succeeded: five route-progressing simulator
  events were published to RabbitMQ, accepted by the worker, and appeared in the
  Foundry stream. The core pipeline is now functional.
- Added bounded worker retry handling for transient Foundry failures and a durable
  `projectcar.telemetry.failed` queue for malformed or permanently rejected
  deliveries. The worker logs delivered, retried, and failed counts. Local
  verification passes (15 tests); live failure-path verification remains pending.

- Route source, saved geometry format, attribution, and exact route distance.
- Default/allowed speed range.
- Foundry hostname, stream/dataset RID, branch, authentication method, and write
  permission once the stream is created.
- Mac Python tooling and Docker/container-runtime availability.
- Raspberry Pi hardware/OS only when deployment is in scope.
