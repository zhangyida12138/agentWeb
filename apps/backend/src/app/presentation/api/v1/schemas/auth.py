"""认证相关的请求 / 响应 Schema（HTTP 边界）。

这是**唯一**该做参数格式校验的地方：请求一到这层立刻被规矩住，
验证通过后进入应用层的就是已经干净的数据（见 application/identity/dto.py 的说明）。

响应模型与领域实体刻意不复用同一套类：
    出参只暴露该暴露的字段——``UserResponse`` 里根本没有 ``password_hash``，
    所以「不小心把密码哈希返回给前端」这种事故在类型层面就发生不了
    （PLAN.md 第八章 DoD：出参 Schema 不泄露敏感字段）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# 用户名规则与 domain/identity/value_objects.py 保持一致。
# 两处都写一遍是有意的：schema 负责「尽早给出 422 友好提示」，
# 值对象负责「无论从哪个入口进来都合法」——后者才是安全边界，
# 前者只是体验优化，所以宁可重复也不要让表现层去 import 领域常量后以为校验已经做完。
USERNAME_MIN_LEN = 3
USERNAME_MAX_LEN = 32
PASSWORD_MIN_LEN = 8
# 字符数上限。注意它**不等于** bcrypt 的 72 字节上限（一个汉字 3 字节），
# 字节维度的约束由用例里的 WeakPasswordError 兜住
PASSWORD_MAX_LEN = 64
DISPLAY_NAME_MAX_LEN = 64
AVATAR_URL_MAX_LEN = 512
BIO_MAX_LEN = 500


# ──────────────────────────── 请求 ────────────────────────────


class RegisterRequest(BaseModel):
    """注册入参。"""

    email: EmailStr = Field(description="邮箱，作为登录账号")
    username: str = Field(
        min_length=USERNAME_MIN_LEN,
        max_length=USERNAME_MAX_LEN,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="用户名，3~32 位字母/数字/下划线/连字符",
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LEN,
        max_length=PASSWORD_MAX_LEN,
        description="明文密码，8~64 个字符",
    )
    display_name: str | None = Field(
        default=None,
        max_length=DISPLAY_NAME_MAX_LEN,
        description="展示名，留空则用用户名代替",
    )


class LoginRequest(BaseModel):
    """登录入参。

    ``password`` 刻意**不加**任何长度/复杂度约束：
        在登录口做规则校验，等于把注册页的密码策略回显给攻击者
        （试一次错的，就能从报错里读出「密码必须 8 位以上」）。
        登录只需要回答「对/不对」。
    """

    email: EmailStr
    password: str


class UpdateProfileRequest(BaseModel):
    """改资料入参（PATCH 语义）。

    配合 ``model_dump(exclude_unset=True)`` 使用：
        只有客户端**显式传过**的字段才会进入 command，没传的字段保持 UNSET 哨兵值。
        这是 PATCH 与 PUT 的分水岭——PUT 语义下没传就等于清空，PATCH 不是。
    """

    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX_LEN)
    avatar_url: str | None = Field(default=None, max_length=AVATAR_URL_MAX_LEN)
    bio: str | None = Field(default=None, max_length=BIO_MAX_LEN)


class ChangePasswordRequest(BaseModel):
    """改密入参。需要旧密码做二次确认，防止 token 被盗后直接锁死账号。"""

    old_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LEN)
    new_password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)


# ──────────────────────────── 响应 ────────────────────────────


class UserResponse(BaseModel):
    """用户出参。

    ``from_attributes=True`` 让它能直接从应用层 DTO（dataclass）构造，
    表现层无需手写逐字段搬运——DTO 加了字段这里自动跟上。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    username: str
    display_name: str
    avatar_url: str | None = None
    bio: str | None = None
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TokenResponse(BaseModel):
    """令牌出参。"""

    # 与 UserResponse 同理：它要直接从应用层的 TokenDTO（dataclass）构造
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="剩余有效秒数")


class AuthResponse(BaseModel):
    """登录出参：令牌 + 用户，避免前端登录后再打一次 /me。

    这里的 ``from_attributes`` 是**必须**的：入参是 ``AuthResultDTO`` 这个
    dataclass 实例，不开启该选项 pydantic 只认 dict / BaseModel，会直接报类型错误。
    """

    model_config = ConfigDict(from_attributes=True)

    token: TokenResponse
    user: UserResponse


__all__ = [
    "AVATAR_URL_MAX_LEN",
    "BIO_MAX_LEN",
    "DISPLAY_NAME_MAX_LEN",
    "PASSWORD_MAX_LEN",
    "PASSWORD_MIN_LEN",
    "USERNAME_MAX_LEN",
    "USERNAME_MIN_LEN",
    "AuthResponse",
    "ChangePasswordRequest",
    "LoginRequest",
    "RegisterRequest",
    "TokenResponse",
    "UpdateProfileRequest",
    "UserResponse",
]
