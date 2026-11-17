from sqlalchemy.orm import Session

from app.models import Event, Load
from app.services.delivery_service import create_deliveries_for_event


def create_trucking_event(
    db: Session,
    load: Load,
    event_type: str,
    idempotency_key: str,
    old_status: str | None = None,
) -> Event:
    payload = {
        "load_id": str(load.id),
        "load_number": load.load_number,
        "status": load.status,
        "shipper_id": str(load.shipper_id),
        "carrier_id": str(load.carrier_id) if load.carrier_id else None,
        "driver_id": str(load.driver_id) if load.driver_id else None,
        "origin": load.origin,
        "destination": load.destination,
        "pickup_at": load.pickup_at.isoformat() if load.pickup_at else None,
        "delivered_at": (
            load.delivered_at.isoformat() if load.delivered_at else None
        ),
    }

    if old_status is not None:
        payload["previous_status"] = old_status

    event = Event(
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
        outbox_status="pending",
        carrier_id=load.carrier_id,
        shipper_id=load.shipper_id,
    )

    db.add(event)
    db.flush()

    create_deliveries_for_event(db, event)

    return event