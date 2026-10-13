"""access 上下文的权限点 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.access.entities import PERMISSION_CODE_MAX_LEN, PERMISSION_NAME_MAX_LEN
from app.infrastructure.persistence.base import Base, IDMixin, TimestampMixin


class PermissionModel(Base, IDMixin, TimestampMixin):
    """permissions 表。"""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(PERMISSION_CODE_MAX_LEN), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(PERMISSION_NAME_MAX_LEN))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    def __repr__(self) -> str:
        return f"<PermissionModel id={self.id!r} code={self.code!r}>"


__all__ = ["PermissionModel"]
