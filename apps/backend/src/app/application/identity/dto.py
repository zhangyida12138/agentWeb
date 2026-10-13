"""identity 上下文的应用层 DTO。

按用途分三类（与 backend.md 4.2 的分类一致）：

============================  ==========  ======================
类型                          方向        示例
============================  ==========  ======================
``*Command``                  入（写）    ``RegisterCommand``
``*Query``                    入（读）    （P3 用户列表时再加）
``*DTO``                      出          ``UserDTO`` / ``TokenDTO``
============================  ==========  ======================

为什么这里用标准库 dataclass 而不是 pydantic：
    入参校验的职责在表现层 schema（HTTP 边界）。应用层承载的是「已经合法的数据」，
    用 pydantic 会让用例的单测必须先搭一套 Web 校验上下文，
    也让应用层无谓地依赖 Web 框架那套语义。
    出参同理——序列化格式（字段名、时间格式）由表现层 schema 决定。
"""

from __future__ import annotations

import uuid

# `dataclass` 是 Python3.7+ 内置的**数据类装饰器**：用来快速定义**只存数据**的类，
# 省去手写 `__init__`、`__repr__`、`__eq__` 这些样板代码。
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.domain.identity.entities import User

# ──────────────────────────── PATCH 语义的哨兵 ────────────────────────────


class Unset:
    """「客户端没传这个字段」的标记。

    必须把「没传」和「传了 null」区分开，否则 PATCH 会退化成
    「没传的字段一律清空」——改个昵称顺手把头像和签名抹掉，这显然不对。
    用 UNSET 哨兵而不是 ``None`` 来表达「没传」：

    - ``UNSET`` → 本次不改
    - ``None``  → 本次清空
    - 其他值    → 本次改成该值
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()


# ──────────────────────────── 入参：Command ────────────────────────────


@dataclass(frozen=True, slots=True)
class RegisterCommand:
    """注册命令。密码是**明文**——它只允许在用例里停留到哈希完成那一刻。"""

    email: str
    username: str
    password: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """登录命令。

    ``password`` 刻意不做任何长度/复杂度校验：登录只需要「对/不对」这一个结论，
    在登录口做规则校验等于把注册页的密码策略回显给攻击者。
    """

    email: str
    password: str


@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    """修改资料命令（PATCH 语义，字段含义见 ``Unset``）。"""

    display_name: str | Unset | None = UNSET
    avatar_url: str | Unset | None = UNSET
    bio: str | Unset | None = UNSET


@dataclass(frozen=True, slots=True)
class ChangePasswordCommand:
    """修改密码命令：旧密码用于二次确认身份。"""

    old_password: str
    new_password: str


# ──────────────────────────── 出参：DTO ────────────────────────────


@dataclass(frozen=True, slots=True)
class UserDTO:
    """对外的用户视图。

    ⚠️ **刻意不含 ``password_hash``**：出参模型里没有这个字段，
    就不存在「某个分支忘了剔除」导致哈希泄露的可能（PLAN.md 第八章 DoD）。
    """

    id: uuid.UUID
    email: str
    username: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, user: User) -> UserDTO:
        """领域实体 → 出参 DTO。

        取不到 id 说明实体还没落库就被拿去构造响应了——这是编程错误，
        必须当场炸掉，而不是在响应里塞一个 ``None`` 让前端拿到空 id。
        """
        if user.id is None:
            msg = "UserDTO 只能由已持久化的实体构造（此时 id 必然已生成）"
            raise ValueError(msg)
        return cls(
            id=user.id,
            email=user.email.value,
            username=user.username.value,
            display_name=user.display_name or user.username.value,
            avatar_url=user.avatar_url,
            bio=user.bio,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


@dataclass(frozen=True, slots=True)
class TokenDTO:
    """签发好的访问令牌。"""

    access_token: str
    token_type: str
    # 剩余有效秒数。前端拿它定刷新/重登时机，不必去解析 JWT 的 exp
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthResultDTO:
    """登录出参：令牌 + 用户信息。

    带着 user 一起返回是有意为之：前端登录后立刻要渲染头像/昵称，
    少了它就只能再打一次 ``/me``，多一次往返也多个中间态。
    """

    token: TokenDTO
    user: UserDTO


__all__ = [
    "UNSET",
    "AuthResultDTO",
    "ChangePasswordCommand",
    "LoginCommand",
    "RegisterCommand",
    "TokenDTO",
    "Unset",
    "UpdateProfileCommand",
    "UserDTO",
]
