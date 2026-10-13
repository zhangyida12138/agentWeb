"""access 上下文的单元测试：不连数据库、不起 ASGI。

这一层守的是**规则**，不是**接线**：
    角色矩阵有没有漏权限、新用户拿到什么角色、DTO 会不会把未落库的实体放出去。
    这些用纯内存对象就能验完。真库相关的行为（唯一索引、事务回滚、
    N+1 是否真的只查了 3 条 SQL）留给集成测试——那才是它们能被暴露出来的地方。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.application.access.dto import PermissionDTO, RoleDTO
from app.application.identity.dto import RegisterCommand
from app.application.identity.use_cases import RegisterUserUseCase
from app.core.config import AppSettings
from app.domain.access.entities import (
    PERMISSION_SPECS,
    ROLE_SPECS,
    Permission,
    PermissionCode,
    PermissionSpec,
    Role,
    RoleCode,
    RoleSpec,
)
from app.domain.access.repositories import AccessRepository
from app.domain.identity.entities import User
from app.domain.identity.repositories import UserRepository
from app.domain.identity.value_objects import Email, Username

# ──────────────────────────── 测试替身 ────────────────────────────


class _RecordingAccess(AccessRepository):
    """只实现 ``assign_roles`` 的测试替身，用来观察「注册时挂了什么角色」。"""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, frozenset[str]]] = []

    async def assign_roles(self, user_id: UUID, role_codes: Collection[str]) -> list[Role]:
        self.calls.append((user_id, frozenset(role_codes)))
        return []

    @property
    def granted(self) -> frozenset[str]:
        """本次注册实际授予的角色码（多次调用取并集）。"""
        codes: set[str] = set()
        for _, batch in self.calls:
            codes |= batch
        return frozenset(codes)

    # 以下方法本文件用不到。显式抛 NotImplementedError 而**不是** pass / return None：
    # 将来若 execute() 多出一次仓储调用，测试会在这里明确炸掉，
    # 而不是静默拿到 None、让断言以「莫名其妙」的方式失败。
    async def list_roles(self) -> list[Role]:
        raise NotImplementedError

    async def list_permissions(self) -> list[Permission]:
        raise NotImplementedError

    async def get_role_by_code(self, code: str) -> Role | None:
        raise NotImplementedError

    async def get_roles_by_user(self, user_id: UUID) -> list[Role]:
        raise NotImplementedError

    async def get_permission_codes(self, user_id: UUID) -> set[str]:
        raise NotImplementedError

    async def get_role_codes_by_users(self, user_ids: Collection[UUID]) -> dict[UUID, set[str]]:
        raise NotImplementedError

    async def sync_catalog(
        self, role_specs: Sequence[RoleSpec], permission_specs: Sequence[PermissionSpec]
    ) -> dict[str, int]:
        raise NotImplementedError


class _EmptyUsers(UserRepository):
    """永远「查不到」的 UserRepository：模拟一个全新邮箱 / 用户名的注册。"""

    def __init__(self) -> None:
        self.added: list[User] = []

    async def add(self, user: User) -> User:
        self.added.append(user)
        # 真实仓储也是「入参实体带 id 进、带 id 出」，这里保持同一契约
        return user

    async def get_by_email(self, email: Email) -> User | None:
        return None

    async def get_by_username(self, username: Username) -> User | None:
        return None

    async def update(self, user: User) -> User:
        raise NotImplementedError

    async def get_by_id(self, user_id: UUID) -> User | None:
        raise NotImplementedError

    async def list_paged(self, offset: int, limit: int) -> list[User]:
        raise NotImplementedError

    async def count(self) -> int:
        raise NotImplementedError


def _register_use_case(
    access: AccessRepository, bootstrap_admin_email: str | None = None
) -> tuple[RegisterUserUseCase, _EmptyUsers]:
    users = _EmptyUsers()
    use_case = RegisterUserUseCase(
        users,
        access,
        # 轮数调到下限：本文件验的是「挂什么角色」，bcrypt 的强度不是这里的关注点
        bcrypt_rounds=4,
        bootstrap_admin_email=bootstrap_admin_email,
    )
    return use_case, users


def _command(email: str) -> RegisterCommand:
    return RegisterCommand(
        email=email,
        username=f"user{uuid4().hex[:10]}",
        password="Sup3r-secret",
        display_name=None,
    )


# ──────────────────────────── 权限矩阵 ────────────────────────────


def _spec(code: str) -> RoleSpec:
    return next(spec for spec in ROLE_SPECS if spec.code == code)


def test_admin_holds_every_declared_permission() -> None:
    """admin 必须覆盖全部权限点。

    这条断言的价值不在「今天是不是 11 个」，而在于：将来往 PERMISSION_SPECS
    里加一个权限点、却忘了给 admin 也加上时，测试会立刻变红。
    靠人眼维护矩阵，漏项是迟早的事。
    """
    declared = {spec.code for spec in PERMISSION_SPECS}
    assert _spec(RoleCode.ADMIN).permissions == declared


def test_reader_permission_count() -> None:
    """reader 恰好是「评论 + 点赞 + AI」，不多不少。

    写死数量而不是只判包含：「多给了权限」和「少给了权限」一样是事故，
    而只判包含的写法对前者完全无感。
    """
    assert _spec(RoleCode.READER).permissions == frozenset(
        {
            PermissionCode.COMMENT_CREATE,
            PermissionCode.LIKE_TOGGLE,
            PermissionCode.AGENT_CHAT,
        }
    )


def test_author_permission_count() -> None:
    """author = reader 的全部 + 4 个文章权限。"""
    assert _spec(RoleCode.AUTHOR).permissions == _spec(RoleCode.READER).permissions | {
        PermissionCode.POST_CREATE,
        PermissionCode.POST_UPDATE,
        PermissionCode.POST_PUBLISH,
        PermissionCode.POST_DELETE,
    }


def test_reader_is_subset_of_author_and_author_is_subset_of_admin() -> None:
    """内置角色必须是层层包含的，不能出现「author 反而没有 reader 的某个权限」。

    这是**产品语义**而不只是数据整洁：一个作者当然能评论、能点赞。
    一旦有人把某个权限从 reader 挪到 author，这条断言会拦住他。
    """
    reader = _spec(RoleCode.READER).permissions
    author = _spec(RoleCode.AUTHOR).permissions
    admin = _spec(RoleCode.ADMIN).permissions

    assert reader <= author <= admin


def test_role_specs_only_reference_declared_permissions() -> None:
    """角色里引用的权限码必须在权限点表里存在。

    ``frozenset({...})`` 里的字符串拼错一个字母不会报错，
    只会表现为「这个角色莫名其妙少了某个权限」，而且只有真人点到那个按钮才发现。
    """
    declared = {spec.code for spec in PERMISSION_SPECS}
    for spec in ROLE_SPECS:
        unknown = spec.permissions - declared
        assert not unknown, f"角色 {spec.code} 引用了未声明的权限码：{sorted(unknown)}"


def test_permission_codes_are_unique() -> None:
    """权限码不能重复——重复意味着同一个权限在库里会有两行、前端矩阵多一列。"""
    codes = [spec.code for spec in PERMISSION_SPECS]
    assert len(codes) == len(set(codes))


def test_role_codes_are_unique() -> None:
    """角色码同理：唯一索引会在启动时抛错，早一步在这里拦住更省事。"""
    codes = [spec.code for spec in ROLE_SPECS]
    assert len(codes) == len(set(codes))


def test_role_has_permission() -> None:
    """``Role.has_permission`` 是集合判包含，不是模糊匹配。

    特意验一次「前缀不算命中」：``user:list`` 与 ``user:list:all`` 这类
    相近编码很容易被写成 ``startswith``，那会让权限越给越多。
    """
    role = Role(
        code="t",
        name="临时角色",
        permission_codes=frozenset({PermissionCode.USER_LIST}),
    )

    assert role.has_permission(PermissionCode.USER_LIST)
    assert not role.has_permission(PermissionCode.USER_ASSIGN_ROLES)
    assert not role.has_permission("user:lis")


# ──────────────────────────── DTO 边界 ────────────────────────────


def test_role_dto_rejects_entity_without_id() -> None:
    """未落库的实体（没有 id）不允许变成出参 DTO。

    与其返回一个 ``id=None`` 让前端拿着空值去拼 URL、在另一个页面报 404，
    不如在响应构造那一刻就炸掉——堆栈会直接指到真正出问题的调用点。
    """
    with pytest.raises(ValueError, match="已持久化"):
        RoleDTO.from_entity(Role(code=RoleCode.READER, name="读者"))


def test_permission_dto_rejects_entity_without_id() -> None:
    with pytest.raises(ValueError, match="已持久化"):
        PermissionDTO.from_entity(Permission(code=PermissionCode.USER_LIST, name="查看用户列表"))


# ──────────────────────────── 引导管理员配置 ────────────────────────────


def test_blank_bootstrap_admin_email_means_disabled() -> None:
    """``APP__BOOTSTRAP_ADMIN_EMAIL=``（值留空）等价于没配。

    这是运维最常见的「关掉它」写法。若不做归一处理，空串会走进邮箱校验，
    应用直接以一条「不是合法邮箱」的报错起不来，排查方向会被带偏到「我的邮箱格式哪里错了」。
    """
    assert AppSettings(bootstrap_admin_email="").bootstrap_admin_email is None
    assert AppSettings(bootstrap_admin_email="   ").bootstrap_admin_email is None
    assert AppSettings().bootstrap_admin_email is None


def test_invalid_bootstrap_admin_email_fails_fast() -> None:
    """写错的邮箱要在启动时就报错，而不是静默不生效。

    静默失败的后果很具体：线上部署时敲错一个字母，
    引导管理员没拿到 admin，于是没有任何人能进管理接口——还得靠翻配置文件才发现。
    """
    with pytest.raises(ValidationError):
        AppSettings(bootstrap_admin_email="not-an-email")


# ──────────────────────────── 注册时的默认角色 ────────────────────────────


async def test_register_grants_reader_by_default() -> None:
    """新用户默认是 reader。

    没有这一步，「谁能做什么」这套模型就是空的：用户注册完在 user_roles 里
    一行都没有，所有需要权限的接口对他一律 403，
    而他连「我该找谁要权限」都无从判断。
    """
    access = _RecordingAccess()
    use_case, users = _register_use_case(access)

    dto = await use_case.execute(_command("newbie@example.com"))

    assert len(users.added) == 1
    assert access.calls == [(users.added[0].id, frozenset({RoleCode.READER}))]
    assert dto.email == "newbie@example.com"


async def test_register_grants_admin_for_bootstrap_email() -> None:
    """邮箱命中引导配置时授予 admin。"""
    access = _RecordingAccess()
    use_case, _ = _register_use_case(access, bootstrap_admin_email="boss@example.com")

    await use_case.execute(_command("boss@example.com"))

    assert access.granted == frozenset({RoleCode.ADMIN})


async def test_bootstrap_email_matches_ignoring_case_and_whitespace() -> None:
    """引导邮箱的比对要两边统一口径。

    ``Email`` 值对象会把整个邮箱转小写，而 pydantic 的 EmailStr 只保证域名小写、
    局部部分原样保留。不归一化的话，配置里写 ``Boss@Example.com``
    就永远匹配不上 ``boss@example.com``——一个字母大小写就能让引导失效。
    """
    access = _RecordingAccess()
    use_case, _ = _register_use_case(access, bootstrap_admin_email="  BOSS@Example.com  ")

    await use_case.execute(_command("boss@example.com"))

    assert access.granted == frozenset({RoleCode.ADMIN})


async def test_other_emails_still_get_reader_when_bootstrap_is_set() -> None:
    """配了引导邮箱不等于「所有人都是管理员」——这是最容易写反的一处。"""
    access = _RecordingAccess()
    use_case, _ = _register_use_case(access, bootstrap_admin_email="boss@example.com")

    await use_case.execute(_command("someone-else@example.com"))

    assert access.granted == frozenset({RoleCode.READER})
