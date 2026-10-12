"""Typed request and response models for the ProjectCar control API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StartTripRequest(BaseModel):
    """Parameters for one locally simulated route trip."""

    speed_kmh: float = Field(default=140.0, ge=0.0, le=250.0)
    urban_speed_kmh: float = Field(default=60.0, ge=50.0, le=70.0)
    speed_variation_kmh: float = Field(default=5.0, ge=0.0, le=100.0)
    random_seed: int | None = None
    traffic_stop_count: int = Field(default=30, ge=0, le=100, multiple_of=2)
    vehicle_id: str = Field(default="car-001", min_length=1, max_length=100)


class UpdateSpeedRequest(BaseModel):
    """A safe speed update for an active simulated trip."""

    speed_kmh: float = Field(ge=0.0, le=250.0)


class TripResponse(BaseModel):
    """Current in-memory state of a locally controlled trip."""

    trip_id: UUID
    vehicle_id: str
    speed_kmh: float
    target_speed_kmh: float
    highway_speed_kmh: float
    urban_speed_kmh: float
    speed_variation_kmh: float
    traffic_stop_count: int
    distance_travelled_km: float
    status: Literal["running", "stopping", "stopped", "arrived", "failed"]
    started_at: datetime
    latest_event_time: datetime | None
    error: str | None


class HealthResponse(BaseModel):
    """Small readiness response for local service checks."""

    status: Literal["ok"]
    active_trip_id: UUID | None
