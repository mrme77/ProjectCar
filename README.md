# ProjectCar

ProjectCar simulates one car's road telemetry, buffers the records in RabbitMQ,
and forwards them to a Palantir Foundry streaming dataset.

## Current stage

The local end-to-end delivery path is verified: simulator to RabbitMQ to worker to
Foundry. A FastAPI control service is implemented and tested locally; it starts,
inspects, adjusts, and stops one simulator trip at a time. The Foundry downstream
pipeline is still future work.

## Local environment

The requested environment name is `car-project`. Once it has been created, install
the project dependencies from `requirements.txt` and run the telemetry tests.

```text
uv venv car-project
source car-project/bin/activate
uv pip install -r requirements.txt
PYTHONPATH=src pytest
```

`car-project` is ignored by Git through `.gitignore`. Copy `.env.example` to `.env`
only when configuration is needed, and never commit its secrets.

## Run the application locally

ProjectCar uses three separate processes. Keep each one in its own terminal so
each job has one clear responsibility:

```text
Terminal 1: RabbitMQ    stores events safely
Terminal 2: Worker      sends queued events to Foundry
Terminal 3: FastAPI     starts and controls the simulated car
```

### 1. Start RabbitMQ

From the project directory, start the local Docker container:

```text
docker compose up -d
```

RabbitMQ exposes two local ports:

| Address | Used by | Purpose |
| --- | --- | --- |
| `localhost:5672` | Python programs | AMQP message connection. |
| `http://localhost:15672` | Your browser | RabbitMQ management page. |

The Python processes connect to `localhost:5672`; Docker forwards that connection
to RabbitMQ inside the container. They do not read Docker files or connect to
Foundry through the RabbitMQ container.

### 2. Start the Foundry forwarding worker

In a new terminal, activate the environment and load your Foundry settings. Keep
the real token in macOS Keychain; this command reads it into this terminal only:

```text
source car-project/bin/activate
export FOUNDRY_TOKEN="$(security find-generic-password -a "$USER" -s FOUNDRY_TOKEN -w)"
export FOUNDRY_HOSTNAME="sasamen.usw-23.palantirfoundry.com"
export FOUNDRY_STREAM_RID="ri.foundry.main.dataset.b1a10d00-d9cb-4161-9afd-f87c8fff6d6a"
export FOUNDRY_BRANCH="master"
export FOUNDRY_PREVIEW="true"
PYTHONPATH=src python -m car_project.broker.worker
```

The worker connects to local RabbitMQ, reads messages from
`projectcar.telemetry`, and sends them to Foundry over HTTPS. It is the only
ProjectCar process that needs the Foundry token.

When delivery succeeds, it logs `Foundry accepted event ...`. A temporary Foundry
problem is retried; a permanent rejection is kept in
`projectcar.telemetry.failed`. When no message arrives, it remains ready without
using CPU and logs `Still waiting for telemetry messages ...` every 30 seconds.

### 3. Start the FastAPI control service

In a third terminal:

