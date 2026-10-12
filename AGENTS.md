# ProjectCar — Agent Instructions

## Project purpose

Build a learning project that simulates one vehicle's road telemetry, publishes it
through RabbitMQ, and forwards it to a Palantir Foundry streaming dataset. The
initial goal is a reliable local ingestion pipeline; a Foundry map is a later phase.

## Current phase

No application code or Foundry resources have been created yet. Begin by defining
and locally validating the Python telemetry event contract. Do not create or alter
Foundry streams until the event schema has been reviewed and agreed.

## Architecture boundaries

- Python simulator produces one telemetry event per wall-clock second.
- FastAPI controls the simulator; it does not ingest into Foundry directly.
- RabbitMQ is the durable local buffer between simulator and forwarding worker.
- A Python forwarding worker calls Foundry's documented push-stream API.
- Foundry does not connect to the local FastAPI service or RabbitMQ.

## Engineering constraints

- Use Python with complete type hints and focused pytest coverage.
- Use concrete return types and structured types such as dataclasses, enums, and
  `TypedDict` instead of untyped dictionaries or `Any`.
- Handle expected failures at process, I/O, configuration, and external-service
  boundaries with specific `try`/`except` clauses. Log or surface actionable
  context and either recover deliberately or re-raise; never silently swallow an
  exception or use a blanket `except Exception` for normal control flow.
- Keep simulator, API, broker, and Foundry client responsibilities separate.
- Keep generated telemetry flat and typed; match the agreed Foundry stream schema.
- Preserve `event_id` and `event_time` on every retry.
- Describe delivery as at least once, never exactly once end to end.
- Acknowledge RabbitMQ messages only after documented Foundry acceptance.
- Keep secrets in environment variables or an ignored local `.env` file; never log
  or commit credentials. Maintain `.env.example` with names only.
- Bind development services to localhost by default.
- Do not invent Foundry API paths, request payloads, or authentication flows.
  Verify current official, environment-generated Foundry guidance first.

## Simulation rules

- One vehicle: `car-001`; one clean journey initially.
- Emit an event every real second, including while speed is zero.
- Changing speed changes distance travelled, not event frequency.
- Use saved road-route geometry and interpolate by distance along that geometry.
- Clamp arrival at the destination, emit a final `arrived` event, and stop.
- A stopped trip is distinct from a zero-speed stationary trip.

## Collaboration

- Explain important design choices so the project remains a learning exercise.
- Update `HANDOFF.md` after every material change, including what changed, what
  was verified, and the next recommended task. Treat this as a required global
  project practice, not an end-of-phase cleanup step.
- Keep `ARCHITECTURE.md` current whenever a component, data flow, delivery
  guarantee, or external integration changes.
- Make routine implementation decisions; ask before choices that materially change
  the architecture or require Foundry credentials/access.
- Do not commit, push, or create Foundry resources without the user's explicit
  request.
