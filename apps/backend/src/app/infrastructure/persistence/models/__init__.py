"""ORM 模型集合。

在此集中导入所有模型，确保 Alembic autogenerate 能发现全部表。
"""

from app.infrastructure.persistence.models.user import UserModel

__all__ = ["UserModel"]
