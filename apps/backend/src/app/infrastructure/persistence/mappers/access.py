"""access 上下文的实体 ↔ 模型翻译。

映射器保持**纯函数**：不做任何 IO，权限码由调用方批量取好后传进来。
这样它可以被单测，也不会把「查库」这件事藏进翻译过程里。
"""

from __future__ import annotations

from collections.abc import Collection

from app.domain.access.entities import Permission, Role
from app.infrastructure.persistence.models.permission import PermissionModel
from app.infrastructure.persistence.models.role import RoleModel


def role_to_entity(model: RoleModel, permission_codes: Collection[str] = ()) -> Role:
    """模型 → 角色实体。"""
    return Role(
        id=model.id,
        code=model.code,
        name=model.name,
        description=model.description,
        permission_codes=frozenset(permission_codes),
    )


def permission_to_entity(model: PermissionModel) -> Permission:
    """模型 → 权限点实体。"""
    return Permission(
        id=model.id,
        code=model.code,
        name=model.name,
        description=model.description,
    )


__all__ = ["permission_to_entity", "role_to_entity"]
