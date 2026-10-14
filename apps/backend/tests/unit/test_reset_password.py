"""管理员重置密码与「我的权限快照」的单元测试：不连数据库、不起 ASGI。

这一层要守住三件**规则**，它们都是「写错了也照样能跑通」的那种错：

    ① 重置密码只认新密码，不需要旧密码。
       反例是照抄 ``ChangePasswordUseCase`` 顺手沿用同一个 command——
       代码能跑，功能却废了：忘记密码的用户永远救不回来。

    ② 重置写进库的必须是**哈希**，不是明文。
       这条断言用 ``verify_password``（真 bcrypt 比对）而不是「字符串变了」来验：
       后者对「把所有用户的密码统一改成 'x'」这种实现也是绿的。

    ③ 权限快照必须来自**与守卫同一个**仓储方法。
       如果哪天有人在用例里改成「从角色内存里求并集」，
       前端就会拿着偏小的权限集把按钮藏起来，而接口其实放行——
       这类错位在集成测试里才会以 403 的形式暴露，太晚。

真库相关的行为（唯一索引、事务回滚）不在这里验，那是集成测试的活。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from uuid import UUID, uuid4

import pytest

from agent_web_shared.security import hash_password, verify_password
from app.application.access.dto import AccessSummaryDTO
from app.application.access.use_cases import GetMyAccessUseCase
from app.application.identity.dto import ResetPasswordCommand
from app.application.identity.use_cases import ResetUserPasswordUseCase
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
from app.domain.identity.exceptions import UserNotFoundError, WeakPasswordError
from app.domain.identity.repositories import UserRepository
from app.domain.identity.value_objects import Email, Username

# 轮数调到下限：本文件验的是「写进去了什么」，bcrypt 的强度不是这里的关注点
_ROUNDS = 4
_OLD_PASSWORD = "Old-secret-1"
_NEW_PASSWORD = "New-secret-2"


# ──────────────────────────── 测试替身 ────────────────────────────


class _FakeUsers(UserRepository):
    """内存版 UserRepository。

    只实现本文件真正用到的方法；其余显式抛 ``NotImplementedError``，
    这样「用例偷偷多查了一次库」会当场炸掉，而不是静默拿到 ``None``。
    """

    def __init__(self, users: Iterable[User] = ()) -> None:
        self._store: dict[UUID, User] = {}
        for user in users:
            # User.id 是 Optional（「刚 new 出来还没落库」的阶段确实为空），
            # 但走到用例里的实体必然来自仓储，取不到 id 说明测试自己装配错了
            assert user.id is not None
            self._store[user.id] = user
        self.updated: list[User] = []

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._store.get(user_id)

    async def get_by_ids(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        # 与真实仓储同一契约：缺失的 id 不出现在返回值里
        return {uid: self._store[uid] for uid in user_ids if uid in self._store}

    async def update(self, user: User) -> User:
        self.updated.append(user)
        return user

    async def add(self, user: User) -> User:
        raise NotImplementedError

    async def get_by_email(self, email: Email) -> User | None:
        raise NotImplementedError

    async def get_by_username(self, username: Username) -> User | None:
        raise NotImplementedError

    async def list_paged(self, offset: int, limit: int) -> list[User]:
        raise NotImplementedError

    async def count(self) -> int:
        raise NotImplementedError


class _StubAccess(AccessRepository):
    """只提供「读角色 / 读权限」的仓储替身。"""

    def __init__(
        self,
        roles: Sequence[Role] = (),
        permissions: Collection[str] = (),
    ) -> None:
        self._roles = list(roles)
        self._permissions = set(permissions)

    async def get_roles_by_user(self, user_id: UUID) -> list[Role]:
        return list(self._roles)

    async def get_permission_codes(self, user_id: UUID) -> set[str]:
        return set(self._permissions)

    async def list_roles(self) -> list[Role]:
        raise NotImplementedError

    async def list_permissions(self) -> list[Permission]:
        raise NotImplementedError

    async def get_role_by_code(self, code: str) -> Role | None:
        raise NotImplementedError

    async def get_role_codes_by_users(self, user_ids: Collection[UUID]) -> dict[UUID, set[str]]:
        raise NotImplementedError

    async def assign_roles(self, user_id: UUID, role_codes: Collection[str]) -> list[Role]:
        raise NotImplementedError

    async def sync_catalog(
        self, role_specs: Sequence[RoleSpec], permission_specs: Sequence[PermissionSpec]
    ) -> dict[str, int]:
        raise NotImplementedError


def _user(password: str = _OLD_PASSWORD) -> User:
    return User.register(
        email=Email(f"{uuid4().hex[:10]}@example.com"),
        username=Username(f"user{uuid4().hex[:10]}"),
        password_hash=hash_password(password, rounds=_ROUNDS),
    )


def _id(user: User) -> UUID:
    """取实体主键。

    ``User.id`` 是 ``UUID | None``，直接往用例里传会让类型检查器报错。
    用断言收窄而不是 ``# type: ignore``：万一哪天 ``register`` 不再生成 id，
    测试会立刻以明确的方式失败，而不是被 ignore 注释悄悄放行。
    """
    assert user.id is not None
    return user.id


# ──────────────────────────── 权限点声明 ────────────────────────────


def _role_spec(code: str) -> RoleSpec:
    return next(spec for spec in ROLE_SPECS if spec.code == code)


def test_reset_password_permission_is_declared() -> None:
    """``user:reset_password`` 必须同时出现在权限点表和 admin 的角色里。

    两个地方漏任何一个，端点都只会有两种下场：
        漏在权限点表 → 种子里没有这条记录，``sync_catalog`` 建不出角色-权限关联，
                       连 admin 都拿不到它，接口永远 403；
        漏在 admin 角色里 → 权限点存在但没人拥有，同样永远 403。
    这两种「永远不会成功」的配置错误靠人工点页面排查非常费时，用一条断言钉死。
    """
    declared = {spec.code for spec in PERMISSION_SPECS}
    assert PermissionCode.USER_RESET_PASSWORD in declared
    assert PermissionCode.USER_RESET_PASSWORD in _role_spec(RoleCode.ADMIN).permissions


def test_reset_password_permission_is_not_granted_to_author_or_reader() -> None:
    """重置他人密码是管理员专属能力，不能顺手给 author / reader。

    它比「看用户列表」危险得多：拿到它就能直接接管任意账号。
    author / reader 是**内容角色**，与用户管理无关，没有理由持有。
    """
    for code in (RoleCode.AUTHOR, RoleCode.READER):
        assert PermissionCode.USER_RESET_PASSWORD not in _role_spec(code).permissions


# ──────────────────────────── 重置密码 ────────────────────────────


async def test_reset_replaces_the_hash_with_the_new_password() -> None:
    """核心契约：重置后新密码可登录、旧密码失效。

    用真 bcrypt 的 ``verify_password`` 反查，而不是断言「哈希字符串变了」：
    后者对「拿旧哈希原样写回去但顺手改了个字符」这种错误实现同样是绿的。
    """
    user = _user()
    users = _FakeUsers([user])
    use_case = ResetUserPasswordUseCase(users, bcrypt_rounds=_ROUNDS)

    await use_case.execute(_id(user), ResetPasswordCommand(new_password=_NEW_PASSWORD))

    assert verify_password(_NEW_PASSWORD, user.password_hash)
    assert not verify_password(_OLD_PASSWORD, user.password_hash)


async def test_reset_persists_the_change_through_the_repository() -> None:
    """实体改了不等于库改了。

    用例必须显式 ``update``——只在内存里改 ``password_hash``
    是本层最容易犯的错，单测里对象看着是新的，真库那条记录一动没动。
    """
    user = _user()
    users = _FakeUsers([user])
    use_case = ResetUserPasswordUseCase(users, bcrypt_rounds=_ROUNDS)

    await use_case.execute(_id(user), ResetPasswordCommand(new_password=_NEW_PASSWORD))

    assert [u.id for u in users.updated] == [user.id]


async def test_reset_returns_user_without_any_password_field() -> None:
    """出参是不含密码字段的用户视图。"""
    user = _user()
    use_case = ResetUserPasswordUseCase(_FakeUsers([user]), bcrypt_rounds=_ROUNDS)

    result = await use_case.execute(_id(user), ResetPasswordCommand(new_password=_NEW_PASSWORD))

    assert result.id == user.id
    assert not hasattr(result, "password_hash")


async def test_reset_does_not_require_the_old_password() -> None:
    """目标用户的旧密码对调用者而言是**未知**的，用例不该试图去知道。

    这条测试模拟的正是唯一有意义的场景：用户忘记密码来求助。
    如果将来有人「顺手」加回校验旧密码的逻辑，这里会红。
    """
    user = _user()
    # 用一串绝对不可能等于旧密码的值，且重置命令里根本没有 old_password 这个字段
    command = ResetPasswordCommand(new_password=_NEW_PASSWORD)
    assert not hasattr(command, "old_password")

    await ResetUserPasswordUseCase(_FakeUsers([user]), bcrypt_rounds=_ROUNDS).execute(
        _id(user),
        command,
    )

    assert verify_password(_NEW_PASSWORD, user.password_hash)


async def test_reset_on_unknown_user_raises_not_found() -> None:
    """目标不存在 → 领域异常 ``UserNotFoundError``（表现层映射成 404）。

    刻意**不**静默成功：管理页点了「重置」却什么都没发生、
    还弹一句「成功」，是最难排查的一类体验问题。
    """
    use_case = ResetUserPasswordUseCase(_FakeUsers(), bcrypt_rounds=_ROUNDS)

    with pytest.raises(UserNotFoundError):
        await use_case.execute(uuid4(), ResetPasswordCommand(new_password=_NEW_PASSWORD))


async def test_reset_rejects_password_beyond_bcrypt_limit() -> None:
    """超过 bcrypt 72 字节上限的密码要变成领域异常，而不是 500。

    ``hash_password`` 内部抛 ``ValueError``；用例把它收敛成 ``WeakPasswordError``。
    不收敛的话这里会冒到全局兜底处理器，前端收到 500 + 「服务器内部错误」，
    真正的原因（密码太长）被埋掉。
    """
    user = _user()
    use_case = ResetUserPasswordUseCase(_FakeUsers([user]), bcrypt_rounds=_ROUNDS)
    # 24 个汉字 = 72 字节刚好越界（每个汉字 3 字节），字符数却只有 24
    too_long = "密" * 30

    with pytest.raises(WeakPasswordError):
        await use_case.execute(_id(user), ResetPasswordCommand(new_password=too_long))


async def test_reset_on_another_users_id_leaves_only_that_user_changed() -> None:
    """重置是「针对某个 id」的精确操作，不能波及别人。

    两人共用同一段密码时特别容易看出问题：只要实现里出现
    「按密码查用户」之类的写法，另一个人的哈希也会被改掉。
    """
    target = _user("Shared-secret")
    bystander = _user("Shared-secret")
    users = _FakeUsers([target, bystander])
    use_case = ResetUserPasswordUseCase(users, bcrypt_rounds=_ROUNDS)

    await use_case.execute(_id(target), ResetPasswordCommand(new_password=_NEW_PASSWORD))

    assert verify_password(_NEW_PASSWORD, target.password_hash)
    assert verify_password("Shared-secret", bystander.password_hash)
    assert users.updated == [target]


# ──────────────────────────── 我的权限快照 ────────────────────────────


async def test_my_access_returns_role_codes_and_permission_codes() -> None:
    """快照同时给出角色码（给人看）与权限码（给前端判断）。"""
    user_id = uuid4()
    roles = [
        Role(id=uuid4(), code=RoleCode.AUTHOR, name="作者", description=None),
        Role(id=uuid4(), code=RoleCode.READER, name="读者", description=None),
    ]
    access = _StubAccess(roles, {PermissionCode.POST_CREATE, PermissionCode.COMMENT_CREATE})

    summary = await GetMyAccessUseCase(access).execute(user_id)

    assert isinstance(summary, AccessSummaryDTO)
    assert summary.role_codes == frozenset({RoleCode.AUTHOR, RoleCode.READER})
    assert summary.permission_codes == frozenset(
        {PermissionCode.POST_CREATE, PermissionCode.COMMENT_CREATE}
    )


async def test_my_access_is_empty_for_a_user_without_roles() -> None:
    """没有任何角色的用户拿到两个空集合，而不是 ``None``。

    返回 ``None`` 会让前端到处写判空；空集合天然可迭代、可 ``includes``，
    调用方少一层分支。
    """
    summary = await GetMyAccessUseCase(_StubAccess()).execute(uuid4())

    assert summary.role_codes == frozenset()
    assert summary.permission_codes == frozenset()
