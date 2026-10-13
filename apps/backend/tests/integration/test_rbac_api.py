"""RBAC 接口的集成测试：真库 + 真 ASGI 应用。

权限相关的 bug 几乎都出在**接线**上而不是**规则**上：
守卫挂错端点、依赖装配漏了仓储、撤权后 token 还能用……
这些只有「请求真的走完整条链路」才暴露得出来。规则本身（矩阵、默认角色）
由 ``tests/unit/test_access.py`` 用纯内存对象验，这里不重复。

种子数据从哪来：见 ``tests/integration/conftest.py``——
``ASGITransport`` 不跑 lifespan，角色表不会自动填，得由夹具显式灌进测试事务。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import PermissionCode, RoleCode
from app.infrastructure.persistence.repositories.access import SqlAccessRepository

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
MY_ACCESS_URL = "/api/v1/auth/me/access"
USERS_URL = "/api/v1/users"
ROLES_URL = "/api/v1/roles"
PERMISSIONS_URL = "/api/v1/roles/permissions"
PASSWORD = "Sup3r-secret"
NEW_PASSWORD = "Rotated-secret"

# 与 domain 里的错误码常量一一对应。这里写死数字是有意的：
# 契约变了两边一起变，测试才拦得住「不经意改掉对外错误码」这种破坏性变更。
PERMISSION_DENIED = 40320
USER_NOT_FOUND = 40410
TOKEN_INVALID = 40111
INVALID_CREDENTIALS = 40110
ROLE_NOT_FOUND = 40420


# ──────────────────────────── 辅助 ────────────────────────────


def _payload(**overrides: object) -> dict[str, object]:
    """造一份唯一的注册入参。

    邮箱 / 用户名带随机后缀：测试库虽然每个用例整体回滚，
    但唯一索引是库级的——万一将来改成「不回滚」的策略，
    随机后缀能让这些用例依旧互不干扰。
    """
    suffix = uuid4().hex[:10]
    payload: dict[str, object] = {
        "email": f"user{suffix}@example.com",
        "username": f"user{suffix}",
        "password": PASSWORD,
        "display_name": None,
    }
    payload.update(overrides)
    return payload


async def _register(client: AsyncClient, **overrides: object) -> tuple[str, str]:
    """注册一个用户，返回 ``(user_id, email)``。"""
    payload = _payload(**overrides)
    response = await client.post(REGISTER_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"], str(payload["email"])


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    """登录并返回可直接塞进请求的认证头。

    ``password`` 可覆盖：改密 / 重置那几组用例需要「先确认新密码能登录」，
    默认值让常规调用点保持一行。
    """
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["data"]["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _actor(
    client: AsyncClient,
    db_session: AsyncSession,
    *role_codes: str,
) -> tuple[str, dict[str, str]]:
    """造一个拥有指定角色的「已登录用户」。

    角色是**直接写库**授予的，不走接口：
        ``PUT /users/{id}/roles`` 本身就需要 ``user:assign_roles``，
        用它来造测试前置数据会陷入「要管理员才能造管理员」的循环。
        直接操作仓储才能把「造数据」和「验证接口」两件事分开。
    """
    user_id, email = await _register(client)
    if role_codes:
        await SqlAccessRepository(db_session).assign_roles(UUID(user_id), set(role_codes))
    return user_id, await _login(client, email)


# ──────────────────────────── 认证 vs 授权 ────────────────────────────


async def test_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    """没带 token → 401，而不是 403。

    401 与 403 混用是很常见的退化：前端拿到 403 会以为「我登录了但权限不够」，
    于是给用户提示「请联系管理员开通权限」，而实际上他该做的是重新登录。
    """
    response = await client.get(USERS_URL)

    assert response.status_code == 401
    assert response.json()["code"] == TOKEN_INVALID


async def test_reader_cannot_list_users(client: AsyncClient, db_session: AsyncSession) -> None:
    """reader 访问用户列表 → 403，且响应里带上缺的是哪个权限。

    把权限码放进 ``data.permission`` 是为了让前端能提示「需要 user:list 权限」，
    而不必把后端的权限矩阵抄一份到前端——抄过去的那一刻就开始漂移了。
    """
    _, headers = await _actor(client, db_session, RoleCode.READER)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == PERMISSION_DENIED
    assert body["data"]["permission"] == PermissionCode.USER_LIST


async def test_user_without_any_role_is_denied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """一个角色都没有的用户同样被拒。

    这条是「默认拒绝」的体现：守卫不认「登录了就放行」，
    只认 user_roles 里真的有没有对应权限。
    """
    _, headers = await _actor(client, db_session)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == PERMISSION_DENIED


async def test_admin_can_list_users(client: AsyncClient, db_session: AsyncSession) -> None:
    """admin 能拿到用户列表，且数据里带上角色码。"""
    admin_id, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] >= 1

    by_id = {item["user"]["id"]: item for item in data["items"]}
    assert admin_id in by_id
    # role_codes 是集合语义，JSON 里是个数组、顺序不保证，所以比较集合而不是列表
    assert set(by_id[admin_id]["role_codes"]) == {RoleCode.ADMIN}


async def test_reader_can_still_read_roles(client: AsyncClient, db_session: AsyncSession) -> None:
    """reader 没有 ``role:list``，所以角色列表接口对他也是 403。

    特意用 reader（而不是「无角色用户」）来测：reader 是**有权限的**用户，
    最容易被误当成「权限够用」。它到底能做什么，应该只由矩阵决定。
    """
    _, headers = await _actor(client, db_session, RoleCode.READER)

    assert (await client.get(ROLES_URL, headers=headers)).status_code == 403
    assert (await client.get(PERMISSIONS_URL, headers=headers)).status_code == 403


async def test_admin_reads_role_and_permission_catalog(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """admin 能读到角色与权限点两份目录（前端权限矩阵的两根坐标轴）。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    roles = await client.get(ROLES_URL, headers=headers)
    permissions = await client.get(PERMISSIONS_URL, headers=headers)

    assert roles.status_code == 200, roles.text
    assert permissions.status_code == 200, permissions.text

    role_codes = {item["code"] for item in roles.json()["data"]}
    assert role_codes == {RoleCode.ADMIN, RoleCode.AUTHOR, RoleCode.READER}

    admin = next(item for item in roles.json()["data"] if item["code"] == RoleCode.ADMIN)
    permission_codes = {item["code"] for item in permissions.json()["data"]}
    assert set(admin["permission_codes"]) == permission_codes


