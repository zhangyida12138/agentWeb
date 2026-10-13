"""角色 ↔ 权限 关联表（理由同 user_role.py）。"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class RolePermissionModel(Base):
    """role_permissions 表（复合主键）。"""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return (
            f"<RolePermissionModel role_id={self.role_id!r} permission_id={self.permission_id!r}>"
        )


__all__ = ["RolePermissionModel"]
