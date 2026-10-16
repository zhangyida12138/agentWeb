"""标签接口的集成测试：真库 + 真 ASGI 应用。

为什么这一层不可省：
    标签上下文的规则本身（slug 派生、归属判定、状态机）由 ``tests/unit/test_tag.py``
    验，这里不重复。这一层守的是**只有真库才成立的三件事**：

    ① ``post_count`` 的口径。它是 JOIN + GROUP BY 算出来的，
       而「只数已发布、只数未删除」这两个条件写在 **ON** 而不是 WHERE——
       写错位置外连接会退化成内连接，于是「只挂着草稿的标签」直接消失。
       内存里测不出来，因为内存里没有 SQL。
    ② ``total`` 与 ``items`` 来自两条不同的语句（``count_tags`` 独立计算）。
       数错时前端会看到「共 10 条」但翻到第 2 页是空白。
    ③ 唯一索引不认 ``status``：软删除的标签仍然占着名字与 slug。
       这条契约只存在于数据库里，代码里一个字都看不到。

本文件重点守四条产品决策：
    ① 未登录能读标签（标签是公共词汇表），但一个字都改不了；
    ② 写路径分级：``POST`` / ``PATCH status`` / ``DELETE`` 要 ``tag:manage``，
       ``PUT`` 只要「是自己的」——作者改自己的标签不必去申请管理员权限；
    ③ 默认列表只看 ``normal``；下架/删除的标签要显式传 ``?status=`` 才看得到；
    ④ 软删除 = 对写路径不存在（404），但占着的名字与 slug 不会释放（409）。

前置数据从哪来：见 ``tests/integration/conftest.py``——``ASGITransport``
不跑 lifespan，角色 / 权限表不会自动填，得由 autouse 夹具灌进测试事务。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import RoleCode
from app.domain.blog.value_objects import TAG_NAME_MAX_LEN
from app.domain.tag.value_objects import TAG_DESCRIPTION_MAX_LEN
from app.infrastructure.persistence.repositories.access import SqlAccessRepository

TAGS_URL = "/api/v1/tags"
POSTS_URL = "/api/v1/posts"
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
PASSWORD = "Sup3r-secret"

# 与 domain 里的错误码一一对应，写死数字以锁住对外契约
VALIDATION_FAILED = 40000
INVALID_TAG_NAME = 40036
TAG_OPERATION_NOT_ALLOWED = 40051
TOKEN_INVALID = 40110
PERMISSION_DENIED = 40320
TAG_OPERATION_FORBIDDEN = 40350
TAG_NOT_FOUND = 40450
TAG_ALREADY_EXISTS = 40950


# ──────────────────────────── 辅助 ────────────────────────────
# 这里刻意不去 import test_posts_api 里的同名辅助：
# 测试之间共享工具会形成隐式耦合——改一个辅助函数就可能让另一个文件的
# 断言语境变掉。几行重复换来「每个文件能独立读懂」，值得。


async def _actor(
    client: AsyncClient,
    db_session: AsyncSession,
    *role_codes: str,
) -> tuple[str, dict[str, str]]:
    """造一个拥有指定角色的已登录用户，返回 ``(user_id, headers)``。

    角色直接写库、不走接口：``PUT /users/{id}/roles`` 需要 ``user:assign_roles``，
    用它造前置数据会陷入「要管理员才能造管理员」的循环。
    """
    suffix = uuid4().hex[:10]
    email = f"tag{suffix}@example.com"
    response = await client.post(
        REGISTER_URL,
        json={
            "email": email,
            "username": f"tag{suffix}",
            "password": PASSWORD,
            "display_name": None,
        },
    )
    assert response.status_code == 201, response.text
    user_id = response.json()["data"]["id"]

    if role_codes:
        await SqlAccessRepository(db_session).assign_roles(UUID(user_id), set(role_codes))

    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.json()["data"]["token"]["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


def _base() -> str:
    """本次用例专用的名字前缀。

    断言一律靠 ``?keyword=`` 把范围收窄到自己造的数据上——
    这样即使开发库里原本就有别人的标签，用例之间也不会互相干扰，
    而且不需要清库、不依赖执行顺序。
    """
    return f"zt{uuid4().hex[:8]}"


async def _create_tag(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    **extra: object,
) -> dict[str, object]:
    """建标签（调用方必须持有 ``tag:manage``），返回响应里的 ``data``。"""
    response = await client.post(TAGS_URL, json={"name": name, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _search(
    client: AsyncClient,
    keyword: str,
    **params: object,
) -> dict[str, object]:
    """按关键词搜标签，返回响应里的 ``data``（``items`` / ``total`` / ...）。"""
    response = await client.get(TAGS_URL, params={"keyword": keyword, **params})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _names(client: AsyncClient, keyword: str, **params: object) -> list[str]:
    """搜标签并只取名字列表，断言读起来更接近产品语言。"""
    page = await _search(client, keyword, **params)
    return [item["name"] for item in page["items"]]  # type: ignore[union-attr]


async def _create_post(
    client: AsyncClient,
    headers: dict[str, str],
    tag_name: str,
    *,
    published: bool,
) -> str:
    """用给定的标签建一篇文章，返回它的 id；``published`` 决定是否立即发布。"""
    response = await client.post(
        POSTS_URL,
        json={
            "title": f"标签用例 {tag_name}",
            "content": "# 正文\n\n内容",
            "tag_names": [tag_name],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    post_id = str(response.json()["data"]["id"])

    if published:
        publish = await client.post(f"{POSTS_URL}/{post_id}/publish", headers=headers)
        assert publish.status_code == 200, publish.text
    return post_id


async def _admin(client: AsyncClient, db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    return await _actor(client, db_session, RoleCode.ADMIN)


async def _call_action(
    client: AsyncClient,
    method: str,
    url: str,
    name: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """按 method 发一个管理动作，供权限参数化用例复用。

    之所以要这层小封装：httpx 的 ``delete()`` **不接受** json 参数
    （它的签名里没有 body），三个动作写成一个 ``getattr(client, method)(... json=...)``
    会在 delete 那组用例上直接抛 TypeError——而那是测试自己的 bug，
    看起来却像接口挂了。
    """
    if method == "delete":
        return await client.delete(url, headers=headers)
    if method == "patch":
        return await client.patch(url, json={"status": "normal"}, headers=headers)
    return await client.post(url, json={"name": name}, headers=headers)


# ──────────────────────────── 公开读取 ────────────────────────────


async def test_list_tags_needs_no_login(client: AsyncClient, db_session: AsyncSession) -> None:
    """未登录也能拿到标签列表——标签是公共词汇表，看不到就没法用。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, f"{base}-python")

    page = await _search(client, base)

    assert [item["name"] for item in page["items"]] == [f"{base}-python"]  # type: ignore[union-attr]


