
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, User
from app.schemas import EventCreate, EventResponse
from app.services.delivery_service import create_deliveries_for_event
from app.workers.dispatcher import dispatch_pending_deliveries


router = APIRouter(prefix="/events", tags=["Events"])


def get_accessible_event(
    event_id: UUID,
    current_user: User,
    db: Session,
) -> Event:
    event = db.get(Event, event_id)

    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    if current_user.role == "admin":
        return event

    if current_user.role == "carrier":
        if (
            current_user.carrier_id is not None
            and event.carrier_id == current_user.carrier_id
        ):
            return event

    elif current_user.role == "shipper":
        if (
            current_user.shipper_id is not None
            and event.shipper_id == current_user.shipper_id
        ):
            return event

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Event not found",
    )


@router.post(
    "/",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    event_data: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Generic event creation is restricted to administrators.
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create generic events",
        )

    # Admin-created generic events have no organisation ownership.
    # Only global admin webhooks will receive these events.

    if event_data.idempotency_key:
        existing_event = db.scalar(
            select(Event).where(
                Event.idempotency_key == event_data.idempotency_key
            )
        )

        if existing_event:
            create_deliveries_for_event(db, existing_event)
            db.commit()
            db.refresh(existing_event)
            return existing_event

    event = Event(
        event_type=event_data.event_type,
        idempotency_key=event_data.idempotency_key,
        payload=event_data.payload,
        outbox_status="pending",
        carrier_id=None,
        shipper_id=None,
    )

    try:
        db.add(event)
        db.flush()

        create_deliveries_for_event(db, event)

        db.commit()
        db.refresh(event)

        dispatch_pending_deliveries.delay()

    except IntegrityError:
        db.rollback()

        if event_data.idempotency_key:
            existing_event = db.scalar(
                select(Event).where(
                    Event.idempotency_key == event_data.idempotency_key
                )
            )

            if existing_event:
                create_deliveries_for_event(db, existing_event)
                db.commit()
                db.refresh(existing_event)
                return existing_event

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Database conflict while creating event.",
        )

    return event


@router.get("/", response_model=list[EventResponse])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(Event)

    if current_user.role == "admin":
        pass

    elif current_user.role == "carrier":
        if current_user.carrier_id is None:
            return []

        statement = statement.where(
            Event.carrier_id == current_user.carrier_id
        )

    elif current_user.role == "shipper":
        if current_user.shipper_id is None:
            return []

        statement = statement.where(
            Event.shipper_id == current_user.shipper_id
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view events",
        )

    statement = statement.order_by(Event.created_at.desc())

    return db.scalars(statement).all()


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_accessible_event(event_id, current_user, db)
