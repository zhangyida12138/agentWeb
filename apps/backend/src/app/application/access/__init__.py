"""access 上下文的应用层：用例编排 + DTO。

依赖方向（只允许向内）：
    application → domain（实体、仓储接口、领域异常）

**不得**出现 FastAPI / SQLAlchemy 的 import：
    事务边界归 ``core/database.py`` 的 ``get_db``，HTTP 语义归表现层与全局异常处理器。
    这一点比 identity 更关键——access 的用例最容易顺手去 import SQLAlchemy
    判「这个角色在不在」，那样依赖倒置立刻作废，用例也就没法用假仓储单测了。
"""

from app.application.access.dto import (
    AccessSummaryDTO,
    AssignRolesCommand,
    PermissionDTO,
    RoleDTO,
    UserWithRolesDTO,
)
from app.application.access.use_cases import (
    AssignRolesUseCase,
    GetMyAccessUseCase,
    ListPermissionsUseCase,
    ListRolesUseCase,
    ListUserRolesUseCase,
    ListUsersUseCase,
)

__all__ = [
    "AccessSummaryDTO",
    "AssignRolesCommand",
    "AssignRolesUseCase",
    "GetMyAccessUseCase",
    "ListPermissionsUseCase",
    "ListRolesUseCase",
    "ListUserRolesUseCase",
    "ListUsersUseCase",
    "PermissionDTO",
    "RoleDTO",
    "UserWithRolesDTO",
]
