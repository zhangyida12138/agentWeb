"""权限上下文（access）的实体、权限点常量与角色矩阵。

铁律：本层不 import 任何框架（FastAPI / SQLAlchemy / Pydantic）。

本模块同时承载两样东西，理由如下：
    ① 实体 Role / Permission：有标识、可持久化的业务对象；
    ② 权限点常量与角色矩阵：它不是「配置」，而是领域知识——「谁能做什么」
       本身就是业务规则。放在这里，core/seed.py 才能以纯搬运的姿态把它同步进库。

权限点常量集中在 PermissionCode，守卫（require_permission）与种子数据共用：
    任何地方手写 "post:create" 字符串，都会在某次改名时被漏掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

# 长度上限是「领域校验 / 数据库列宽」的唯一来源（与 identity/value_objects.py 同一约定）：
# 两处各写一遍，早晚会漂移成「领域放行、数据库截断」
ROLE_CODE_MAX_LEN = 50
ROLE_NAME_MAX_LEN = 100
PERMISSION_CODE_MAX_LEN = 100
PERMISSION_NAME_MAX_LEN = 100


class RoleCode:
    """内置角色编码常量。"""

    ADMIN: Final = "admin"
    AUTHOR: Final = "author"
    READER: Final = "reader"


class PermissionCode:
    """权限点常量，命名规范 ``<资源>:<动作>``。

    刻意不用 Enum：库里存的就是普通字符串，Enum 成员一旦改名，
    已入库的旧值就对不上了；而「常量集中 + 一律引用常量」已经足够安全。
    """

    # ── 用户与权限管理 ──
    USER_LIST: Final = "user:list"
    USER_ASSIGN_ROLES: Final = "user:assign_roles"
    USER_RESET_PASSWORD: Final = "user:reset_password"
    ROLE_LIST: Final = "role:list"
    # ── 文章 ──
    POST_CREATE: Final = "post:create"
    POST_UPDATE: Final = "post:update"
    POST_PUBLISH: Final = "post:publish"
    POST_DELETE: Final = "post:delete"
    # ── 互动 ──
    COMMENT_CREATE: Final = "comment:create"
    COMMENT_DELETE: Final = "comment:delete"
    LIKE_TOGGLE: Final = "like:toggle"
    # ── AI Agent ──
    AGENT_CHAT: Final = "agent:chat"


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    """权限点声明（种子数据的输入）。"""

    code: str
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """角色声明：编码、名称，以及它拥有的权限码集合。"""

    code: str
    name: str
    description: str | None = None
    permissions: frozenset[str] = frozenset()


# ──────────────────────────── 声明区：改这里就改了种子数据 ────────────────────────────

PERMISSION_SPECS: Final[tuple[PermissionSpec, ...]] = (
    PermissionSpec(PermissionCode.USER_LIST, "查看用户列表"),
    PermissionSpec(PermissionCode.USER_ASSIGN_ROLES, "分配用户角色"),
    PermissionSpec(PermissionCode.USER_RESET_PASSWORD, "重置用户密码"),
    PermissionSpec(PermissionCode.ROLE_LIST, "查看角色与权限"),
    PermissionSpec(PermissionCode.POST_CREATE, "新建文章"),
    PermissionSpec(PermissionCode.POST_UPDATE, "编辑文章"),
    PermissionSpec(PermissionCode.POST_PUBLISH, "发布 / 下架文章"),
    PermissionSpec(PermissionCode.POST_DELETE, "删除文章"),
    PermissionSpec(PermissionCode.COMMENT_CREATE, "发表评论"),
    PermissionSpec(PermissionCode.COMMENT_DELETE, "删除评论"),
    PermissionSpec(PermissionCode.LIKE_TOGGLE, "点赞 / 取消点赞"),
    PermissionSpec(PermissionCode.AGENT_CHAT, "使用 AI 助手"),
)

_ALL_PERMISSION_CODES: Final = frozenset(spec.code for spec in PERMISSION_SPECS)

_READER_PERMISSIONS: Final = frozenset(
    {
        PermissionCode.COMMENT_CREATE,
        PermissionCode.LIKE_TOGGLE,
        PermissionCode.AGENT_CHAT,
    }
)

_AUTHOR_PERMISSIONS: Final = _READER_PERMISSIONS | {
    PermissionCode.POST_CREATE,
    PermissionCode.POST_UPDATE,
    PermissionCode.POST_PUBLISH,
    PermissionCode.POST_DELETE,
}

ROLE_SPECS: Final[tuple[RoleSpec, ...]] = (
    RoleSpec(RoleCode.ADMIN, "管理员", "拥有全部权限", _ALL_PERMISSION_CODES),
    RoleSpec(RoleCode.AUTHOR, "作者", "可创作与管理自己的文章", _AUTHOR_PERMISSIONS),
    RoleSpec(RoleCode.READER, "读者", "可评论、点赞与使用 AI 助手", _READER_PERMISSIONS),
)


# ──────────────────────────── 实体 ────────────────────────────


@dataclass(slots=True)
class Permission:
    """权限点实体。"""

    code: str
    name: str
    id: UUID | None = None
    description: str | None = None


@dataclass(slots=True)
class Role:
    """角色实体（聚合根）。

    ``permission_codes`` 用 frozenset 而不是 list：
        「这个角色有哪些权限」是集合语义（去重、判包含），
        list 会让 ``in`` 变成线性查找，也让重复项成为可能。
    """

    code: str
    name: str
    id: UUID | None = None
    description: str | None = None
    permission_codes: frozenset[str] = frozenset()

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes


__all__ = [
    "PERMISSION_CODE_MAX_LEN",
    "PERMISSION_NAME_MAX_LEN",
    "PERMISSION_SPECS",
    "ROLE_CODE_MAX_LEN",
    "ROLE_NAME_MAX_LEN",
    "ROLE_SPECS",
    "Permission",
    "PermissionCode",
    "PermissionSpec",
    "Role",
    "RoleCode",
    "RoleSpec",
]
