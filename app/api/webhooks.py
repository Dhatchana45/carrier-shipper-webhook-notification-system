
from uuid import UUID
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Webhook
from app.schemas import WebhookCreate, WebhookResponse, WebhookUpdate
from app.security.webhook_url import (
    validate_webhook_url,
    WebhookURLValidationError,
)
from app.security.webhook_secrets import encrypt_webhook_secret


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_accessible_webhook(
    webhook_id: UUID,
    current_user: User,
    db: Session,
) -> Webhook:
    """
    Return a webhook only if the current user owns it
    or the current user is an admin.
    """

    webhook = db.get(Webhook, webhook_id)

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )

    if current_user.role == "admin":
        return webhook

    if current_user.role == "carrier":
        if (
            current_user.carrier_id is not None
            and webhook.carrier_id == current_user.carrier_id
        ):
            return webhook

    elif current_user.role == "shipper":
        if (
            current_user.shipper_id is not None
            and webhook.shipper_id == current_user.shipper_id
        ):
            return webhook

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Webhook not found",
    )


def validate_target_url(url: str) -> str:
    """
    Validate a webhook destination and convert validation
    failures into HTTP 422 responses.
    """

    try:
        return validate_webhook_url(url)

    except WebhookURLValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook(
    webhook_data: WebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Assign ownership from the authenticated account.
    # Never accept organisation ownership from the request body.

    carrier_id = None
    shipper_id = None

    if current_user.role == "admin":
        # Admin-created webhooks are global.
        pass

    elif current_user.role == "carrier":
        if current_user.carrier_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not linked to a carrier",
            )

        carrier_id = current_user.carrier_id

    elif current_user.role == "shipper":
        if current_user.shipper_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not linked to a shipper",
            )

        shipper_id = current_user.shipper_id

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to create webhooks",
        )

    # Validate destination before storing it.
    target_url = validate_target_url(
        str(webhook_data.target_url)
    )

    # Generate a secret if none was supplied, then encrypt it.
    raw_secret = webhook_data.secret or secrets.token_urlsafe(32)

    webhook = Webhook(
        name=webhook_data.name,
        target_url=target_url,
        secret=encrypt_webhook_secret(raw_secret),
        subscribed_event_types=webhook_data.subscribed_event_types,
        is_active=webhook_data.is_active,
        circuit_state="closed",
        consecutive_failures=0,
        carrier_id=carrier_id,
        shipper_id=shipper_id,
    )

    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    return webhook


@router.get("/", response_model=list[WebhookResponse])
def list_webhooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = select(Webhook)

    if current_user.role == "admin":
        pass

    elif current_user.role == "carrier":
        if current_user.carrier_id is None:
            return []

        statement = statement.where(
            Webhook.carrier_id == current_user.carrier_id
        )

    elif current_user.role == "shipper":
        if current_user.shipper_id is None:
            return []

        statement = statement.where(
            Webhook.shipper_id == current_user.shipper_id
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view webhooks",
        )

    statement = statement.order_by(Webhook.created_at.desc())

    return db.scalars(statement).all()


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_accessible_webhook(
        webhook_id,
        current_user,
        db,
    )


@router.patch("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: UUID,
    webhook_data: WebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    webhook = get_accessible_webhook(
        webhook_id,
        current_user,
        db,
    )

    updates = webhook_data.model_dump(exclude_unset=True)

    # Validate any new destination before updating the database.
    if "target_url" in updates and updates["target_url"] is not None:
        updates["target_url"] = validate_target_url(
            str(updates["target_url"])
        )

    # Generate and encrypt a new secret if one is supplied.
    if "secret" in updates:
        raw_secret = updates["secret"] or secrets.token_urlsafe(32)
        updates["secret"] = encrypt_webhook_secret(raw_secret)

    for field, value in updates.items():
        setattr(webhook, field, value)

    db.commit()
    db.refresh(webhook)

    return webhook


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_webhook(
    webhook_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    webhook = get_accessible_webhook(
        webhook_id,
        current_user,
        db,
    )

    # Soft delete: deactivate the webhook.
    webhook.is_active = False

    db.commit()

    return None
