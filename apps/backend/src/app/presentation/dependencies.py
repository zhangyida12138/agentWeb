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
from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from agent_web_shared.security import decode_token
from app.application.access.use_cases import (
    AssignRolesUseCase,
    GetMyAccessUseCase,
    ListPermissionsUseCase,
    ListRolesUseCase,
    ListUserRolesUseCase,
    ListUsersUseCase,
)
from app.application.identity.use_cases import (
    ChangePasswordUseCase,
    GetCurrentUserUseCase,
    LoginUserUseCase,
    RegisterUserUseCase,
    ResetUserPasswordUseCase,
    TokenConfig,
    UpdateProfileUseCase,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import InternalServerError
from app.domain.access.exceptions import PermissionDeniedError
from app.domain.access.repositories import AccessRepository
from app.domain.identity.entities import User
from app.domain.identity.exceptions import TokenInvalidError
from app.domain.identity.repositories import UserRepository
from app.infrastructure.persistence.repositories.access import SqlAccessRepository
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


async def get_access_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccessRepository:
    """同 ``get_user_repository``：对外只暴露接口类型。"""
    return SqlAccessRepository(db)


# ──────────────────────────── 用例工厂 ────────────────────────────


async def get_register_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> RegisterUserUseCase:
    # bcrypt 轮数从配置取：生产 12 轮，测试环境调低可以把注册类用例从秒级压到毫秒级
    return RegisterUserUseCase(
        users,
        access,
        bcrypt_rounds=get_settings().security.bcrypt_rounds,
        bootstrap_admin_email=get_settings().app.bootstrap_admin_email,
    )


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


async def get_list_roles_use_case(
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> ListRolesUseCase:
    return ListRolesUseCase(access)


async def get_list_permissions_use_case(
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> ListPermissionsUseCase:
    return ListPermissionsUseCase(access)


async def get_list_users_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> ListUsersUseCase:
    return ListUsersUseCase(users, access)


async def get_list_user_roles_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> ListUserRolesUseCase:
    return ListUserRolesUseCase(users, access)


async def get_assign_roles_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> AssignRolesUseCase:
    return AssignRolesUseCase(users, access)


async def get_reset_user_password_use_case(
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ResetUserPasswordUseCase:
    """管理员重置密码的用例工厂。

    它**不**接收调用者身份：授权是表现层 ``require_permission`` 的职责，
    把「谁在调」传进用例会让应用层长出第二套权限判断，
    将来换入口（CLI、定时任务）就得复制一遍。
    """
    return ResetUserPasswordUseCase(users, bcrypt_rounds=get_settings().security.bcrypt_rounds)


async def get_my_access_use_case(
    access: Annotated[AccessRepository, Depends(get_access_repository)],
) -> GetMyAccessUseCase:
    return GetMyAccessUseCase(access)


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
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(code: str) -> Callable[..., Awaitable[User]]:
    """生成「要求当前用户拥有 ``code`` 权限」的依赖。

    这是**工厂**而不是普通依赖：授权判断需要一个「要什么权限」的参数，
    而 FastAPI 的 ``Depends`` 无法给被依赖的函数传业务参数，
    于是把参数留在外层、把依赖函数闭包出来。

    用法（放在路由装饰器的 ``dependencies`` 里，不关心当前用户时）::

        @router.get("/users", dependencies=[Depends(require_permission(code))])

    需要拿到当前用户时，直接当参数注解用::

        current_user: Annotated[User, Depends(require_permission(code))]

    ``code`` 一律从 ``domain/access/entities.py`` 的 ``PermissionCode`` 取，
    不要写字面量：写错一个字母不会报错，只会让接口永远 403。

    「守卫在依赖层，不在用例层」是刻意的：这样「这个接口需要什么权限」
    和接口定义挨在一起，一眼能看全；用例则保持与 HTTP 无关，可被任意调用方复用。
    """
    # 权限码在「创建依赖」时就固定下来，避免请求期再取一次
    required = code

    async def _guard(
        current_user: CurrentUser,
        access: Annotated[AccessRepository, Depends(get_access_repository)],
    ) -> User:
        user_id = current_user.id
        if user_id is None:  # pragma: no cover - 守卫出来的实体必然来自仓储，id 不会为空
            raise TokenInvalidError()

        # 每次请求现查一次权限，而不是塞进 token：token 里带权限的确能省一次查询，
        # 但撤权要等到 token 过期才生效——「刚把某人降级、他还能用十分钟」
        # 对管理接口来说是不可接受的。这里用一次查询换掉这个窗口。
        owned = await access.get_permission_codes(user_id)
        if required not in owned:
            raise PermissionDeniedError(required)
        return current_user

    return _guard


# 认证（401）与授权（403）分属两个异常，异常处理器据此映射状态码。
# 这里不做「已登录就一定有权限」之类的兜底——默认拒绝，漏挂守卫的接口会 401 而不是放行。


__all__ = [
    "CurrentUser",
    "get_access_repository",
    "get_assign_roles_use_case",
    "get_change_password_use_case",
    "get_current_user",
    "get_current_user_use_case",
    "get_list_permissions_use_case",
    "get_list_roles_use_case",
    "get_list_user_roles_use_case",
    "get_list_users_use_case",
    "get_login_use_case",
    "get_my_access_use_case",
    "get_register_use_case",
    "get_reset_user_password_use_case",
    "get_token_config",
    "get_update_profile_use_case",
    "get_user_repository",
    "require_permission",
]
