
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Carrier, Driver, Load, Shipper, User
from app.schemas_loads import (
    DriverCreate,
    DriverResponse,
    LoadAssignment,
    LoadCreate,
    LoadResponse,
    LoadStatusUpdate,
)
from app.services.trucking_event_service import create_trucking_event
from app.workers.dispatcher import dispatch_pending_deliveries


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Loads and Drivers"])


# ---------------------------------------------------------
# LOAD STATUS STATE MACHINE
# ---------------------------------------------------------

LOAD_STATUS_TRANSITIONS = {
    "created": {"assigned", "cancelled"},
    "assigned": {"dispatched", "cancelled"},
    "dispatched": {"at_pickup", "cancelled"},
    "at_pickup": {"picked_up", "detention", "cancelled"},
    "picked_up": {"in_transit", "detention", "cancelled"},
    "in_transit": {"detention", "at_delivery", "cancelled"},
    "detention": {
        "picked_up",
        "in_transit",
        "at_delivery",
        "cancelled",
    },
    "at_delivery": {"detention", "delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


def validate_load_transition(old_status: str, new_status: str):
    """
    Validate whether a load can move from its current status
    to the requested status.
    """

    if new_status not in LOAD_STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid load status: {new_status}",
        )

    allowed_transitions = LOAD_STATUS_TRANSITIONS.get(old_status, set())

    if new_status not in allowed_transitions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Invalid load status transition",
                "current_status": old_status,
                "requested_status": new_status,
                "allowed_transitions": sorted(allowed_transitions),
            },
        )


# ---------------------------------------------------------
# COMMON HELPERS
# ---------------------------------------------------------

def dispatch_after_commit():
    """
    Dispatch pending webhook deliveries after the database
    transaction has been committed.
    """

    try:
        dispatch_pending_deliveries.delay()
    except Exception:
        logger.exception(
            "Failed to enqueue pending webhook delivery dispatch"
        )


def get_accessible_load(
    db: Session,
    load_id: UUID,
    current_user: User,
) -> Load:
    """
    Retrieve a load only if the current user is authorised
    to access it.
    """

    load = db.get(Load, load_id)

    if load is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Load not found",
        )

    if current_user.role == "admin":
        return load

    if current_user.role == "carrier":
        if (
            current_user.carrier_id is None
            or load.carrier_id != current_user.carrier_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Load not found",
            )

        return load

    if current_user.role == "shipper":
        if (
            current_user.shipper_id is None
            or load.shipper_id != current_user.shipper_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Load not found",
            )

        return load

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this load",
    )


def validate_carrier_and_driver(
    db: Session,
    carrier_id: UUID,
    driver_id: UUID | None,
):
    """
    Validate carrier and optional driver before assignment.
    """

    carrier = db.get(Carrier, carrier_id)

    if carrier is None or not carrier.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carrier not found or inactive",
        )

    if driver_id is not None:
        driver = db.get(Driver, driver_id)

        if (
            driver is None
            or not driver.is_active
            or driver.carrier_id != carrier_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Driver is invalid, inactive, or does not belong to this carrier",
            )


# ---------------------------------------------------------
# DRIVER ENDPOINTS
# ---------------------------------------------------------

