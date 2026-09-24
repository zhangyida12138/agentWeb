from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.user.entities import User


@dataclass(frozen=True, slots=True)
class UserDTO:
    """跨越应用层边界的数据载体，表现层不再接触领域实体。"""

    id: UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, user: User) -> "UserDTO":
        return cls(
            id=user.id,
            email=str(user.email),
            display_name=user.display_name,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


@dataclass(frozen=True, slots=True)
class CreateUserCommand:
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class UpdateUserCommand:
    display_name: str | None = None
    is_active: bool | None = None


@dataclass(frozen=True, slots=True)
class ListUsersQuery:
    offset: int = 0
    limit: int = 20
