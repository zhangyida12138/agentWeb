"""access 上下文的应用层 DTO。

入参 ``*Command``、出参 ``*DTO``，一律标准库 dataclass：
    参数校验归表现层 schema，序列化格式同理
    （理由见 application/identity/dto.py 顶部关于「为什么不用 pydantic」的说明）。
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from app.application.identity.dto import UserDTO
from app.domain.access.entities import Permission, Role
from app.domain.identity.entities import User

# ──────────────────────────── 入参：Command ────────────────────────────


@dataclass(frozen=True, slots=True)
class AssignRolesCommand:
    """分配角色命令。

    ``role_codes`` 是**最终状态**（替换语义），不是增量：
        管理后台的交互就是「勾选一组 → 保存」，替换语义与界面一一对应，
        而且天然幂等——重复提交同一份集合不产生任何变化。
    用 frozenset 而不是 list：集合语义自带去重，
    「同一个角色填了两遍」这种脏输入在进用例之前就被抹平了。
    """

    role_codes: frozenset[str]


# ──────────────────────────── 出参：DTO ────────────────────────────


@dataclass(frozen=True, slots=True)
class PermissionDTO:
    """权限点出参视图。"""

    id: uuid.UUID
    code: str
    name: str
    description: str | None

    @classmethod
    def from_entity(cls, permission: Permission) -> PermissionDTO:
        """领域实体 → DTO。

        取不到 id 说明实体还没落库就被拿去构造响应了；和 ``UserDTO.from_entity``
        同一套判断：这是编程错误，当场炸掉远好过返回一个空 id 让前端去猜。
        """
        if permission.id is None:
            msg = "PermissionDTO 只能由已持久化的实体构造（此时 id 必然已生成）"
            raise ValueError(msg)
        return cls(
            id=permission.id,
            code=permission.code,
            name=permission.name,
            description=permission.description,
        )


@dataclass(frozen=True, slots=True)
class RoleDTO:
    """角色出参视图：带权限码，前端据它渲染勾选态。"""

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    permission_codes: frozenset[str]

    @classmethod
    def from_entity(cls, role: Role) -> RoleDTO:
        if role.id is None:
            msg = "RoleDTO 只能由已持久化的实体构造（此时 id 必然已生成）"
            raise ValueError(msg)
        return cls(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            permission_codes=role.permission_codes,
        )


@dataclass(frozen=True, slots=True)
class UserWithRolesDTO:
    """用户列表项：用户视图 + 他拥有的角色码。

    组合，而不是给 ``UserDTO`` 加一个 ``role_codes`` 字段：
        identity 上下文不需要知道「角色」这个概念存在。往 UserDTO 里塞角色，
        两个上下文就从单向依赖变成互相咬住——而 identity 是更底层的那个。
    """

    user: UserDTO
    role_codes: frozenset[str]

    @classmethod
    def from_entity(cls, user: User, role_codes: Collection[str]) -> UserWithRolesDTO:
        return cls(user=UserDTO.from_entity(user), role_codes=frozenset(role_codes))


@dataclass(frozen=True, slots=True)
class AccessSummaryDTO:
    """「当前登录用户能做什么」的快照，供前端渲染管理入口。

    为什么回的是**权限码**而不是一个 ``is_admin: bool``：
        前端要显示/隐藏某个按钮，用的必须是后端守卫真正校验的那把尺子。
        按角色名判断（``role_codes.includes('admin')``）当下能跑，
        但角色可以新增、可以改名、可以出现「有这个权限却没这个角色名」的自定义角色，
        那一刻前后端就会错位成「按钮给了、一点就 403」。
        权限码是这个系统里唯一稳定的授权语言，两边共用它。
    """

    role_codes: frozenset[str]
    permission_codes: frozenset[str]


__all__ = [
    "AccessSummaryDTO",
    "AssignRolesCommand",
    "PermissionDTO",
    "RoleDTO",
    "UserWithRolesDTO",
]