@router.post(
    "/drivers/",
    response_model=DriverResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_driver(
    driver_data: DriverCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin can create drivers for any carrier.
    Carrier users can create drivers only for their own carrier.
    """

    # Resolve the carrier organisation from the authenticated user.
    if current_user.role == "carrier":

        if current_user.carrier_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Carrier account is not linked to an organisation",
            )

        # Always use the logged-in carrier's organisation.
        # Never trust a carrier_id submitted by the frontend.
        carrier_id = current_user.carrier_id

    elif current_user.role == "admin":

        if driver_data.carrier_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Carrier ID is required for administrators",
            )

        carrier_id = driver_data.carrier_id

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators and carriers can create drivers",
        )

    # Verify that the carrier exists and is active.
    carrier = db.get(Carrier, carrier_id)

    if carrier is None or not carrier.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carrier not found or inactive",
        )

    # Create the driver under the resolved carrier organisation.
    driver = Driver(
        carrier_id=carrier_id,
        name=driver_data.name,
        phone=driver_data.phone,
        license_number=driver_data.license_number,
        is_active=True,
    )

    db.add(driver)
    db.commit()
    db.refresh(driver)

    return driver

@router.get(
    "/drivers/",
    response_model=list[DriverResponse],
)
def list_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin sees all drivers.
    Carrier sees only its own drivers.
    Shipper cannot access driver records.
    """

    statement = select(Driver)

    if current_user.role == "admin":
        pass

    elif current_user.role == "carrier":
        if current_user.carrier_id is None:
            return []

        statement = statement.where(
            Driver.carrier_id == current_user.carrier_id
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view drivers",
        )

    return db.scalars(statement.order_by(Driver.created_at.desc())).all()


# ---------------------------------------------------------
# LOAD CREATION
# ---------------------------------------------------------

@router.post(
    "/loads/",
    response_model=LoadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_load(
    load_data: LoadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Shipper creates loads for its own organisation.
    Admin can create loads for any shipper.
    New loads always begin in the created state.
    """

    if current_user.role == "shipper":

        if current_user.shipper_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Shipper account is not linked to an organisation",
            )

        if load_data.shipper_id != current_user.shipper_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create loads for your own shipper organisation",
            )

        if load_data.carrier_id is not None or load_data.driver_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Shippers cannot assign carriers or drivers during load creation",
            )

        carrier_id = None
        driver_id = None

    elif current_user.role == "admin":

        shipper = db.get(Shipper, load_data.shipper_id)

        if shipper is None or not shipper.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipper not found or inactive",
            )

        carrier_id = load_data.carrier_id
        driver_id = load_data.driver_id

        if carrier_id is not None:
            validate_carrier_and_driver(
                db,
                carrier_id,
                driver_id,
            )

        elif driver_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A driver cannot be assigned without a carrier",
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators and shippers can create loads",
        )

    load = Load(
        load_number=load_data.load_number,
        shipper_id=load_data.shipper_id,
        carrier_id=carrier_id,
        driver_id=driver_id,
        origin=load_data.origin,
        destination=load_data.destination,
        status="created",
    )

    db.add(load)
    db.flush()

    event = create_trucking_event(
        db=db,
        load=load,
        event_type="load.created",
        idempotency_key=f"load-created-{load.id}",
    )

    db.commit()
    db.refresh(load)

    dispatch_after_commit()

    return load


# ---------------------------------------------------------
# LIST LOADS
# ---------------------------------------------------------

@router.get(
    "/loads/",
    response_model=list[LoadResponse],
)
def list_loads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin sees all loads.
    Carrier sees loads assigned to its organisation.
    Shipper sees loads created for its organisation.
    """

    statement = select(Load)

    if current_user.role == "admin":
        pass

    elif current_user.role == "carrier":

        if current_user.carrier_id is None:
            return []

        statement = statement.where(
            Load.carrier_id == current_user.carrier_id
        )

    elif current_user.role == "shipper":

        if current_user.shipper_id is None:
            return []

        statement = statement.where(
            Load.shipper_id == current_user.shipper_id
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view loads",
        )

    return db.scalars(
        statement.order_by(Load.created_at.desc())
    ).all()


# ---------------------------------------------------------
# GET SINGLE LOAD
# ---------------------------------------------------------

@router.get(
    "/loads/{load_id}",
    response_model=LoadResponse,
)
def get_load(
    load_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_accessible_load(
        db=db,
        load_id=load_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# ASSIGN OR REASSIGN LOAD
# ---------------------------------------------------------

@router.patch(
    "/loads/{load_id}/assign",
    response_model=LoadResponse,
)
def assign_load(
    load_id: UUID,
    assignment: LoadAssignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Only admin can assign or reassign a carrier and driver.

    Assignment is permitted while a load is in created or
    assigned status. Reassignment does not change the status.
    """

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can assign loads",
        )

    # Lock the row to prevent concurrent assignments.
    load = db.scalar(
        select(Load)
        .where(Load.id == load_id)
        .with_for_update()
    )

    if load is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Load not found",
        )

    if load.status not in ("created", "assigned"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assign or reassign a load in '{load.status}' status",
        )

    validate_carrier_and_driver(
        db=db,
        carrier_id=assignment.carrier_id,
        driver_id=assignment.driver_id,
    )

    # No changes required if the assignment is identical.
    if (
        load.carrier_id == assignment.carrier_id
        and load.driver_id == assignment.driver_id
    ):
        return load

    old_status = load.status

    # Only a created load makes a status transition.
    # Reassignment of an already assigned load keeps its status.
    if old_status == "created":
        validate_load_transition(
            old_status,
            "assigned",
        )

    load.carrier_id = assignment.carrier_id
    load.driver_id = assignment.driver_id
    load.status = "assigned"

    event = create_trucking_event(
        db=db,
        load=load,
        event_type="load.assigned",
        idempotency_key=f"load-assigned-{load.id}-{uuid4()}",
        old_status=old_status,
    )

    db.commit()
    db.refresh(load)

    dispatch_after_commit()

    return load


# ---------------------------------------------------------
# UPDATE LOAD STATUS
# ---------------------------------------------------------

@router.patch(
    "/loads/{load_id}/status",
    response_model=LoadResponse,
)
def update_load_status(
    load_id: UUID,
    payload: LoadStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin can update any load.
    Carrier can update only its own assigned loads.
    Shippers cannot update load status.
    """

    if current_user.role not in ("admin", "carrier"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update load status",
        )

    # Lock the load row before validating and changing status.
    load = db.scalar(
        select(Load)
        .where(Load.id == load_id)
        .with_for_update()
    )

    if load is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Load not found",
        )

    # Check organisation ownership after acquiring the lock.
    if current_user.role == "carrier":
        if (
            current_user.carrier_id is None
            or load.carrier_id != current_user.carrier_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Load not found",
            )

    old_status = load.status
    new_status = payload.status

    # Repeated requests for the current status are harmless.
    if old_status == new_status:
        return load

    # Validate the state machine.
    validate_load_transition(
        old_status,
        new_status,
    )

    load.status = new_status

    now = datetime.now(timezone.utc)

    # Set timestamps for relevant shipment milestones.
    if new_status == "picked_up":
        load.pickup_at = now

    elif new_status == "delivered":
        load.delivered_at = now

    # Map statuses to webhook event types.
    event_mapping = {
        "assigned": "load.assigned",
        "dispatched": "load.dispatched",
        "at_pickup": "load.at_pickup",
        "picked_up": "load.picked_up",
        "in_transit": "load.in_transit",
        "detention": "load.detention_started",
        "at_delivery": "load.at_delivery",
        "delivered": "load.delivered",
        "cancelled": "load.cancelled",
    }

    event_type = event_mapping.get(
        new_status,
        "load.status_updated",
    )

    event = create_trucking_event(
        db=db,
        load=load,
        event_type=event_type,
        idempotency_key=f"load-status-{load.id}-{uuid4()}",
        old_status=old_status,
    )

    db.commit()
    db.refresh(load)

    dispatch_after_commit()

    return load
