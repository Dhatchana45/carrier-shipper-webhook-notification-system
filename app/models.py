
import uuid
from datetime import datetime, timezone
from sqlalchemy import Enum
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    shipper_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("shippers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    subscribed_event_types: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    circuit_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="closed",
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    circuit_opened_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="webhook",
    )

    __table_args__ = (
        CheckConstraint(
        "carrier_id IS NULL OR shipper_id IS NULL",
        name="ck_webhooks_single_organisation_owner",
    ),
        CheckConstraint(
            "circuit_state IN ('closed', 'open', 'half_open')",
            name="ck_webhooks_circuit_state",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_webhooks_failure_count",
        ),
        Index("ix_webhooks_is_active", "is_active"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Supplied by the producer to prevent duplicate event creation.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )

    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    shipper_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("shippers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Outbox processing status.
    outbox_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="event",
    )

    __table_args__ = (
        CheckConstraint(
            "outbox_status IN ('pending', 'processing', 'published')",
            name="ck_events_outbox_status",
        ),
        Index("ix_events_outbox_created", "outbox_status", "created_at"),
        Index("ix_events_event_type", "event_type"),
    )


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("webhooks.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=8,
    )

    processing_started_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
    )

    claim_token: Mapped[uuid.UUID | None] = mapped_column(
    Uuid,
    nullable=True,
    )

    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    event: Mapped["Event"] = relationship(back_populates="deliveries")
    webhook: Mapped["Webhook"] = relationship(back_populates="deliveries")

    attempts: Mapped[list["DeliveryAttempt"]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="DeliveryAttempt.attempt_number",
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "webhook_id",
            name="uq_delivery_event_webhook",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'retrying', "
            "'succeeded', 'failed', 'paused')",
            name="ck_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1",
            name="ck_deliveries_attempt_counts",
        ),
        Index("ix_deliveries_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_deliveries_webhook_status", "webhook_id", "status"),
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
    )

    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    http_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    delivery: Mapped["Delivery"] = relationship(back_populates="attempts")

    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "attempt_number",
            name="uq_delivery_attempt_number",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_delivery_attempt_number",
        ),
        Index("ix_delivery_attempts_started_at", "started_at"),
    )


# ---------------------------------------------------------
# Trucking domain models
# ---------------------------------------------------------

class Carrier(Base):
    __tablename__ = "carriers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    contact_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Shipper(Base):
    __tablename__ = "shippers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    contact_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    license_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Load(Base):
    __tablename__ = "loads"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    load_number: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )

    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    shipper_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("shippers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("drivers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    origin: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="created"
    )

    pickup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'assigned', 'dispatched', "
            "'at_pickup', 'picked_up', 'in_transit', "
            "'detention', 'at_delivery', 'delivered', 'cancelled')",
            name="ck_loads_status",
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    shipper_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("shippers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="shipper",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'carrier', 'shipper')",
            name="ck_users_role",
        ),
    )
