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
from app.application.blog.use_cases import (
    CreatePostUseCase,
    DeletePostUseCase,
    GetPostBySlugUseCase,
    ListMyPostsUseCase,
    ListPublishedPostsUseCase,
    PublishPostUseCase,
    UnpublishPostUseCase,
    UpdatePostUseCase,
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
from app.application.interaction.use_cases import (
    CreateCommentUseCase,
    DeleteCommentUseCase,
    GetPostInteractionStatsUseCase,
    ListCommentsUseCase,
    ToggleLikeUseCase,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import InternalServerError
from app.domain.access.exceptions import PermissionDeniedError
from app.domain.access.repositories import AccessRepository
from app.domain.blog.repositories import PostRepository
from app.domain.identity.entities import User
from app.domain.identity.exceptions import TokenInvalidError
from app.domain.identity.repositories import UserRepository
from app.domain.interaction.repositories import CommentRepository, LikeRepository
from app.infrastructure.persistence.repositories.access import SqlAccessRepository
from app.infrastructure.persistence.repositories.interaction import (
    SqlCommentRepository,
    SqlLikeRepository,
)
from app.infrastructure.persistence.repositories.post import SqlPostRepository
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


async def get_post_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostRepository:
    """同 ``get_user_repository``：对外只暴露接口类型。

    注意三个仓储共用**同一个** ``get_db`` 提供的 session，因此也在同一个事务里：
    「创建文章 + 关联标签」这种跨表写入失败时会一起回滚，不需要用例操心。
    """
    return SqlPostRepository(db)


async def get_comment_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CommentRepository:
    """评论仓储（对外只暴露接口类型）。"""
    return SqlCommentRepository(db)


async def get_like_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LikeRepository:
    """点赞仓储（对外只暴露接口类型）。

    点赞与评论共用同一个 session：``POST /likes/toggle`` 里「确认目标存在
    然后点赞」必须在一个事务里，否则目标可能在两步之间被删掉。
    """
    return SqlLikeRepository(db)


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


# ────────────────────── 博客上下文的用例工厂 ──────────────────────


async def get_list_published_posts_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> ListPublishedPostsUseCase:
    return ListPublishedPostsUseCase(posts)


async def get_post_by_slug_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> GetPostBySlugUseCase:
    return GetPostBySlugUseCase(posts)


async def get_list_my_posts_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> ListMyPostsUseCase:
    return ListMyPostsUseCase(posts)


async def get_create_post_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> CreatePostUseCase:
    return CreatePostUseCase(posts)


async def get_update_post_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> UpdatePostUseCase:
    return UpdatePostUseCase(posts)


async def get_publish_post_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> PublishPostUseCase:
    return PublishPostUseCase(posts)


async def get_unpublish_post_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> UnpublishPostUseCase:
    return UnpublishPostUseCase(posts)


async def get_delete_post_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
) -> DeletePostUseCase:
    return DeletePostUseCase(posts)


# ──────────────────── 互动上下文的用例工厂 ────────────────────


async def get_list_comments_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
    comments: Annotated[CommentRepository, Depends(get_comment_repository)],
    likes: Annotated[LikeRepository, Depends(get_like_repository)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ListCommentsUseCase:
    """评论树用例要同时拿到文章、评论、点赞、用户四个仓储。

    这是**跨上下文编排**在依赖注入里的具体形状：``ListCommentsUseCase`` 需要
    先按 id 定位文章（属于 blog 上下文），再取评论树（属于 interaction），
    补上点赞统计（同属 interaction），最后批量把作者名解析出来（属于 identity）。
    四个仓储共用一个 session、一个事务。

    ★ 用户仓储之所以在这一层而不是在用例里自己 new：
        作者名是**响应的一部分**，不是一个可选的装饰。
        让它成为一个声明的依赖，就意味着“忘了接上它就根本跑不起来”，
        而不是“跑起来了但名字是空的”（后者只会在界面上被发现有错）。

    这里注入的是**接口**而不是实现，所以将来评论树改从缓存读，
    只需要换掉 ``get_comment_repository`` 的那一行。
    """
    return ListCommentsUseCase(posts, comments, likes, users)


async def get_post_interaction_stats_use_case(
    comments: Annotated[CommentRepository, Depends(get_comment_repository)],
    likes: Annotated[LikeRepository, Depends(get_like_repository)],
) -> GetPostInteractionStatsUseCase:
    """互动统计用例（喂给文章列表 / 详情的赞数与评论数）。"""
    return GetPostInteractionStatsUseCase(comments, likes)


async def get_create_comment_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
    comments: Annotated[CommentRepository, Depends(get_comment_repository)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> CreateCommentUseCase:
    """发评论也要用户仓储：返回值会被前端直接插进评论树，
    所以“谁写的 / 回了谁”必须在同一个响应里给出。
    """
    return CreateCommentUseCase(posts, comments, users)


async def get_delete_comment_use_case(
    comments: Annotated[CommentRepository, Depends(get_comment_repository)],
) -> DeleteCommentUseCase:
    return DeleteCommentUseCase(comments)


async def get_toggle_like_use_case(
    posts: Annotated[PostRepository, Depends(get_post_repository)],
    comments: Annotated[CommentRepository, Depends(get_comment_repository)],
    likes: Annotated[LikeRepository, Depends(get_like_repository)],
) -> ToggleLikeUseCase:
    """点赞用例要三个仓储：目标可能是文章也可能是评论（多态），
    所以两种目标的存在性检查都得能做。
    """
    return ToggleLikeUseCase(posts, comments, likes)


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


async def get_current_user_id(current_user: CurrentUser) -> uuid.UUID:
    """当前用户 id 的「非空版本」。

    ``User.id`` 在类型上是 ``UUID | None``（实体在持久化之前确实没有 id），
    但**从仓储取出来的实体必然已经落库**，所以这里的不可能分支只是给类型检查看的。

    把这个断言收进一个依赖的理由：
        写接口普遍只需要 id，不需要整个实体。如果让它们都拿 ``CurrentUser``
        再各自写一遍 ``if user.id is None: raise ...``，那段守卫会被复制到每个端点；
        漏写一处不会报错，只会在类型检查里变成一个 ``type: ignore``——
        而 ``type: ignore`` 正是「我不知道这里安不安全」的白旗。
    """
    user_id = current_user.id
    if user_id is None:  # pragma: no cover - 守卫出来的实体必然来自仓储，id 不会为空
        raise TokenInvalidError()
    return user_id


# 只需要「谁在操作」而不需要用户其他字段时的标注糖。
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


async def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User | None:
    """尽力识别当前用户：没带 token、token 失效或账号被停用，都返回 ``None``。

    公开读接口（文章列表 / 详情）要在同一条路径上服务两种访问者：
        游客 —— 已发布的文章人人可看；
        作者本人 —— 连自己未发布的草稿也要能预览（编辑器里点「预览」就是这条路径）。

    两者不能拆成两个接口：拆了就会出现「游客版详情」和「作者版详情」两份渲染逻辑，
    而它们展示的明明是同一篇文章。所以阅读接口统一走「识别到就是本人，识别不到就是游客」。

    ⚠️ 不能用「先试 ``get_current_user``、失败就兜成 None」来简化：
        那需要在一个依赖里 ``try/except`` 另一个依赖，把 401 当成控制流；
        而这个函数的作用是**返回 None**，不是「吞掉异常」。
        另写一份显式实现，读起来才能一眼看到「哪些情况算游客」。

    ⚠️ 与 ``get_current_user`` 的另一个区别：**账号被停用时返回 None 而不是 401**。
        停用只应让写操作失效；一个失效的 token 不该让公开页面整体打不开。
        此时它的可见范围退回游客口径（看不到自己的草稿），这是个安全的下沉选择。
    """
    if credentials is None:
        return None

    config = get_token_config()
    try:
        payload = decode_token(
            credentials.credentials,
            secret_key=config.secret_key,
            algorithms=[config.algorithm],
        )
    except jwt.InvalidTokenError:
        return None

    subject = payload.get("sub")
    if not isinstance(subject, str):
        return None
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        return None

    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        return None
    return user


# 公开读接口的标注糖：`viewer: OptionalCurrentUser` 一行表达「可能是游客」。
OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]


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


def require_permission_with_codes(
    code: str,
) -> Callable[..., Awaitable[frozenset[str]]]:
    """要求当前用户拥有 ``code``，并把该用户的**全部权限码**一并返回。

    为什么需要它（而不是「守卫 + 再查一次权限」）：
        写文章的接口除了「有没有基础权限（``post:update``）」，
        还要判断「有没有越权钥匙（``post:update_any``）」——
        后者只影响「改自己的还是改别人的」，不是一个能拦住请求的门槛。

        如果分两个依赖去取，同一个用户在这次请求里会被查两遍权限；
        更要紧的是两次判断可能读到**不同的权限快照**：
        管理员在两次查询之间撤了权，就会出现「守卫放行了、越权判定说没有」这种
        自相矛盾的结果。合并成一次查询，两个判断共用同一份快照，不可能不一致。

    返回值就是权限码集合，判定交给调用方写明条件（例如
    ``PermissionCode.POST_UPDATE_ANY in codes``），而不是在这里猜「什么算越权」——
    「基础码 → 对应哪个钥匙」是博客上下文的知识，不该渗进这个通用守卫。
    """
    required = code

    async def _guard(
        current_user: CurrentUser,
        access: Annotated[AccessRepository, Depends(get_access_repository)],
    ) -> frozenset[str]:
        user_id = current_user.id
        if user_id is None:  # pragma: no cover - 守卫出来的实体必然来自仓储，id 不会为空
            raise TokenInvalidError()

        owned = frozenset(await access.get_permission_codes(user_id))
        if required not in owned:
            raise PermissionDeniedError(required)
        return owned

    return _guard


# 认证（401）与授权（403）分属两个异常，异常处理器据此映射状态码。
# 这里不做「已登录就一定有权限」之类的兜底——默认拒绝，漏挂守卫的接口会 401 而不是放行。


__all__ = [
    "CurrentUser",
    "CurrentUserId",
    "OptionalCurrentUser",
    "get_access_repository",
    "get_assign_roles_use_case",
    "get_change_password_use_case",
    "get_create_post_use_case",
    "get_current_user",
    "get_current_user_id",
    "get_current_user_use_case",
    "get_delete_post_use_case",
    "get_list_my_posts_use_case",
    "get_list_permissions_use_case",
    "get_list_published_posts_use_case",
    "get_list_roles_use_case",
    "get_list_user_roles_use_case",
    "get_list_users_use_case",
    "get_login_use_case",
    "get_my_access_use_case",
    "get_optional_current_user",
    "get_post_by_slug_use_case",
    "get_post_repository",
    "get_publish_post_use_case",
    "get_register_use_case",
    "get_reset_user_password_use_case",
    "get_token_config",
    "get_unpublish_post_use_case",
    "get_update_post_use_case",
    "get_update_profile_use_case",
    "get_user_repository",
    "require_permission",
    "require_permission_with_codes",
]
