
from sqlalchemy import or_, select, cast
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB

from app.models import Delivery, Event, Webhook


def create_deliveries_for_event(db: Session, event: Event) -> int:
    """
    Create one pending delivery for each active webhook subscribed
    to this event and matching its carrier/shipper ownership.

    PostgreSQL uses JSONB containment for efficient subscription
    filtering. SQLite uses Python-side filtering for test compatibility.
    """

    dialect_name = db.get_bind().dialect.name

    statement = select(Webhook).where(
        Webhook.is_active.is_(True)
    )

    # PostgreSQL-specific JSONB containment.
    if dialect_name == "postgresql":
        statement = statement.where(
            cast(Webhook.subscribed_event_types, JSONB).contains(
                [event.event_type]
            )
        )

    # Match global webhooks or webhooks belonging to this event's
    # carrier or shipper.
    if event.carrier_id is not None and event.shipper_id is not None:
        statement = statement.where(
            or_(
                (
                    Webhook.carrier_id.is_(None)
                    & Webhook.shipper_id.is_(None)
                ),
                Webhook.carrier_id == event.carrier_id,
                Webhook.shipper_id == event.shipper_id,
            )
        )

    elif event.carrier_id is not None:
        statement = statement.where(
            or_(
                (
                    Webhook.carrier_id.is_(None)
                    & Webhook.shipper_id.is_(None)
                ),
                Webhook.carrier_id == event.carrier_id,
            )
        )

    elif event.shipper_id is not None:
        statement = statement.where(
            or_(
                (
                    Webhook.carrier_id.is_(None)
                    & Webhook.shipper_id.is_(None)
                ),
                Webhook.shipper_id == event.shipper_id,
            )
        )

    else:
        statement = statement.where(
            Webhook.carrier_id.is_(None),
            Webhook.shipper_id.is_(None),
        )

    webhooks = db.scalars(statement).all()

    # SQLite fallback: JSONB containment is not supported by SQLite.
    if dialect_name == "sqlite":
        webhooks = [
            webhook
            for webhook in webhooks
            if event.event_type in (webhook.subscribed_event_types or [])
        ]

    created_count = 0

    for webhook in webhooks:
        existing_delivery = db.scalar(
            select(Delivery).where(
                Delivery.event_id == event.id,
                Delivery.webhook_id == webhook.id,
            )
        )

        if existing_delivery:
            continue

        delivery = Delivery(
            event_id=event.id,
            webhook_id=webhook.id,
            status="pending",
            attempt_count=0,
        )

        db.add(delivery)
        created_count += 1

    return created_count
