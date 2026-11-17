
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# DRIVER SCHEMAS
# ---------------------------------------------------------

class DriverCreate(BaseModel):
    carrier_id: UUID | None = None
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    license_number: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class DriverResponse(BaseModel):
    id: UUID
    carrier_id: UUID
    name: str
    phone: str | None
    license_number: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# LOAD CREATION SCHEMA
# ---------------------------------------------------------

class LoadCreate(BaseModel):
    load_number: str = Field(min_length=2, max_length=100)
    shipper_id: UUID
    carrier_id: UUID | None = None
    driver_id: UUID | None = None
    origin: str = Field(min_length=2, max_length=255)
    destination: str = Field(min_length=2, max_length=255)

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------
# LOAD ASSIGNMENT SCHEMA
# ---------------------------------------------------------

class LoadAssignment(BaseModel):
    carrier_id: UUID
    driver_id: UUID

    model_config = ConfigDict(
        extra="forbid",
    )


# ---------------------------------------------------------
# LOAD STATUS UPDATE SCHEMA
# ---------------------------------------------------------

LoadStatus = Literal[
    "created",
    "assigned",
    "dispatched",
    "at_pickup",
    "picked_up",
    "in_transit",
    "detention",
    "at_delivery",
    "delivered",
    "cancelled",
]


class LoadStatusUpdate(BaseModel):
    status: LoadStatus

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------
# LOAD RESPONSE SCHEMA
# ---------------------------------------------------------

class LoadResponse(BaseModel):
    id: UUID
    load_number: str
    carrier_id: UUID | None
    shipper_id: UUID
    driver_id: UUID | None
    origin: str
    destination: str
    status: LoadStatus
    pickup_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
