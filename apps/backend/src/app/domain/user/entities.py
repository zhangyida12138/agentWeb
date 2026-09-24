from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.user.exceptions import InvalidUserNameError
from app.domain.user.value_objects import Email

_MAX_NAME_LENGTH = 100


@dataclass(slots=True)
class User:
    """用户聚合根。所有状态变更必须通过下方的方法进行，以保证业务不变量。"""

    email: Email
    display_name: str
    id: UUID = field(default_factory=uuid4)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def register(cls, *, email: str | Email, display_name: str) -> "User":
        """注册一个新用户（处于激活状态）。"""
        return cls(
            email=email if isinstance(email, Email) else Email(email),
            display_name=_validate_name(display_name),
        )

    def rename(self, display_name: str) -> None:
        self.display_name = _validate_name(display_name)

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False


def _validate_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise InvalidUserNameError("显示名称不能为空")
    if len(name) > _MAX_NAME_LENGTH:
        raise InvalidUserNameError(f"显示名称不能超过 {_MAX_NAME_LENGTH} 个字符")
    return name
