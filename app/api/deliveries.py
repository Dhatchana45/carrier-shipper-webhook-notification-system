
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Delivery, User, Webhook
from app.schemas import DeliveryResponse, DeliveryAttemptResponse


router = APIRouter(prefix="/deliveries", tags=["Deliveries"])


def apply_delivery_ownership_filter(statement, current_user: User):
    """
    Restrict delivery records to the current user's organisation.
    Admins can access all deliveries.
    """

    if current_user.role == "admin":
        return statement

    if current_user.role == "carrier":
        if current_user.carrier_id is None:
            return statement.where(False)

        return statement.join(
            Webhook,
            Delivery.webhook_id == Webhook.id,
        ).where(
            Webhook.carrier_id == current_user.carrier_id
        )

    if current_user.role == "shipper":
        if current_user.shipper_id is None:
            return statement.where(False)

        return statement.join(
            Webhook,
            Delivery.webhook_id == Webhook.id,
        ).where(
            Webhook.shipper_id == current_user.shipper_id
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view deliveries",
    )


def get_accessible_delivery(
    delivery_id: UUID,
    db: Session,
    current_user: User,
    include_attempts: bool = False,
) -> Delivery:

    statement = select(Delivery).where(
        Delivery.id == delivery_id
    )

    if include_attempts:
        statement = statement.options(
            selectinload(Delivery.attempts)
        )

    statement = apply_delivery_ownership_filter(
        statement,
        current_user,
    )

    delivery = db.scalar(statement)

    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        )

    return delivery


@router.get("/", response_model=list[DeliveryResponse])
def list_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(Delivery)

    statement = apply_delivery_ownership_filter(
        statement,
        current_user,
    )

    statement = statement.order_by(
        Delivery.created_at.desc()
    )

    return db.scalars(statement).all()


@router.get(
    "/attempts/all",
    response_model=list[DeliveryAttemptResponse],
)
def list_all_delivery_attempts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = (
        select(Delivery)
        .options(selectinload(Delivery.attempts))
    )

    statement = apply_delivery_ownership_filter(
        statement,
        current_user,
    )

    statement = statement.order_by(
        Delivery.created_at.desc()
    )

    deliveries = db.scalars(statement).unique().all()

    return [
        attempt
        for delivery in deliveries
        for attempt in delivery.attempts
    ]


@router.get(
    "/{delivery_id}",
    response_model=DeliveryResponse,
)
def get_delivery(
    delivery_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_accessible_delivery(
        delivery_id,
        db,
        current_user,
    )


@router.get(
    "/{delivery_id}/attempts",
    response_model=list[DeliveryAttemptResponse],
)
def list_delivery_attempts(
    delivery_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    delivery = get_accessible_delivery(
        delivery_id,
        db,
        current_user,
        include_attempts=True,
    )

    return delivery.attempts
