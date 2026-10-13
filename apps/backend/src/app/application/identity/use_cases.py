"""identity 上下文的应用层用例。

用例的职责边界（多一分少一分都算越界）：
    做：「取数据 → 调领域规则 → 存数据」的编排，以及把技术细节翻译成领域语义。
    不做：业务规则本身（住在 domain/identity/entities.py），
          参数格式校验（住在 presentation 的 schema），事务提交（住在 core/database.py）。

依赖注入一律走构造函数：仓储是接口（依赖倒置），配置是纯数据。
因此这些用例可以被纯内存的假仓储驱动，不需要数据库、不需要 Web 框架。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent_web_shared.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.application.identity.dto import (
    AuthResultDTO,
    ChangePasswordCommand,
    LoginCommand,
    RegisterCommand,
    ResetPasswordCommand,
    TokenDTO,
    Unset,
    UpdateProfileCommand,
    UserDTO,
)
from app.domain.access.entities import RoleCode
from app.domain.access.repositories import AccessRepository
from app.domain.identity.entities import User
from app.domain.identity.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    UsernameAlreadyTakenError,
    UserNotFoundError,
    WeakPasswordError,
)
from app.domain.identity.repositories import UserRepository
from app.domain.identity.value_objects import Email, Username

# ──────────────────────────── 注入用的配置 ────────────────────────────


@dataclass(frozen=True, slots=True)
class TokenConfig:
    """签发 access token 的口径。

    为什么以参数注入而不是让用例直接读 ``get_settings()``：
        - 用例一旦读全局单例，测试就得去改环境变量或清理缓存，顺序依赖随之而来；
        - 密钥是**部署期**才确定的输入，显式注入让「这个用例需要什么」一目了然。
    表现层负责从 Settings 组装后传进来。
    """

    secret_key: str
    algorithm: str = "HS256"
    expires_minutes: int = 60


# ──────────────────────────── 内部辅助 ────────────────────────────


def _hash_password(plain_password: str, *, rounds: int) -> str:
    """哈希明文密码，并把 shared 层的 ``ValueError`` 收敛成领域异常。

    ``hash_password`` 会因「空密码」或「UTF-8 超过 72 字节」抛 ``ValueError``——
    两者都是客户端参数问题，不该以 500 的形式返回。
    """
    try:
        return hash_password(plain_password, rounds=rounds)
    except ValueError as exc:
        raise WeakPasswordError("密码不合法：长度需在 1~72 字节之间") from exc


def _require_id(user: User) -> uuid.UUID:
    """取实体的主键。

    ``User.id`` 是 ``Optional``，只因为在「刚构造、还没落库」的阶段它确实是空的；
    凡是走到用例里的实体都来自仓储，取不到 id 说明装配错了，属于内部错误。
    """
    if user.id is None:
        msg = "用例收到的实体缺少 id，说明它没有经过仓储"
        raise ValueError(msg)
    return user.id


async def _load(users: UserRepository, user_id: uuid.UUID) -> User:
    """按主键取用户，取不到就抛 404 领域异常，避免每个用例各写一遍。"""
    user = await users.get_by_id(user_id)
    if user is None:
        raise UserNotFoundError()
    return user


# ──────────────────────────── 注册 ────────────────────────────


class RegisterUserUseCase:
    """注册：查重 → 哈希密码 → 建实体 → 落库 → 授予初始角色。"""

    def __init__(
        self,
        users: UserRepository,
        access: AccessRepository,
        *,
        bcrypt_rounds: int = 12,
        bootstrap_admin_email: str | None = None,
    ) -> None:
        self._users = users
        # 可注入的算力开关：生产用 12 轮，测试可以调到 4 轮把单测从秒级压到毫秒级
        self._bcrypt_rounds = bcrypt_rounds
        # 跨上下文协作：注册成功后要挂角色，所以这里也依赖 access。
        # 依赖依旧只是**抽象**（依赖倒置没破），用例照样能被内存假仓储驱动。
        self._access = access
        # 归一化后再比较：Email 值对象会把整个邮箱转小写，而 pydantic 的 EmailStr
        # 只保证**域名**小写、局部部分原样保留。不统一口径的话，
        # 配 Admin@Example.com 就永远匹配不上 admin@example.com。
        # strip 同理：.env 里行尾多一个空格是最常见的手滑，
        # 而它造成的后果是「引导管理员悄悄失效」，必须顺手抹掉。
        self._bootstrap_admin_email = (
            bootstrap_admin_email.strip().lower() if bootstrap_admin_email else None
        )

    async def execute(self, command: RegisterCommand) -> UserDTO:
        # ── 第一步：把原始字符串升格成值对象 ──
        # 放在最前面：归一化（邮箱小写、两端去空格）只有做一次的机会，
        # 查重、落库、后续登录必须共用同一个归一口径，否则「大小写不同的同名邮箱」
        # 会在查重时漏判、在唯一索引上才炸出来。
        email = Email(command.email)
        username = Username(command.username)

        # ── 第二步：查重 ──
        # 只为「友好报错」。真正的唯一性由 DB 唯一索引保证：并发下两个请求可能同时
        # 通过这里，随后其中一个在 INSERT 时撞索引——仓储会把 IntegrityError 翻译成
        # 同名的领域异常，所以两条路径对外表现完全一致（都是 409）。
        # 查重与兜底两者缺一不可：只有查重 → 并发漏判；只有兜底 → 正常场景也报 409 且无字段提示。
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError()
        if await self._users.get_by_username(username) is not None:
            raise UsernameAlreadyTakenError()

        # ── 第三步：哈希后就地丢弃明文 ──
        # 明文只在这里停留到哈希完成那一刻：password_hash 一旦拿到值，
        # 这个进程里就再没有指向明文的引用路径了。
        user = User.register(
            email=email,
            username=username,
            password_hash=_hash_password(command.password, rounds=self._bcrypt_rounds),
            display_name=command.display_name,
        )

        # ── 第四步：落库（仓储内部会 flush，唯一约束冲突在这里就会抛出来）──
        created = await self._users.add(user)

        # ── 第五步：授予初始角色 ──
        # 必须在 add() 之后：角色绑定需要用户的 id，而 id 由 User.register 生成、
        # 借 add() 写进库。这一步与上一步共用同一个事务——角色分配失败会把用户一起
        # 回滚掉，绝不会留下「有账号但一条权限都没有」的半成品。
        await self._access.assign_roles(_require_id(created), {self._role_for(email)})
        return UserDTO.from_entity(created)

    def _role_for(self, email: Email) -> str:
        """决定新用户的初始角色编码。

        单独抽成方法而不是写在 execute 里：这是一条**策略**，
        「引导邮箱 → admin，其余 → reader」以后可能变（比如改成邀请码机制），
        届时只改这一处，execute 的流程不受影响。
        """
        if self._bootstrap_admin_email is not None and email.value == self._bootstrap_admin_email:
            return RoleCode.ADMIN
        return RoleCode.READER


# ──────────────────────────── 登录 ────────────────────────────


class LoginUserUseCase:
    """登录：验密 → 检查账号状态 → 签发 token。"""

    def __init__(self, users: UserRepository, token_config: TokenConfig) -> None:
        self._users = users
        self._token_config = token_config

    async def execute(self, command: LoginCommand) -> AuthResultDTO:
        # 同样先升格成值对象：库里存的是归一化后的邮箱，
        # 若拿客户端原样的字符串去查，「Alice@Example.COM」会查不到自己。
        # 格式非法时抛 InvalidEmailError（400）——从 HTTP 进来时 schema 已经拦住了，
        # 这里只是让「直接调用用例」的路径也有确定行为。
        user = await self._users.get_by_email(Email(command.email))

        # 「用户不存在」与「密码错误」共用同一个异常和文案：
        # 分开提示的话，这个接口就变成了「批量探测邮箱是否已注册」的工具。
        # 注意顺序——先验密码再查禁用状态：若先报「账号被禁用」，
        # 等于承认了这个账号存在且密码正确。
        if user is None or not verify_password(command.password, user.password_hash):
            raise InvalidCredentialsError()

        user.ensure_active()
        return AuthResultDTO(user=UserDTO.from_entity(user), token=self._issue(user))

    def _issue(self, user: User) -> TokenDTO:
        """签发 access token。

        ``sub`` 必须是**字符串**：这是 JWT 规范要求，也是各家库在还原 int/UUID 时
        行为不一致的地方（有的给 int，有的给 str），存字符串能完全绕开这个坑。
        """
        token = create_access_token(
            str(_require_id(user)),
            secret_key=self._token_config.secret_key,
            algorithm=self._token_config.algorithm,
            expires_minutes=self._token_config.expires_minutes,
        )
        return TokenDTO(
            access_token=token,
            token_type="bearer",
            expires_in=self._token_config.expires_minutes * 60,
        )


# ──────────────────────────── 当前用户 ────────────────────────────


class GetCurrentUserUseCase:
    """读当前用户。

    守卫（``get_current_user``）已经解过 token 并查过一次库，这里再查一次并不会多打
    一条 SQL：同一个请求共用 ``get_db`` 的 session，``session.get()`` 命中 identity map
    直接返回内存里的实例。留着这次查询是为了让「token 里的用户在两次操作之间被删掉」
    表现为规整的 404，而不是一个带着悬空 id 的响应。
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, user_id: uuid.UUID) -> UserDTO:
        return UserDTO.from_entity(await _load(self._users, user_id))


