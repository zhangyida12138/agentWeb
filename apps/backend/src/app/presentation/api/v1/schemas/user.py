from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreateRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
