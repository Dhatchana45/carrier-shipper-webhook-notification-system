
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Carrier, Shipper, User
from app.auth import get_current_user, require_roles
from app.schemas_trucking import (
    CarrierCreate,
    CarrierResponse,
    ShipperCreate,
    ShipperResponse,
)

router = APIRouter(tags=["Trucking Management"])


# ---------------------------------------------------------
# CARRIERS
# ---------------------------------------------------------

@router.post(
    "/carriers/",
    response_model=CarrierResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_carrier(
    payload: CarrierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    existing = db.scalar(
        select(Carrier).where(Carrier.code == payload.code)
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Carrier code already exists",
        )

    carrier = Carrier(**payload.model_dump())

    db.add(carrier)
    db.commit()
    db.refresh(carrier)

    return carrier


@router.get("/carriers/", response_model=list[CarrierResponse])
def list_carriers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "admin":
        return db.scalars(select(Carrier)).all()

    if current_user.role == "carrier":
        if not current_user.carrier_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not linked to a carrier",
            )

        carrier = db.get(Carrier, current_user.carrier_id)

        return [carrier] if carrier else []

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view carriers",
    )


@router.get("/carriers/{carrier_id}", response_model=CarrierResponse)
def get_carrier(
    carrier_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "carrier":
        if current_user.carrier_id != carrier_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only access your own carrier profile",
            )

    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this carrier",
        )

    carrier = db.get(Carrier, carrier_id)

    if not carrier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carrier not found",
        )

    return carrier


# ---------------------------------------------------------
# SHIPPERS
# ---------------------------------------------------------

@router.post(
    "/shippers/",
    response_model=ShipperResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shipper(
    payload: ShipperCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    existing = db.scalar(
        select(Shipper).where(Shipper.code == payload.code)
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shipper code already exists",
        )

    shipper = Shipper(**payload.model_dump())

    db.add(shipper)
    db.commit()
    db.refresh(shipper)

    return shipper


@router.get("/shippers/", response_model=list[ShipperResponse])
def list_shippers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "admin":
        return db.scalars(select(Shipper)).all()

    if current_user.role == "shipper":
        if not current_user.shipper_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not linked to a shipper",
            )

        shipper = db.get(Shipper, current_user.shipper_id)

        return [shipper] if shipper else []

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view shippers",
    )


@router.get("/shippers/{shipper_id}", response_model=ShipperResponse)
def get_shipper(
    shipper_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "shipper":
        if current_user.shipper_id != shipper_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only access your own shipper profile",
            )

    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this shipper",
        )

    shipper = db.get(Shipper, shipper_id)

    if not shipper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipper not found",
        )

    return shipper
