"""Send one typed telemetry event to the configured Foundry stream."""

import os
import sys

import requests

from car_project.domain.telemetry import TripStatus
from car_project.simulator.sample import TelemetrySampleFactory


def setting(name: str) -> str:
    """Return a required environment setting without revealing its value."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"required environment variable {name} is not set")
    return value


def main() -> None:
    """Publish one record using the Foundry-generated high-scale endpoint shape."""
    try:
        host = setting("FOUNDRY_HOSTNAME").removeprefix("https://").rstrip("/")
        dataset_rid = setting("FOUNDRY_STREAM_RID")
        token = setting("FOUNDRY_TOKEN")
        branch = os.environ.get("FOUNDRY_BRANCH", "master")
        event = TelemetrySampleFactory().create_event(39.554673, 15.878057, 0.0, 0.0, TripStatus.STATIONARY)
        response = requests.post(
            f"https://{host}/api/v2/highScale/streams/datasets/{dataset_rid}/streams/{branch}/publishRecords",
            params={"preview": os.environ.get("FOUNDRY_PREVIEW", "true")},
            json={"records": [event.to_record()]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        print(f"Foundry response: {response.status_code} {response.reason}")
    except (ValueError, requests.RequestException) as error:
        print(f"Foundry probe failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        print("Foundry probe stopped by Ctrl-C.", file=sys.stderr)


if __name__ == "__main__":
    main()
