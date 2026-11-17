from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CarrierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=50)
    contact_email: str | None = None
    phone: str | None = None


class CarrierResponse(BaseModel):
    id: UUID
    name: str
    code: str
    contact_email: str | None
    phone: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShipperCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=50)
    contact_email: str | None = None
    phone: str | None = None


class ShipperResponse(BaseModel):
    id: UUID
    name: str
    code: str
    contact_email: str | None
    phone: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