```text
source car-project/bin/activate
PYTHONPATH=src python -m uvicorn car_project.api.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. `127.0.0.1` means this Mac only; it does not
make your control page public on the internet.

FastAPI is the controller, not the telemetry delivery system. It tells the local
simulator to start, change speed, or stop. The simulator still publishes data to
RabbitMQ, and the separate worker sends that data to Foundry.

### 4. Start and control a trip in `/docs`

On the FastAPI documentation page:

1. Open `POST /trips`.
2. Choose **Try it out**.
3. Use a request body such as:

   ```json
   {
     "speed_kmh": 140,
     "urban_speed_kmh": 60,
     "speed_variation_kmh": 5,
     "traffic_stop_count": 30,
     "vehicle_id": "car-001"
   }
   ```

4. Choose **Execute**.
5. Copy the returned `trip_id`. It is the reference number for that running trip.

Then use that `trip_id` with the other endpoint rows:

| Request | Everyday meaning | Changes data? |
| --- | --- | --- |
| `GET /health` | “Is the control service running?” | No. |
| `POST /trips` | “Create and start a new car trip.” | Yes. |
| `GET /trips/{trip_id}` | “Show me this trip's latest known state.” | No. |
| `PATCH /trips/{trip_id}/speed` | “Change only this trip's speed.” | Yes. |
| `POST /trips/{trip_id}/stop` | “Request a clean stop for this trip.” | Yes. |

`GET` asks for information without changing anything. `POST` starts an action or
creates something. `PATCH` changes one part of something that already exists.

`speed_kmh` is the target for the central highway section; its default is 140 km/h.
`urban_speed_kmh` is the target near the route ends; its default is 60 km/h and is
bounded from 50 to 70 km/h. The simulator samples a normal distribution around the
active road-zone target and limits speed changes to 10 km/h per second, so a car
does not make unrealistic jumps. `speed_variation_kmh` is the size of the usual
variation; the default `5` creates a gentle pattern around the target. Set it to
`0` to remove random variation within each road zone. Optionally include
`random_seed` to reproduce exactly the same variable-speed pattern in a later test
run.

The default trip also includes 30 simulated traffic lights: 15 in the first 3% of
the route and 15 in the final 3%, with no planned lights on the highway portion.
Each stop lasts a seeded-random 20–60 seconds. The car brakes toward the light,
reports `speed_kmh: 0.0` and `status: "stationary"` while waiting, then resumes
normal variable-speed driving. These are realistic simulation rules, not a claim
that the saved route contains exactly 30 real traffic lights. Set
`traffic_stop_count` to `0` to disable them; otherwise use an even number.

After a trip starts, the simulator creates one event per second. The worker should
show accepted-event logs, and the records should appear in the Foundry stream.
Use `POST /trips/{trip_id}/stop` when you are finished. Stopping FastAPI or letting
Uvicorn reload it also stops the in-memory controller; RabbitMQ still retains any
events it already confirmed.

## Event contract

Each event is flat and typed: stable event/trip IDs, a UTC event timestamp, WGS84
coordinates, speed, travelled route distance, and a lifecycle status. See
`src/car_project/domain/telemetry.py` for the locally validated model.

## Generate a local sample event

Run the following command while the `car-project` environment is active:

```text
PYTHONPATH=src python -m car_project.simulator.sample
```

It prints one JSON record using the same fields and `DOUBLE`-compatible numeric
values that will later be configured in the Foundry stream.

## Saved road route

The simulator uses the checked-in GeoJSON asset at
`data/routes/cittadella-del-capo-to-napoli.geojson`; it never calls a routing
service while running. The asset was retrieved on 2026-10-11 from the OSRM public
demo server using OpenStreetMap data. It uses a Cittadella del Capo location
returned by Nominatim and routes to Piazza del Plebiscito, where OSRM snapped the
Napoli endpoint. The routing response reported 257.1659 km.
The simplified line's raw geographic segments total about 246.810 km, so the
simulator proportionally scales those segments to the preserved 257.1659 km routing
distance. This keeps both the saved geometry and realistic arrival-time calculation.

## Watch the local live stream

The command below prints five newline-delimited JSON events. The first event reports
the origin immediately; every later event is emitted one wall-clock second apart.

```text
PYTHONPATH=src python -m car_project.simulator.stream --speed-kmh 140 --events 5 --print-events
```

Omit `--events` for a continuous stream. Press Ctrl-C to stop it cleanly.

The default speed profile uses 60 km/h urban zones at the two route ends and a
140 km/h highway zone in the middle. It varies gently around the active zone target
using a bounded normal distribution. Use `--speed-variation-kmh 0` to remove random
variation, or use a seed when you need the same variable pattern again:

```text
PYTHONPATH=src python -m car_project.simulator.stream \
  --vehicle-id car-002 \
  --speed-kmh 140 \
  --urban-speed-kmh 60 \
  --speed-variation-kmh 5 \
  --traffic-stop-count 30 \
  --random-seed 42 \
  --events 5 \
  --print-events
```

To publish the same live events to RabbitMQ, add `--publish-rabbitmq`. Add
`--print-events` as well when you also want to inspect every JSON record locally.
Use `--traffic-stop-count 0` for a no-stop route test; the default is 30.

## RabbitMQ (local development)

RabbitMQ is configured only on `localhost` and persists broker data in a named
Docker volume. Start it with:

```text
docker compose up -d
```

Its management UI is at `http://localhost:15672`. Copy `.env.example` to `.env`
before changing the development credentials; do not commit `.env`.

Publish one confirmed, persistent sample message with:

```text
PYTHONPATH=src python -m car_project.broker.publish_sample
```

The publisher uses a durable direct exchange and durable queue, persistent
messages, publisher confirms, mandatory routing, and a maximum queue length of
10,000 messages. When full, the queue rejects new publishes, allowing the simulator
to pause or fail visibly instead of silently losing telemetry.

The forwarding worker retries transient Foundry failures up to three times with
exponential delays of one and two seconds. A malformed message or a permanent
Foundry rejection is preserved in the durable `projectcar.telemetry.failed` queue
before the original message is acknowledged.

### Replay failed records

Replay is a deliberate operator action, not an automatic loop. First fix the
underlying problem (for example, reload a valid Foundry token) and start the normal
forwarding worker. Then replay a small batch from a separate terminal:

```text
PYTHONPATH=src python -m car_project.broker.replay_failed --limit 10
```

For each item, the replay command validates the failed-message envelope, republishes
its original telemetry JSON to `projectcar.telemetry`, waits for RabbitMQ's publish
confirmation, and only then acknowledges the failed item. The original `event_id`
is unchanged. The normal worker then sends it to Foundry.

An invalid failed-message envelope is not discarded; it is moved to
`projectcar.telemetry.failed.invalid` for manual inspection. Do not replay messages
until the cause of failure is resolved, or the worker will put them back into the
failed queue.

OpenStreetMap data is © OpenStreetMap contributors and available under the
[Open Database License](https://www.openstreetmap.org/copyright). This saved,
simplified route is suitable for this learning simulator; use an appropriately
provisioned routing service and review its policy before production use.
