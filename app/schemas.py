from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from typing import Any

class WebhookCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    target_url: HttpUrl
    secret: str | None = Field(default=None, max_length=255)
    subscribed_event_types: list[str] = Field(min_length=1)
    is_active: bool = True


class WebhookResponse(BaseModel):
    id: UUID
    name: str
    target_url: str
    subscribed_event_types: list[str]
    is_active: bool
    circuit_state: str
    consecutive_failures: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    target_url: HttpUrl | None = None
    secret: str | None = Field(default=None, max_length=255)
    subscribed_event_types: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None



class EventCreate(BaseModel):
    event_type: str = Field(min_length=3, max_length=150)
    idempotency_key: str | None = Field(default=None, min_length=5, max_length=255)
    payload: dict[str, Any]



class EventResponse(BaseModel):
    id: UUID
    event_type: str
    idempotency_key: str | None
    payload: dict[str, Any]
    outbox_status: str
    published_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryResponse(BaseModel):
    id: UUID
    event_id: UUID
    webhook_id: UUID
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class DeliveryAttemptResponse(BaseModel):
    id: UUID
    delivery_id: UUID
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None
    http_status_code: int | None
    response_body: str | None
    error_message: str | None
    duration_ms: int | None

    model_config = ConfigDict(from_attributes=True)
