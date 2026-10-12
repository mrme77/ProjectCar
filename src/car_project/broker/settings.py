"""Typed configuration for the local RabbitMQ boundary."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RabbitMQSettings(BaseSettings):
    """RabbitMQ settings loaded from environment variables or a local `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rabbitmq_url: str = "amqp://projectcar:projectcar-development-only@localhost:5672/%2F"
    rabbitmq_exchange: str = "projectcar.telemetry"
    rabbitmq_queue: str = "projectcar.telemetry"
    rabbitmq_routing_key: str = "telemetry"
    rabbitmq_max_queue_messages: int = Field(default=10_000, ge=1)
    rabbitmq_prefetch_count: int = Field(default=10, ge=1)
    rabbitmq_failed_queue: str = "projectcar.telemetry.failed"
    rabbitmq_replay_invalid_queue: str = "projectcar.telemetry.failed.invalid"
    worker_max_delivery_attempts: int = Field(default=3, ge=1)
    worker_retry_base_seconds: float = Field(default=1.0, gt=0.0)
    worker_idle_heartbeat_seconds: float = Field(default=30.0, gt=0.0)