async def test_page_metadata_counts_tags_not_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``total`` 数的是**标签数**，不是「标签 × 文章」的行数。

    两个标签一共被 3 篇已发布文章使用：正确结果是 ``total == 2``。
    如果把 ``list_tags`` 那条带 GROUP BY 的语句直接拿来 count，
    结果会是 3——前端据此算出的页数比实际多，最后一页永远是空的。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_post(client, author, f"{base}-a", published=True)
    await _create_post(client, author, f"{base}-a", published=True)
    await _create_post(client, author, f"{base}-b", published=True)

    page = await _search(client, base)

    assert page["total"] == 2
    assert len(page["items"]) == 2


async def test_pagination_is_sanitized_and_echoed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """越界的 offset/limit 被收敛而不是报 422，并把收敛后的值回填进响应。

    回填是关键：不回填的话客户端以为「我传了 1000」，
    于是自己算出的页数和后端实际给的页数对不上，又没人能看出是谁错了。
    """
    response = await client.get(TAGS_URL, params={"offset": -5, "limit": 1000})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["offset"] == 0
    assert data["limit"] == 100


async def test_keyword_search_ignores_case(client: AsyncClient, db_session: AsyncSession) -> None:
    """大写标签能被小写关键词搜到。

    用 LIKE 而不是 ILIKE 的话，用户搜「python」找不到「Python」——
    而他会得出「这个标签不存在」的结论，于是自己再建一个。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, f"{base}-Python")

    assert f"{base}-Python" in await _names(client, f"{base}-python")


async def test_overlong_name_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """超长名字在 Schema 那一层就被挡下，与领域的上限是同一个常量。"""
    _, admin = await _admin(client, db_session)

    response = await client.post(
        TAGS_URL, json={"name": "x" * (TAG_NAME_MAX_LEN + 1)}, headers=admin
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == VALIDATION_FAILED


async def test_keyword_search_treats_underscore_literally(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``_`` 在 LIKE 里是通配符，必须被转义。

    不转义时搜 ``zt1a2b3c4d_x`` 会连 ``zt1a2b3c4dax`` 一起返回——
    「看起来有结果，但都是错的」，这类 bug 用户根本描述不清楚。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    wanted = f"{base}_x"
    decoy = f"{base}zx"
    await _create_tag(client, admin, wanted)
    await _create_tag(client, admin, decoy)

    found = await _names(client, wanted)

    assert found == [wanted]


async def test_blank_keyword_is_treated_as_no_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """只有空白的 keyword 当作"没传"，而不是当作"匹配空字符串"。

    后者会返回 0 条，用户会以为标签表是空的。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, base)

    page = await _search(client, "   ")

    assert base in [item["name"] for item in page["items"]]  # type: ignore[union-attr]


