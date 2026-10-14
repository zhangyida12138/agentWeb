"""集中登记全部 ORM 模型。

Alembic 的 autogenerate 依赖 ``Base.metadata``，而 metadata 只有在模型类被
**import 过**之后才会被填充。所以每新增一个模型都必须在这里登记，
否则迁移会「莫名其妙漏表」——而且是静默漏，不会报错。
"""

from app.infrastructure.persistence.models.comment import CommentModel
from app.infrastructure.persistence.models.like import LikeModel
from app.infrastructure.persistence.models.permission import PermissionModel
from app.infrastructure.persistence.models.post import PostModel
from app.infrastructure.persistence.models.post_tag import PostTagModel
from app.infrastructure.persistence.models.role import RoleModel
from app.infrastructure.persistence.models.role_permission import RolePermissionModel
from app.infrastructure.persistence.models.tag import TagModel
from app.infrastructure.persistence.models.user import UserModel
from app.infrastructure.persistence.models.user_role import UserRoleModel

__all__ = [
    "CommentModel",
    "LikeModel",
    "PermissionModel",
    "PostModel",
    "PostTagModel",
    "RoleModel",
    "RolePermissionModel",
    "TagModel",
    "UserModel",
    "UserRoleModel",
]