# ──────────────────────────── 修改资料 ────────────────────────────


class UpdateProfileUseCase:
    """按 PATCH 语义修改资料。"""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, user_id: uuid.UUID, command: UpdateProfileCommand) -> UserDTO:
        user = await _load(self._users, user_id)

        # 只把「客户端真的传了」的字段交给实体：UNSET → 跳过，None → 清空。
        # 过滤动作放在这里而不是实体里，是因为「有没有传」是协议层信息，
        # 领域对象不该知道 HTTP 的 PATCH 约定。
        changes = {
            field: value
            for field, value in (
                ("display_name", command.display_name),
                ("avatar_url", command.avatar_url),
                ("bio", command.bio),
            )
            if not isinstance(value, Unset)
        }
        # 一个字段都没传就别写库：省掉一次无意义的 UPDATE 和 updated_at 的跳动
        if changes:
            user.update_profile(**changes)
            await self._users.update(user)
        return UserDTO.from_entity(user)


# ──────────────────────────── 修改密码 ────────────────────────────


class ChangePasswordUseCase:
    """改密：先验旧密码，再换新哈希。"""

    def __init__(self, users: UserRepository, *, bcrypt_rounds: int = 12) -> None:
        self._users = users
        self._bcrypt_rounds = bcrypt_rounds

    async def execute(self, user_id: uuid.UUID, command: ChangePasswordCommand) -> None:
        user = await _load(self._users, user_id)

        # 必须验旧密码：否则任何一个被窃取的 access token 都能直接改掉密码，
        # 把真正的机主锁在门外（token 有效期内无法自救）。
        if not verify_password(command.old_password, user.password_hash):
            raise InvalidCredentialsError("原密码不正确")

        user.change_password(_hash_password(command.new_password, rounds=self._bcrypt_rounds))
        await self._users.update(user)