async def test_default_list_hides_abnormal_and_deleted_tags(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """默认只返回 ``normal``：列表的默认结果应当是"用户可以拿去用的东西"。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    abnormal = await _create_tag(client, admin, f"{base}-abnormal")
    deleted = await _create_tag(client, admin, f"{base}-deleted")

    for tag, target in ((abnormal, "abnormal"), (deleted, "deleted")):
        response = await client.patch(
            f"{TAGS_URL}/{tag['id']}/status", json={"status": target}, headers=admin
        )
        assert response.status_code == 200, response.text

    assert await _names(client, base) == []

    assert await _names(client, base, status="abnormal") == [f"{base}-abnormal"]
    assert await _names(client, base, status="deleted") == [f"{base}-deleted"]


async def test_type_filter_separates_system_from_user_tags(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``?type=`` 能分辨平台内置标签与用户标签；不传时两类都返回。

    内置标签是给人用的入口，藏起来等于它不存在——所以默认不过滤 type。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, f"{base}-official", type="system")
    await _create_tag(client, admin, f"{base}-personal")

    assert set(await _names(client, base)) == {f"{base}-official", f"{base}-personal"}
    assert await _names(client, base, type="system") == [f"{base}-official"]
    assert await _names(client, base, type="user") == [f"{base}-personal"]


async def test_author_filter_narrows_to_one_creator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``?author_id=`` 只看某个作者创建的标签。"""
    admin_id, admin = await _admin(client, db_session)
    _, other = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_tag(client, admin, f"{base}-mine")
    await _create_post(client, other, f"{base}-theirs", published=True)

    assert await _names(client, base, author_id=admin_id) == [f"{base}-mine"]


async def test_unknown_status_is_rejected_instead_of_ignored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """拼错的状态明确报错，而不是被当成"不筛选"。

    静默忽略的后果是前端收到整份列表、看起来完全正常，
    直到有人发现「筛了已删除却还是全都在」。
    """
    response = await client.get(TAGS_URL, params={"status": "delteed"})

    assert response.status_code == 400, response.text
    assert response.json()["code"] == TAG_OPERATION_NOT_ALLOWED


# ──────────────────────────── post_count 的统计口径 ────────────────────────────


async def test_post_count_counts_only_published_posts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """草稿不计入 ``post_count``——标签页点进去看不到草稿，数字必须和它一致。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_post(client, author, base, published=True)
    await _create_post(client, author, base, published=False)

    page = await _search(client, base)

    assert page["items"][0]["post_count"] == 1  # type: ignore[index]


async def test_tag_used_only_by_drafts_still_appears(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """只被草稿引用的标签**仍然出现在列表里**（``post_count`` 为 0）。

    这条守的是一个极容易写错的位置：那两个统计条件必须写在 JOIN 的 ``ON`` 里。
    一旦挪到 ``WHERE``，外连接会退化成内连接，这个标签会直接从列表里**消失**——
    而「只有一个草稿用过的标签」正是作者回头要找的东西。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_post(client, author, base, published=False)

    page = await _search(client, base)

    assert [item["name"] for item in page["items"]] == [base]  # type: ignore[union-attr]
    assert page["items"][0]["post_count"] == 0  # type: ignore[index]


async def test_new_tag_starts_with_zero_post_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """没人用过的标签 ``post_count`` 是 0——「没人用的标签」是标签管理页最想知道的信息。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    created = await _create_tag(client, admin, base)

    assert created["post_count"] == 0

    page = await _search(client, base)
    assert page["items"][0]["post_count"] == 0  # type: ignore[index]


async def test_tags_are_ordered_by_usage(client: AsyncClient, db_session: AsyncSession) -> None:
    """用得多"在前——标签列表的实际用法是「挑一个现成的用」。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_post(client, author, f"{base}-rare", published=True)
    await _create_post(client, author, f"{base}-popular", published=True)
    await _create_post(client, author, f"{base}-popular", published=True)

    names = await _names(client, base)

    assert names == [f"{base}-popular", f"{base}-rare"]


# ──────────────────────────── 标签与文章的联动 ────────────────────────────


async def test_deleted_tag_disappears_from_posts_but_post_survives(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """管理员删掉标签后，文章上的这个标签不再展示，文章本身不受影响。

    软删除只作用于 ``tags`` 自己这一行——``post_tags`` 与 ``posts`` 都不动。
    这是「删除一个公共词汇」应有的破坏半径：谁都没义务回头改别人的文章。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _admin(client, db_session)
    base = _base()
    post_id = await _create_post(client, author, base, published=True)

    before = await client.get(f"{POSTS_URL}/{post_id}")
    assert before.json()["data"]["tags"] == [base]

    tag_id = (await _search(client, base))["items"][0]["id"]  # type: ignore[index]
    deleted = await client.delete(f"{TAGS_URL}/{tag_id}", headers=admin)
    assert deleted.status_code == 204, deleted.text

    after = await client.get(f"{POSTS_URL}/{post_id}")
    assert after.status_code == 200, after.text
    assert after.json()["data"]["tags"] == []


async def test_abnormal_tag_stays_on_posts_but_leaves_the_vocabulary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """下架是"停止新使用"，不是"抹掉历史"。

    已打标的文章仍然显示它——否则作者会以为自己的文章被改了。
    这两条读路径的差别是刻意的，所以必须各测一次。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _admin(client, db_session)
    base = _base()
    post_id = await _create_post(client, author, base, published=True)

    tag_id = (await _search(client, base))["items"][0]["id"]  # type: ignore[index]
    response = await client.patch(
        f"{TAGS_URL}/{tag_id}/status", json={"status": "abnormal"}, headers=admin
    )
    assert response.status_code == 200, response.text

    assert await _names(client, base) == []
    assert await _names(client, base, status="abnormal") == [base]

    post = await client.get(f"{POSTS_URL}/{post_id}")
    assert post.json()["data"]["tags"] == [base]


# ──────────────────────────── 写路径的授权分级 ────────────────────────────


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [("post", ""), ("patch", "/{tag_id}/status"), ("delete", "/{tag_id}")],
)
async def test_write_endpoints_require_login(
    client: AsyncClient, db_session: AsyncSession, method: str, path_suffix: str
) -> None:
    """未登录调三个管理动作 → 401，而不是 403。

    401 与 403 的分工：401 = 「你是谁我不知道」，403 = 「知道你是谁，但你不行」。
    混用会让前端无法决定「弹登录框」还是「弹权限提示」。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base)
    url = TAGS_URL + path_suffix.format(tag_id=tag["id"])

    response = await _call_action(client, method, url, f"{base}-x")

    assert response.status_code == 401, response.text
    assert response.json()["code"] == TOKEN_INVALID


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [("post", ""), ("patch", "/{tag_id}/status"), ("delete", "/{tag_id}")],
)
async def test_tag_manage_guard_rejects_authors(
    client: AsyncClient, db_session: AsyncSession, method: str, path_suffix: str
) -> None:
    """作者（有 ``post:*``）仍然不能建 / 下架 / 删标签 → 40320。

    作者与读者**刻意都不含** ``tag:manage``：维护公共词汇表不是写文章的一部分。
    这条断言如果失败，多半是有人为了"让前端别报错"把权限码顺手加进了作者角色。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base)
    url = TAGS_URL + path_suffix.format(tag_id=tag["id"])

    response = await _call_action(client, method, url, f"{base}-x", headers=author)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == PERMISSION_DENIED


