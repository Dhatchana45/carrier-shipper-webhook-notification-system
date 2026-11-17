
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["carrier", "shipper"]

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    model_config = ConfigDict(
        extra="forbid",
    )


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