# ──────────────────────────── 分配角色 ────────────────────────────


async def test_register_defaults_to_reader(client: AsyncClient, db_session: AsyncSession) -> None:
    """注册即得 reader，不留「有账号但零权限」的空档。"""
    user_id, _ = await _register(client)

    granted = await SqlAccessRepository(db_session).get_role_codes_by_users([UUID(user_id)])

    assert granted[UUID(user_id)] == {RoleCode.READER}


async def test_assign_roles_replaces_instead_of_appending(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """分配角色是**替换**语义：把 reader 换成 author 之后不该还留着 reader。

    如果哪天有人把它改成「追加」，这个用例会红——
    而线上表现为「降级降不掉」，用户永远保着之前的权限。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": [RoleCode.AUTHOR]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert {item["code"] for item in response.json()["data"]} == {RoleCode.AUTHOR}

    granted = await SqlAccessRepository(db_session).get_role_codes_by_users([UUID(target_id)])
    assert granted[UUID(target_id)] == {RoleCode.AUTHOR}


async def test_assign_roles_accepts_multiple_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """一个用户可以同时挂多个角色，权限取并集。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": [RoleCode.READER, RoleCode.AUTHOR]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert {item["code"] for item in response.json()["data"]} == {
        RoleCode.AUTHOR,
        RoleCode.READER,
    }


