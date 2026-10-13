"""表现层的依赖注入入口：把「接口」和「实现」在这里接上。

分工：
    用例（application）只认 ``UserRepository`` 这个抽象；
    由本模块决定它背后是 PostgreSQL 实现、内存实现还是 Mock。

为什么这些工厂函数放在 presentation 而不是 application：
    一旦应用层自己去 new 一个 ``SqlUserRepository``，它就得 import SQLAlchemy——
    依赖倒置立刻作废，单测也没法塞假仓储。「谁最外层谁组装」是唯一不破功的答案。

事务边界提醒：本模块**不 commit**。整条依赖链共用 ``get_db`` 提供的同一个
``AsyncSession``（FastAPI 默认对同一依赖做请求内缓存），提交由 ``get_db`` 在响应
正常返回后统一完成。
"""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from agent_web_shared.security import decode_token
from app.application.identity.use_cases import (
    ChangePasswordUseCase,
    GetCurrentUserUseCase,
    LoginUserUseCase,
    RegisterUserUseCase,
    TokenConfig,
    UpdateProfileUseCase,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import InternalServerError
from app.domain.identity.entities import User
from app.domain.identity.exceptions import TokenInvalidError
from app.domain.identity.repositories import UserRepository
from app.infrastructure.persistence.repositories.user import SqlUserRepository

# ──────────────────────────── 配置 ────────────────────────────


def get_token_config() -> TokenConfig:
    """从 Settings 组装签发口径。

    ``jwt_secret_key`` 在类型上是 Optional，因为 pydantic 无法表达
    「取决于 app.env 的条件必填」；这里补上运行期断言——
    development/test 下 Settings 会自造一次性密钥，因此实际不会走到 raise。
    """
    security = get_settings().security
    secret_key = security.jwt_secret_key
    if secret_key is None:  # pragma: no cover - Settings.model_post_init 已兜住
        raise InternalServerError("SECURITY__JWT_SECRET_KEY 未配置")
    return TokenConfig(
        secret_key=secret_key.get_secret_value(),
        algorithm=security.jwt_algorithm,
        expires_minutes=security.jwt_expire_minutes,
    )


# ──────────────────────────── 仓储 ────────────────────────────


async def get_user_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRepository:
    """返回仓储**接口**类型而不是 ``SqlUserRepository``。

    这么写是有意的：类型注解即契约——调用方（用例工厂）只能看到接口，
    想换实现就改这一行，上层无感。
    """
    return SqlUserRepository(db)


# ──────────────────────────── 用例工厂 ────────────────────────────


async def get_register_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> RegisterUserUseCase:
    # bcrypt 轮数从配置取：生产 12 轮，测试环境调低可以把注册类用例从秒级压到毫秒级
    return RegisterUserUseCase(users, bcrypt_rounds=get_settings().security.bcrypt_rounds)


async def get_login_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> LoginUserUseCase:
    return LoginUserUseCase(users, get_token_config())


async def get_current_user_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> GetCurrentUserUseCase:
    return GetCurrentUserUseCase(users)


async def get_update_profile_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> UpdateProfileUseCase:
    return UpdateProfileUseCase(users)


async def get_change_password_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(users, bcrypt_rounds=get_settings().security.bcrypt_rounds)


# ──────────────────────────── 认证守卫 ────────────────────────────

# auto_error=False：默认行为是缺 header 时抛 HTTPException(403)，
# 对「没带 token」这种认证问题来说 403 是错的，且绕开了我们的 DomainError 体系
# （响应里不会带 code 业务码）。这里自己判空，统一抛 401。
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """解析 Bearer token 并返回当前用户实体，是所有受保护接口的统一入口。

    三道关，任何一道不过都抛 ``TokenInvalidError``（401）：
        ① 有没有带 Authorization: Bearer <token>
        ② 签名/有效期是否可信（``decode_token`` 内部校验 exp，过期即抛）
        ③ sub 能不能解析成 UUID，且 token 指向的用户还在、未被禁用
    """
    if credentials is None:
        raise TokenInvalidError()

    config = get_token_config()
    try:
        payload = decode_token(
            credentials.credentials,
            secret_key=config.secret_key,
            algorithms=[config.algorithm],
        )
    except jwt.InvalidTokenError as exc:
        # 签名不符 / 已过期 / 结构损坏都归为「登录态无效」——具体哪种原因不对外区分，
        # 免得给攻击者提供「这个 token 只是过期了」之类的反馈
        raise TokenInvalidError() from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenInvalidError()
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise TokenInvalidError() from exc

    user = await users.get_by_id(user_id)
    if user is None:
        # token 本身没问题，但用户已被删除：对客户端来说就是「登录态失效」，
        # 返回 404 会让人以为是自己请求的路径写错了
        raise TokenInvalidError()

    # 禁用检查放在守卫里而不是各用例里：这样「禁用账号不能做任何事」是一条
    # 由架构保证的性质，将来新增接口只要挂了守卫就自动生效，不依赖谁记得加
    user.ensure_active()
    return user


# 受保护接口的标注糖：`current_user: CurrentUser` 一行挂上认证+禁用检查。
# 后续 P3 的 require_permission 守卫会在此基础上再叠一层授权判断。
CurrentUser = Annotated[User, Depends(get_current_user)]


__all__ = [
    "CurrentUser",
    "get_change_password_use_case",
    "get_current_user",
    "get_current_user_use_case",
    "get_login_use_case",
    "get_register_use_case",
    "get_token_config",
    "get_update_profile_use_case",
    "get_user_repository",
]