async def test_author_can_edit_their_own_tag_without_extra_permission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """作者改自己的标签不需要 ``tag:manage``。

    PUT 的守卫只负责认证，归属由 ``Tag.ensure_manageable_by`` 判——
    因为「这是你自己建的」是一个**逐行**的规则，没有任何角色能表达它。
    硬要表达就只能给每个标签建一个角色。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    created = await _create_post(client, author, f"{base}a", published=True)
    tag = (await _search(client, f"{base}a"))["items"][0]  # type: ignore[index]

    response = await client.put(
        f"{TAGS_URL}/{tag['id']}",
        json={"name": f"{base}b", "description": "作者自己写的说明"},
        headers=author,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == f"{base}b"
    assert data["slug"] == f"{base}b"
    assert data["description"] == "作者自己写的说明"

    # 改名后文章的标签也跟着变：文章与标签之间只存 id 关联，名字是现读的
    post = await client.get(f"{POSTS_URL}/{created}")
    assert post.json()["data"]["tags"] == [f"{base}b"]


async def test_author_cannot_edit_someone_elses_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """别人的标签 → 40350（「不是你的」），而不是 40320（「你没这个能力」）。

    两个码对应两种完全不同的用户行为：去找管理员要权限 vs 去联系标签的作者。
    报错信息指错方向，用户就会做错事。
    """
    _, owner = await _actor(client, db_session, RoleCode.AUTHOR)
    _, intruder = await _actor(client, db_session, RoleCode.AUTHOR)
    base = _base()
    await _create_post(client, owner, base, published=True)
    tag = (await _search(client, base))["items"][0]  # type: ignore[index]

    response = await client.put(
        f"{TAGS_URL}/{tag['id']}", json={"name": f"{base}-hijacked"}, headers=intruder
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == TAG_OPERATION_FORBIDDEN


async def test_admin_can_edit_anyones_tag(client: AsyncClient, db_session: AsyncSession) -> None:
    """管理员凭 ``tag:manage`` 越权编辑——包括无主标签（作者已注销）。

    ``author_id IS NULL`` 不等于人人可改：没有主人就只剩管理员能动。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_post(client, author, base, published=True)
    tag = (await _search(client, base))["items"][0]  # type: ignore[index]

    response = await client.put(
        f"{TAGS_URL}/{tag['id']}", json={"name": f"{base}-curated"}, headers=admin
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == f"{base}-curated"


async def test_author_cannot_edit_a_system_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """系统内置标签对普通人报 40051：不是"别人的"，而是"它谁都不能改"。

    报 40350 会让作者去找标签的主人要权限——而那个主人不存在。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base, type="system")

    response = await client.put(
        f"{TAGS_URL}/{tag['id']}", json={"name": f"{base}-x"}, headers=author
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == TAG_OPERATION_NOT_ALLOWED


# ──────────────────────────── 唯一性：名字与 slug ────────────────────────────


async def test_duplicate_name_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """同名标签 → 40950。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, base)

    response = await client.post(TAGS_URL, json={"name": base}, headers=admin)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == TAG_ALREADY_EXISTS