async def test_assign_empty_set_revokes_all_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """传空集合表示收回全部角色。

    空集合必须能和「没传这个字段」区分开，否则「收回权限」这件事就没有接口能表达了。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": []},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []

    granted = await SqlAccessRepository(db_session).get_role_codes_by_users([UUID(target_id)])
    assert granted[UUID(target_id)] == set()


async def test_revoked_permission_takes_effect_immediately(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """撤权之后，**同一个 token** 立刻不能再访问。

    这是「权限每次现查、不塞进 token」这条设计的核心收益。
    如果把权限写进 JWT，撤权要等 token 过期才生效——
    对管理接口来说，那段窗口期就是实打实的安全问题。
    """
    admin_id, admin_headers = await _actor(client, db_session, RoleCode.ADMIN)
    assert (await client.get(USERS_URL, headers=admin_headers)).status_code == 200

    # 另一个管理员把他降级成 reader（不能把自己降级，否则后面发请求的凭据也没了）
    _, other_headers = await _actor(client, db_session, RoleCode.ADMIN)
    downgrade = await client.put(
        f"{USERS_URL}/{admin_id}/roles",
        json={"role_codes": [RoleCode.READER]},
        headers=other_headers,
    )
    assert downgrade.status_code == 200, downgrade.text

    # token 没变，但权限已没了
    assert (await client.get(USERS_URL, headers=admin_headers)).status_code == 403


async def test_assign_roles_to_unknown_user_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """给不存在的用户分配角色 → 404。

    不能静默成功：``user_roles`` 表没有指向 ``users`` 的外键约束失败时，
    悄悄插进去的行会变成永远读不出来的孤儿数据。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.put(
        f"{USERS_URL}/{uuid4()}/roles",
        json={"role_codes": [RoleCode.READER]},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == USER_NOT_FOUND


async def test_assign_unknown_role_code_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """角色码不存在 → 404，且**整体失败**，不做部分写入。

    混着一个合法编码一起提交是最好的探针：
    如果实现是「能认出来的先写」，这里就会变成 200 + 只写入 reader，
    而调用方以为两个都成功了。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": [RoleCode.READER, "no-such-role"]},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == ROLE_NOT_FOUND

    granted = await SqlAccessRepository(db_session).get_role_codes_by_users([UUID(target_id)])
    assert granted[UUID(target_id)] == {RoleCode.READER}, "失败的请求不该动到已有角色"


async def test_assign_roles_requires_assign_permission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """reader 没有 ``user:assign_roles``，所以→ 403。

    用户列表（``user:list``）与分配角色（``user:assign_roles``）是两个权限：
    只读管理界面和改权限必须能分开授，否则「让运营看看用户列表」就成了「让他能改所有人权限」。
    """
    _, headers = await _actor(client, db_session, RoleCode.READER)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": [RoleCode.ADMIN]},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["data"]["permission"] == PermissionCode.USER_ASSIGN_ROLES


async def test_list_user_roles(client: AsyncClient, db_session: AsyncSession) -> None:
    """查看某用户的角色（含权限码）。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.get(f"{USERS_URL}/{target_id}/roles", headers=headers)

    assert response.status_code == 200, response.text
    assert {item["code"] for item in response.json()["data"]} == {RoleCode.READER}


async def test_list_roles_of_unknown_user_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """查不存在用户的角色 → 404，而不是空列表。

    空列表会被前端理解成「这个人没有任何角色」，画出一个空态；
    而真相是「这个人根本不存在」，前端该做的是跳回列表页。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.get(f"{USERS_URL}/{uuid4()}/roles", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == USER_NOT_FOUND


@pytest.mark.parametrize("role_codes", [["reader", "reader"], ["reader"]])
async def test_duplicate_role_codes_are_harmless(
    client: AsyncClient, db_session: AsyncSession, role_codes: list[str]
) -> None:
    """重复提交同一个角色码不会报错，也不会插出两行绑定关系。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": role_codes},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert {item["code"] for item in response.json()["data"]} == {RoleCode.READER}


# ──────────────────────────── 分页 ────────────────────────────


async def test_pagination_is_clamped_not_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """越界的分页参数被收敛而不是报 422，且回传收敛后的值。

    回传 ``limit`` 是这个接口的契约一部分：客户端用 limit 算总页数，
    不告诉它实际用了多少，它就会按自己传的 1000 去算，页数算少一大截。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.get(USERS_URL, params={"offset": -5, "limit": 100000}, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["offset"] == 0
    assert data["limit"] == 100
    assert len(data["items"]) <= 100


async def test_pagination_offset_skips_rows(client: AsyncClient, db_session: AsyncSession) -> None:
    """offset 真的会跳过行，且两页之间不重不漏。

    这条依赖仓储里 ``ORDER BY created_at DESC, id DESC`` 那个次序键：
    只按 created_at 排序时，同一批插入的行时间戳可能完全相同，
    PG 不保证稳定顺序，表现为「翻页时某行出现两次、另一行永远看不到」。
    测试里连续注册的用户恰好是这种「同一批插入」的情形。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    await _register(client)
    await _register(client)

    first = await client.get(USERS_URL, params={"offset": 0, "limit": 2}, headers=headers)
    second = await client.get(USERS_URL, params={"offset": 2, "limit": 2}, headers=headers)

    assert first.status_code == 200 and second.status_code == 200

    first_ids = [item["user"]["id"] for item in first.json()["data"]["items"]]
    second_ids = [item["user"]["id"] for item in second.json()["data"]["items"]]

    assert len(first_ids) == 2
    assert not set(first_ids) & set(second_ids), "两页之间出现了重复行"


async def test_page_reflects_total_ignoring_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``total`` 是全量总数，不受 limit 影响。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    await _register(client)

    response = await client.get(USERS_URL, params={"offset": 0, "limit": 1}, headers=headers)

    data = response.json()["data"]
    assert len(data["items"]) == 1
    assert data["total"] >= 2


# ──────────────────────────── 入参校验 ────────────────────────────


async def test_invalid_user_id_is_rejected_before_the_use_case(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """路径参数不是 UUID → 400 + code 40000，由 FastAPI 拦下，用例不必写这段判断。

    注意是 400 不是 422：本项目的全局处理器把 FastAPI 的 ``RequestValidationError``
    统一翻译成了 ``ValidationError``（40000 / 400），
    好让「参数不合法」在前后端只有一种表达方式。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.get(f"{USERS_URL}/not-a-uuid/roles", headers=headers)

    assert response.status_code == 400
    assert response.json()["code"] == 40000


async def test_too_many_role_codes_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """一次提交过多角色码 → 400 + code 40000。

    这是一个纯粹的资源保护：没有上限的话，请求体里塞十万个编码
    就会让服务端拿着它们逐条查库。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/roles",
        json={"role_codes": [f"role-{index}" for index in range(21)]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40000


# ──────────────────────────── 我的权限快照 ────────────────────────────


async def test_my_access_lists_admin_permissions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """admin 的权限快照里必须包含全部三个管理权限点。

    特意点名 ``USER_RESET_PASSWORD``：它是本次新加的常量，
    最容易出的问题是「常量加了、``PERMISSION_SPECS`` 忘了加」——
    那样种子里根本建不出这条权限，连 admin 都拿不到，接口永远 403。
    单测只能验证常量表的自洽，只有连真库跑 ``sync_catalog``
    才能证明这条权限真的落到 ``role_permissions`` 里了。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.get(MY_ACCESS_URL, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert set(data["role_codes"]) == {RoleCode.ADMIN}
    assert {
        PermissionCode.USER_LIST,
        PermissionCode.USER_ASSIGN_ROLES,
        PermissionCode.USER_RESET_PASSWORD,
        PermissionCode.ROLE_LIST,
    } <= set(data["permission_codes"])


async def test_my_access_for_reader_excludes_management_permissions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """reader 的快照里有内容权限、没有管理权限。

    前端就是靠这个差别决定「用户管理」入口显不显示的：
    所以既要确认它有自己该有的，也要确认它没有不该有的——
    只验前者的话，一个「把全部权限发给所有人」的实现照样能过。
    """
    _, headers = await _actor(client, db_session, RoleCode.READER)

    data = (await client.get(MY_ACCESS_URL, headers=headers)).json()["data"]

    assert PermissionCode.COMMENT_CREATE in data["permission_codes"]
    assert PermissionCode.USER_LIST not in data["permission_codes"]
    assert PermissionCode.USER_RESET_PASSWORD not in data["permission_codes"]


async def test_my_access_requires_authentication(client: AsyncClient) -> None:
    """没带 token → 401。它是「我是谁」的接口，匿名访问没有意义。"""
    response = await client.get(MY_ACCESS_URL)

    assert response.status_code == 401
    assert response.json()["code"] == TOKEN_INVALID


async def test_role_catalog_exposes_the_reset_permission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """角色目录里 admin 的 ``permission_codes`` 含 ``user:reset_password``。

    与 ``test_my_access_lists_admin_permissions`` 是同一条链路的两个观察点：
    那边看「我有什么」，这边看「目录说 admin 有什么」。
    两者都过，才能确定种子的 ``role_permissions`` 关联是真的建起来了，
    而不是靠 ``get_permission_codes`` 的某条兜底路径偶然拼出来的。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    roles = (await client.get(ROLES_URL, headers=headers)).json()["data"]
    admin = next(item for item in roles if item["code"] == RoleCode.ADMIN)

    assert PermissionCode.USER_RESET_PASSWORD in admin["permission_codes"]


# ──────────────────────────── 管理员重置密码 ────────────────────────────


async def test_admin_resets_a_users_password(client: AsyncClient, db_session: AsyncSession) -> None:
    """完整闭环：管理员改密 → 新密码能登录、旧密码登不上。

    这是整个功能唯一有意义的验收标准。只断言「接口返回 200」是没用的：
    一个把哈希写错、或者压根没调 ``update`` 的实现，同样返回 200。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, target_email = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    # 新密码可用（能拿到 token 就说明 bcrypt 比对通过了）
    await _login(client, target_email, NEW_PASSWORD)

    stale = await client.post(LOGIN_URL, json={"email": target_email, "password": PASSWORD})
    assert stale.status_code == 401
    assert stale.json()["code"] == INVALID_CREDENTIALS


async def test_reset_response_never_contains_password_material(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """响应里不能出现密码哈希（哪怕是哈希）。

    管理页会把这个对象直接塞进 React state，一旦带上 ``password_hash``，
    它就进浏览器内存、进 devtools、进任何日志上报。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    payload = response.json()["data"]
    assert "password_hash" not in payload
    assert "password" not in payload
    assert payload["id"] == target_id


@pytest.mark.parametrize("role_code", [RoleCode.READER, RoleCode.AUTHOR])
async def test_reset_password_requires_the_dedicated_permission(
    client: AsyncClient, db_session: AsyncSession, role_code: str
) -> None:
    """reader / author 都拿不到重置能力 → 403。

    author 一起测是有意的：它是「权限比较多」的内容角色，
    最容易被顺手加上管理权限。拿到 ``user:reset_password``
    就等于能接管任意账号（含 admin），比 ``user:list`` 危险得多，
    因此必须是独立权限点，而不是搭在 ``user:list`` 上。
    """
    _, headers = await _actor(client, db_session, role_code)
    target_id, target_email = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["data"]["permission"] == PermissionCode.USER_RESET_PASSWORD

    # 被拒绝的请求不能有任何副作用：目标用户仍能用原密码登录
    await _login(client, target_email, PASSWORD)


async def test_reset_password_of_unknown_user_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """目标不存在 → 404，而不是静默的成功。"""
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)

    response = await client.put(
        f"{USERS_URL}/{uuid4()}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == USER_NOT_FOUND


async def test_reset_password_rejects_too_short_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """新密码短于 8 位 → 400 + code 40000（不是 422，见本文件顶部关于错误码的说明）。

    前端虽然也拦了一道，但接口不能依赖前端：直接构造请求就能绕过去，
    而一个 3 位密码的账号会被离线爆破瞬间拿下。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)

    response = await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": "short"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40000


async def test_reset_password_does_not_touch_other_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """两个人用同一个密码时，重置其中一个不影响另一个。

    这条专抓「按密码查用户」这类实现错误：
    它们在本项目里不该存在（重置只按 id 定位），但一旦有人图省事这么写，
    登录校验会开始出现「莫名其妙的账号串号」，排查代价极高。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, _ = await _register(client)
    _, bystander_email = await _register(client)

    await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    await _login(client, bystander_email, PASSWORD)


async def test_reset_password_leaves_existing_tokens_valid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ 已知边界：重置**不会**把目标用户已登录的会话踢下线。

    这条断言记录的是当前设计的一个**取舍**，不是「正确行为」：
    本项目的 access token 是无状态 JWT，服务端不留会话，
    所以「重置即踢人」需要一张吊销名单（或把密码哈希掺进签名）。
    真要做，改动量不小，因此这版明确不做——但要把它钉在测试里：

        ① 前端的重置弹窗必须写明「该用户已登录的设备仍会保持登录，直到令牌过期」，
           否则管理员会以为重置等于踢人，从而把重置当成封禁手段来用；
        ② 将来真的实现了吊销，这条测试会失败，正好提醒作者
           连带更新前端那句提示文案。

    如果哪天这条红了，请不要「顺手改绿」——先确认前端文案一起改了。
    """
    _, headers = await _actor(client, db_session, RoleCode.ADMIN)
    target_id, target_email = await _register(client)
    victim_headers = await _login(client, target_email)

    await client.put(
        f"{USERS_URL}/{target_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    # 旧 token 依旧有效——这正是「未实现吊销」的证据
    response = await client.get("/api/v1/auth/me", headers=victim_headers)
    assert response.status_code == 200

    # 而用旧密码重新登录已经不行了
    stale = await client.post(LOGIN_URL, json={"email": target_email, "password": PASSWORD})
    assert stale.status_code == 401
    assert stale.json()["code"] == INVALID_CREDENTIALS


async def test_admin_can_reset_their_own_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """管理员也能重置自己（走的是同一条路径，不额外禁止）。

    这么设计是因为「禁止」没有实际收益：他本来就有这个权限，
    真禁掉只会多出一次「点不动、也没提示原因」的交互。
    这里把它固化成契约，免得将来有人为了「防误操作」加上禁止、
    却忘了前端也要一起改。
    """
    admin_id, admin_headers = await _actor(client, db_session, RoleCode.ADMIN)
    # 拿到管理员的邮箱：列表接口里就有
    users = (await client.get(USERS_URL, headers=admin_headers)).json()["data"]["items"]
    admin_email = next(item["user"]["email"] for item in users if item["user"]["id"] == admin_id)

    response = await client.put(
        f"{USERS_URL}/{admin_id}/password",
        json={"new_password": NEW_PASSWORD},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    await _login(client, admin_email, NEW_PASSWORD)
