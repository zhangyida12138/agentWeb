"""用户 ↔ 角色 关联表。

两个刻意的选择：

① **不继承** IDMixin / TimestampMixin（即不使用 MappedAsDataclass）：
   关联表没有「自身标识」也没有审计语义，只有一对复合主键。
   硬加一个自增 id 会多出无意义的主键列，也削弱了 ``(user_id, role_id)``
   唯一性的显式表达。

② **不声明 relationship()**：
   本项目仓储一律用显式 JOIN 取数据（见 repositories/access.py），不依赖 ORM
   关系加载。少一层隐式行为，就少一类「N+1 查询」和「异步下懒加载报
   MissingGreenlet」的坑。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class UserRoleModel(Base):
    """user_roles 表（复合主键）。"""

    __tablename__ = "user_roles"

    # ondelete="CASCADE"：删用户时顺带清掉角色绑定，避免悬空行
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<UserRoleModel user_id={self.user_id!r} role_id={self.role_id!r}>"


__all__ = ["UserRoleModel"]