async def test_distinct_names_with_the_same_slug_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """两个**不同**的合法名字归化出同一个 slug → 同样 40950。

    只查名字的话这条请求会一路走到 INSERT 才撞唯一索引：
    报错时机更晚、信息更少（PG 只说"某个唯一约束冲突了"）。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, f"{base}.js")

    response = await client.post(TAGS_URL, json={"name": f"{base} js"}, headers=admin)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == TAG_ALREADY_EXISTS


async def test_renaming_a_tag_to_its_own_slug_is_allowed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """改名后 slug 没变时**必须放行**——查重要排除自己。

    这条是最容易漏的 case：``{base}.js`` 与 ``{base} js`` 归化出同一个 slug，
    改名即"把 slug 改成它自己"。
    查重时不排除自己，这个用户就会被自己的标签挡住，报一个谁也看不懂的 40950——
    而他明明只是加了一个空格。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, f"{base}.js")

    response = await client.put(
        f"{TAGS_URL}/{tag['id']}", json={"name": f"{base} js"}, headers=admin
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["slug"] == f"{base}-js"


async def test_renaming_into_an_existing_slug_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """反过来：改到一个已被别人占用的 slug → 40950。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    await _create_tag(client, admin, f"{base}.js")
    other = await _create_tag(client, admin, f"{base}-other")

    response = await client.put(
        f"{TAGS_URL}/{other['id']}", json={"name": f"{base} js"}, headers=admin
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == TAG_ALREADY_EXISTS


async def test_deleted_tag_name_stays_occupied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """软删除之后名字**仍然被占用**：删了再建一个同名的会拿到 40950。

    唯一索引不认 ``status``——这是数据库的事实，代码里一个字都看不到，
    所以只能在这里锁住它。顺带解释了为什么删除不是"释放名字"：
    对已经引用过它的文章来说，「再建一个同名的」会变成两个不同的 id 抢同一个名字。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base)
    deleted = await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)
    assert deleted.status_code == 204, deleted.text

    response = await client.post(TAGS_URL, json={"name": base}, headers=admin)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == TAG_ALREADY_EXISTS