# ──────────────────────────── 管理员重置密码 ────────────────────────────


class ResetUserPasswordUseCase:
    """管理员重置指定用户的密码：直接换新哈希，不校验旧密码。

    「谁能调用它」完全由表现层的 ``require_permission(USER_RESET_PASSWORD)`` 决定，
    用例自己不判断调用者是谁——这是分层的结果：
        授权是「这次请求允不允许」的问题，属于表现层；
        用例只回答「给定一个用户和一份新密码，怎么改」。
    好处是这个用例可以被「批量重置」「命令行重置」等任何入口复用，
    而不必在每个入口重写一遍「你是不是管理员」。

    ⚠️ 副作用提示：改密**不会**让已签发的 access token 立即失效。
    本项目的 token 是无状态 JWT，服务端不留会话，因此「重置后把别人踢下线」
    需要一张吊销名单（或把密码哈希掺进签名），当前不在范围内。
    前端的弹窗里必须把这一点明确告诉管理员，否则他会以为重置等于踢人。
    """

    def __init__(self, users: UserRepository, *, bcrypt_rounds: int = 12) -> None:
        self._users = users
        self._bcrypt_rounds = bcrypt_rounds

    async def execute(self, user_id: uuid.UUID, command: ResetPasswordCommand) -> UserDTO:
        # 复用 _load：目标用户不存在时抛 UserNotFoundError（404），
        # 与「分配角色给不存在的人」表现一致，前端不必分辨两种 404
        user = await _load(self._users, user_id)
        user.change_password(_hash_password(command.new_password, rounds=self._bcrypt_rounds))
        await self._users.update(user)
        return UserDTO.from_entity(user)


__all__ = [
    "ChangePasswordUseCase",
    "GetCurrentUserUseCase",
    "LoginUserUseCase",
    "RegisterUserUseCase",
    "ResetUserPasswordUseCase",
    "TokenConfig",
    "UpdateProfileUseCase",
]
