"""FastAPI application for controlling the local ProjectCar simulator."""

from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException, status

from car_project.api.models import HealthResponse, StartTripRequest, TripResponse, UpdateSpeedRequest
from car_project.api.trips import ActiveTripError, TripManager, TripNotFoundError


def create_app(manager: TripManager | None = None) -> FastAPI:
    """Create the application with an injectable manager for isolated tests."""
    trip_manager = manager or TripManager()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        """Ensure background simulators receive a clean stop request on shutdown."""
        yield
        trip_manager.shutdown()

    app = FastAPI(
        title="ProjectCar Control API",
        version="0.1.0",
        description="Starts and controls the local telemetry simulator; RabbitMQ carries the events.",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Report that the API process is serving requests."""
        return HealthResponse(status="ok", active_trip_id=trip_manager.active_trip_id())

    @app.post("/trips", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
    def start_trip(request: StartTripRequest) -> TripResponse:
        """Start one RabbitMQ-backed simulated trip."""
        try:
            return trip_manager.start_trip(request)
        except ActiveTripError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @app.get("/trips/{trip_id}", response_model=TripResponse)
    def get_trip(trip_id: UUID) -> TripResponse:
        """Return the latest state known by the in-memory controller."""
        try:
            return trip_manager.get_trip(trip_id)
        except TripNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @app.patch("/trips/{trip_id}/speed", response_model=TripResponse)
    def update_speed(trip_id: UUID, request: UpdateSpeedRequest) -> TripResponse:
        """Set a new simulator speed for the active trip."""
        try:
            return trip_manager.set_speed(trip_id, request.speed_kmh)
        except TripNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post("/trips/{trip_id}/stop", response_model=TripResponse, status_code=status.HTTP_202_ACCEPTED)
    def stop_trip(trip_id: UUID) -> TripResponse:
        """Request clean termination of an active local trip."""
        try:
            return trip_manager.stop_trip(trip_id)
        except TripNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return app


app = create_app()