# ──────────────────────────── 生命周期：删除与恢复 ────────────────────────────


async def test_delete_hides_the_tag_and_keeps_its_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """删除回 204，且标签从默认列表里消失。

    这里**不**断言响应体为空：本项目的全局响应中间件会把 204 的空体
    也包成 ``{code,data,message}`` 信封（既有行为，评论的删除接口也一样），
    所以 204 在这个应用里不代表「没有 body」。断言状态码与**效果**即可。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base)

    response = await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)

    assert response.status_code == 204
    assert await _names(client, base) == []


async def test_delete_is_idempotent(client: AsyncClient, db_session: AsyncSession) -> None:
    """重复删除返回同样的结果而不是报错——网络重试是常态。"""
    _, admin = await _admin(client, db_session)
    tag = await _create_tag(client, admin, _base())

    first = await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)
    second = await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)

    assert first.status_code == 204
    assert second.status_code == 204


async def test_deleted_tag_is_not_found_for_the_write_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """已删除的标签在写路径上等同于不存在（404），而不是 40051。

    报 404 是为了不泄漏「这个 id 曾经存在过」——
    否则 404 与 40051 的差异就成了一种探测别人删过什么的手段。
    """
    _, admin = await _admin(client, db_session)
    tag = await _create_tag(client, admin, _base())
    await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)

    response = await client.put(f"{TAGS_URL}/{tag['id']}", json={"name": "whatever"}, headers=admin)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == TAG_NOT_FOUND


async def test_missing_tag_is_not_found(client: AsyncClient, db_session: AsyncSession) -> None:
    """不存在的 id → 40450（三个动作一致）。"""
    _, admin = await _admin(client, db_session)
    missing = uuid4()

    updated = await client.put(f"{TAGS_URL}/{missing}", json={"name": "whatever"}, headers=admin)
    patched = await client.patch(
        f"{TAGS_URL}/{missing}/status", json={"status": "normal"}, headers=admin
    )
    removed = await client.delete(f"{TAGS_URL}/{missing}", headers=admin)

    for response in (updated, patched, removed):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == TAG_NOT_FOUND


async def test_deleted_tag_can_be_restored(client: AsyncClient, db_session: AsyncSession) -> None:
    """状态机是全连通的：``deleted → normal`` 就是"恢复"。

    这也是为什么 ``ChangeTagStatusUseCase`` 刻意**不**调用 ``ensure_not_deleted``——
    加上的话"恢复"从物理上就不可能实现了。
    """
    _, admin = await _admin(client, db_session)
    base = _base()
    tag = await _create_tag(client, admin, base)
    await client.delete(f"{TAGS_URL}/{tag['id']}", headers=admin)
    assert await _names(client, base) == []

    response = await client.patch(
        f"{TAGS_URL}/{tag['id']}/status", json={"status": "normal"}, headers=admin
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "normal"
    assert await _names(client, base) == [base]


async def test_status_change_rejects_unknown_value(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """取值不认识 → 40051（状态问题），而不是 40000（格式问题）。

    格式在 Pydantic 那层就挡住了，能走到这里的只可能是"格式对但取值不认识"。
    """
    _, admin = await _admin(client, db_session)
    tag = await _create_tag(client, admin, _base())

    response = await client.patch(
        f"{TAGS_URL}/{tag['id']}/status", json={"status": "archived"}, headers=admin
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == TAG_OPERATION_NOT_ALLOWED


# ──────────────────────────── 入参校验 ────────────────────────────


async def test_empty_name_is_rejected_by_the_schema(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """空字符串在 Schema 那一层就被挡下 → 40000，不进领域。"""
    _, admin = await _admin(client, db_session)

    response = await client.post(TAGS_URL, json={"name": ""}, headers=admin)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == VALIDATION_FAILED


async def test_whitespace_only_name_is_rejected_by_the_domain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """只有空白的名字长度合法（3 字符）、语义非法，所以由领域报 40036。

    两个错误码的分工在这里最清楚：Schema 管"是不是字符串、长不长"，
    领域管"这个名字能不能用"。
    """
    _, admin = await _admin(client, db_session)

    response = await client.post(TAGS_URL, json={"name": "   "}, headers=admin)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == INVALID_TAG_NAME


async def test_name_with_forbidden_characters_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``/ \\ # ? %`` 会在 URL 里改变语义，统一拒绝。"""
    _, admin = await _admin(client, db_session)
    base = _base()

    response = await client.post(TAGS_URL, json={"name": f"{base}/x"}, headers=admin)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == INVALID_TAG_NAME


