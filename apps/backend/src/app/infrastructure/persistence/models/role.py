"""access 上下文的角色 ORM 模型。

模型不是领域实体：业务规则住在 domain/access/entities.py，
两者由 mappers/access.py 显式翻译。
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.access.entities import ROLE_CODE_MAX_LEN, ROLE_NAME_MAX_LEN
from app.infrastructure.persistence.base import Base, IDMixin, TimestampMixin


class RoleModel(Base, IDMixin, TimestampMixin):
    """roles 表。"""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(ROLE_CODE_MAX_LEN), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(ROLE_NAME_MAX_LEN))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    def __repr__(self) -> str:
        return f"<RoleModel id={self.id!r} code={self.code!r}>"


__all__ = ["RoleModel"]