async def test_overlong_description_is_rejected_by_the_schema(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """描述超长 → 40000，且这条校验与领域的上限是同两个常量。"""
    _, admin = await _admin(client, db_session)

    response = await client.post(
        TAGS_URL,
        json={"name": _base(), "description": "字" * (TAG_DESCRIPTION_MAX_LEN + 1)},
        headers=admin,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == VALIDATION_FAILED


async def test_null_description_means_no_description(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``description: null`` 与"不传"同义，都落成 ``None``，而不是空串。"""
    _, admin = await _admin(client, db_session)
    base = _base()

    created = await _create_tag(client, admin, f"{base}-null", description=None)
    cleared = await client.put(
        f"{TAGS_URL}/{created['id']}",
        json={"name": f"{base}-null", "description": ""},
        headers=admin,
    )

    assert created["description"] is None
    assert cleared.json()["data"]["description"] is None


async def test_author_id_comes_from_the_token_not_the_body(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """请求体里的 ``author_id`` 被忽略，归属一律从 token 推导。

    让客户端指定归属等于允许以别人的名义建标签，
    而"谁该对这个标签负责"一旦可以伪造，归属校验就失去意义了。
    """
    admin_id, admin = await _admin(client, db_session)
    victim = uuid4()
    base = _base()

    created = await _create_tag(client, admin, base, author_id=str(victim))

    assert created["author_id"] == admin_id


async def test_error_responses_keep_the_envelope(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """错误响应也是 ``{code, message, data}``——前端只需要实现一套解析。

    包封是由中间件统一加的，所以这里顺带验证它没有被某个异常处理器绕过去。
    """
    _, admin = await _admin(client, db_session)

    response = await client.post(TAGS_URL, json={"name": ""}, headers=admin)
    body = response.json()

    assert set(body) >= {"code", "message"}
    assert body["code"] == VALIDATION_FAILED
    assert isinstance(body["message"], str)


async def test_description_is_free_text_and_survives_round_trip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """描述只是列表页上的一句说明：要能原样存、原样取，不能被顺手 strip 掉中间的内容。"""
    _, admin = await _admin(client, db_session)
    base = _base()
    text = "这是 一段   带空格的说明"

    created = await _create_tag(client, admin, base, description=f"  {text}  ")

    assert created["description"] == text
    assert (await _search(client, base))["items"][0]["description"] == text  # type: ignore[index]


async def test_description_at_the_limit_is_accepted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """长度恰好等于上限时合法——上限是闭区间，Schema 与领域用的是同一个常量。"""
    _, admin = await _admin(client, db_session)
    exact = "字" * TAG_DESCRIPTION_MAX_LEN

    created = await _create_tag(client, admin, _base(), description=exact)

    assert created["description"] == exact
