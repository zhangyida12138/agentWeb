"""博客接口的集成测试：真库 + 真 ASGI 应用。

为什么这一层不可省：权限相关的 bug 几乎全出在**接线**上而不是**规则**上——
    守卫挂错端点、`actor_can_override` 忘了传、软删除只过滤了列表没过滤详情、
    PATCH 少传字段把摘要清空……这些只有「请求真的走完整条依赖链」才暴露得出来。
    规则本身（状态机、可见性、slug 派生）由 ``tests/unit/test_post.py`` 验，这里不重复。

本文件重点守三条产品决策：
    ① 未登录能读**已发布**文章，且读不到别人的草稿（404 而不是 403）；
    ② 作者只能改自己的文章，管理员凭 ``post:update_any`` / ``post:delete_any`` 越权；
    ③ PATCH 只改传了的字段，没传的绝不被清空。

前置数据（角色 / 权限矩阵）从哪来：见 ``tests/integration/conftest.py``——
``ASGITransport`` 不跑 lifespan，角色表不会自动填，得由 autouse 夹具灌进测试事务。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import PermissionCode, RoleCode
from app.infrastructure.persistence.repositories.access import SqlAccessRepository

POSTS_URL = "/api/v1/posts"
MY_POSTS_URL = "/api/v1/me/posts"
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
PASSWORD = "Sup3r-secret"

# 与 domain 里的错误码常量一一对应，写死数字以锁住对外契约
VALIDATION_FAILED = 40000
INVALID_POST_TITLE = 40030
INVALID_POST_STATUS = 40035
PERMISSION_DENIED = 40320
POST_FORBIDDEN = 40330
POST_NOT_FOUND = 40430
SLUG_TAKEN = 40930


# ──────────────────────────── 辅助 ────────────────────────────
# 这里刻意不去 import test_rbac_api 里的同名辅助：
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
    email = f"blog{suffix}@example.com"
    response = await client.post(
        REGISTER_URL,
        json={
            "email": email,
            "username": f"blog{suffix}",
            "password": PASSWORD,
            "display_name": None,
        },
    )
    assert response.status_code == 201, response.text
    user_id = response.json()["data"]["id"]

    await SqlAccessRepository(db_session).assign_roles(UUID(user_id), set(role_codes))

    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.json()["data"]["token"]["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def _create_post(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "一篇测试文章",
    content: str = "# 正文\n\n内容",
    **extra: object,
) -> dict[str, object]:
    """新建文章，返回响应里的 ``data``（草稿状态）。"""
    response = await client.post(
        POSTS_URL,
        json={"title": title, "content": content, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _publish(client: AsyncClient, headers: dict[str, str], post_id: str) -> dict[str, object]:
    """发布文章并返回响应里的 ``data``。"""
    response = await client.post(f"{POSTS_URL}/{post_id}/publish", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _ids(page: dict[str, object]) -> list[str]:
    return [str(item["id"]) for item in page["items"]]  # type: ignore[union-attr]


def _unique_tag() -> str:
    """随机标签名。

    用它给用例自己的数据打标记，然后靠 ``?tag=`` 把断言范围收窄到自己造的数据上——
    这样即使开发库里原本就有别人的文章，用例也不会互相干扰。
    """
    return f"tag-{uuid4().hex[:8]}"


# ──────────────────────────── 公开读取（未登录也能看） ────────────────────────────


async def test_anonymous_can_list_published_posts(client: AsyncClient) -> None:
    """列表接口不带 token 也要能通。

    「未登录也能看」这条决策的第一个落点：读接口上不能挂 ``CurrentUser`` 依赖，
    否则匿名访问会先被 401 拦下，整个公开站点就没了。
    """
    response = await client.get(POSTS_URL)

    assert response.status_code == 200, response.text
    page = response.json()["data"]
    assert {"items", "total", "offset", "limit"} <= page.keys()


async def test_published_post_is_readable_anonymously(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """已发布文章匿名可读，且阅读量会 +1（作者自己读不涨，见另一个用例）。"""
    _, headers = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, headers, slug="public-read-demo")
    await _publish(client, headers, str(post["id"]))

    first = await client.get(f"{POSTS_URL}/public-read-demo")

    assert first.status_code == 200, first.text
    detail = first.json()["data"]
    assert detail["status"] == "published"
    assert detail["published_at"] is not None
    assert detail["view_count"] == 1
    assert detail["content"] == "# 正文\n\n内容"

    second = await client.get(f"{POSTS_URL}/public-read-demo")
    assert second.json()["data"]["view_count"] == 2


async def test_author_reading_own_post_does_not_inflate_view_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """作者刷新自己的文章不涨阅读量——那更像编辑时的预览。

    否则作者自测几轮，计数就完全失去参考价值。
    """
    _, headers = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, headers, slug="own-view-demo")
    await _publish(client, headers, str(post["id"]))

    response = await client.get(f"{POSTS_URL}/own-view-demo", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["view_count"] == 0


async def test_anonymous_reading_someone_elses_draft_gets_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """别人的草稿对匿名读者**完全不存在**。

    这里必须是 404 而不是 403：403 等于承认「这里有一篇你没权限的文章」，
    可以据此枚举出存在性。草稿的内容与存在性都属于作者私有。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="draft-secret-demo")

    response = await client.get(f"{POSTS_URL}/draft-secret-demo")

    assert response.status_code == 404
    assert response.json()["code"] == POST_NOT_FOUND
    # 顺带确认这篇草稿确实存在，否则本用例会因为「slug 压根没建成」而假绿
    assert post["status"] == "draft"


async def test_author_can_preview_own_draft_but_anonymous_cannot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """同一条读路径上，作者能预览草稿、匿名不能——靠 ``OptionalCurrentUser`` 区分。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    await _create_post(client, author, slug="preview-demo")

    mine = await client.get(f"{POSTS_URL}/preview-demo", headers=author)
    theirs = await client.get(f"{POSTS_URL}/preview-demo")

    assert mine.status_code == 200, mine.text
    assert mine.json()["data"]["status"] == "draft"
    assert theirs.status_code == 404


# ──────────────────────────── 权限与归属 ────────────────────────────


async def test_reader_cannot_create_post(client: AsyncClient, db_session: AsyncSession) -> None:
    """reader 没有 ``post:create`` → 403，且响应带上缺的是哪个权限。"""
    _, headers = await _actor(client, db_session, RoleCode.READER)

    response = await client.post(
        POSTS_URL, json={"title": "标题", "content": "正文"}, headers=headers
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == PERMISSION_DENIED
    assert body["data"]["permission"] == PermissionCode.POST_CREATE


async def test_anonymous_cannot_create_post(client: AsyncClient) -> None:
    """未登录不是 403 而是 401——前端据此决定「去登录」还是「找管理员」。"""
    response = await client.post(POSTS_URL, json={"title": "标题", "content": "正文"})

    assert response.status_code == 401


async def test_other_author_cannot_edit_or_delete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """另一个作者即使持有 ``post:update``，也改不动别人的文章。

    这是「作者只能改自己的文章」这条规则的核心落点：
    ``post:update`` 只回答「你能不能编辑文章」，不回答「这一篇是不是你的」。
    越界给 40330（不是 404）——已发布文章的存在不是秘密，假装不存在只会让人白查。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, intruder = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="owned-by-a")

    patched = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"title": "我改了"}, headers=intruder
    )
    deleted = await client.delete(f"{POSTS_URL}/{post['id']}", headers=intruder)

    assert patched.status_code == 403
    assert patched.json()["code"] == POST_FORBIDDEN
    assert deleted.status_code == 403
    assert deleted.json()["code"] == POST_FORBIDDEN


async def test_admin_can_edit_and_delete_others_post(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """管理员凭 ``post:update_any`` / ``post:delete_any`` 越过归属限制。

    用 admin 角色而不是手工授予 ``*_any``：这样测的就是「角色矩阵是否正确包含
    这两个特权码」这个真实配置，而不是一个测试里现编的权限集合。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, admin = await _actor(client, db_session, RoleCode.ADMIN)
    post = await _create_post(client, author, slug="moderated-post", title="原标题")

    patched = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"title": "管理员改的"}, headers=admin
    )
    deleted = await client.delete(f"{POSTS_URL}/{post['id']}", headers=admin)

    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["title"] == "管理员改的"
    assert deleted.status_code == 204


async def test_authoring_roles_do_not_include_the_any_codes() -> None:
    """作者角色**刻意不含** ``post:*_any``。

    给了作者等于把「作者只能改自己的文章」这条规则关掉，
    而那种改动在代码里只体现为 ``_AUTHOR_PERMISSIONS`` 多一个元素，
    评审时极易被放过。这里把它钉成一条断言。
    """
    from app.domain.access.entities import _AUTHOR_PERMISSIONS

    assert PermissionCode.POST_UPDATE_ANY not in _AUTHOR_PERMISSIONS
    assert PermissionCode.POST_DELETE_ANY not in _AUTHOR_PERMISSIONS


# ──────────────────────────── slug 唯一性 ────────────────────────────


async def test_duplicate_explicit_slug_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """显式指定已被占用的 slug → 409。

    指定 slug 是「我要这个地址」，撞了不能悄悄给我换一个——
    那样调用方以为自己拿到了 ``/posts/foo``，实际是 ``/posts/foo-2``。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    await _create_post(client, author, slug="taken-slug")

    response = await client.post(
        POSTS_URL,
        json={"title": "另一篇", "content": "正文", "slug": "taken-slug"},
        headers=author,
    )

    assert response.status_code == 409
    assert response.json()["code"] == SLUG_TAKEN


async def test_derived_slug_gets_auto_suffixed_when_title_collides(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """不指定 slug 时按标题派生，撞车自动加后缀。

    「标题撞车」是极常见的正常操作（同一个人写系列文章），
    这里报 409 会变成很难理解的产品缺陷。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    first = await _create_post(client, author, title="同名标题")
    second = await _create_post(client, author, title="同名标题")

    assert first["slug"] != second["slug"]
    assert str(second["slug"]).endswith("-2")


async def test_patch_content_does_not_change_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """改标题不跟着改 slug：slug 是地址，改动会打断所有既有链接。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="stable-address")

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"title": "完全换掉标题"}, headers=author
    )

    assert response.status_code == 200
    assert response.json()["data"]["slug"] == "stable-address"


# ──────────────────────────── PATCH 语义（数据丢失回归） ────────────────────────────


async def test_patching_only_title_keeps_summary_cover_and_tags(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """最重要的回归用例：只改标题不能清空摘要 / 封面 / 标签。

    ``UpdatePostRequest.model_dump()`` 会把「没传的字段」也填成 ``None``，
    于是表现层少写一个 ``exclude_unset=True`` 就会造成静默数据丢失——
    用户保存一次标题，摘要和标签全部没了，而且没有任何报错。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    post = await _create_post(
        client,
        author,
        title="原标题",
        slug="patch-safety",
        summary="原来的摘要",
        cover_url="/uploads/cover.png",
        tag_names=[tag],
    )

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"title": "新标题"}, headers=author
    )

    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["title"] == "新标题"
    assert detail["summary"] == "原来的摘要"
    assert detail["cover_url"] == "/uploads/cover.png"
    assert detail["tags"] == [tag]


async def test_patching_with_explicit_null_clears_optional_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """显式 ``null`` 与「没传」必须区分开：前者是清空，后者是不动。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="clear-me", summary="原摘要")

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"summary": None}, headers=author
    )

    assert response.status_code == 200
    assert response.json()["data"]["summary"] is None


async def test_patching_tags_replaces_the_whole_set(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """标签是整体替换语义（聚合根内部的集合），不是「追加」。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    old_tag = _unique_tag()
    new_tag = _unique_tag()
    post = await _create_post(client, author, slug="retag-me", tag_names=[old_tag])

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"tag_names": [new_tag]}, headers=author
    )

    assert response.status_code == 200
    assert response.json()["data"]["tags"] == [new_tag]


# ──────────────────────────── 列表 / 筛选 / 分页 ────────────────────────────


async def test_public_feed_only_contains_published_posts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """草稿不能出现在公开列表里——否则「未发布」就只是个装饰字段。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    draft = await _create_post(client, author, slug="feed-draft", tag_names=[tag])
    published = await _create_post(client, author, slug="feed-published", tag_names=[tag])
    await _publish(client, author, str(published["id"]))

    page = (await client.get(POSTS_URL, params={"tag": tag})).json()["data"]

    assert _ids(page) == [str(published["id"])]
    assert draft["id"] is not None


async def test_tag_filter_and_total_agree(client: AsyncClient, db_session: AsyncSession) -> None:
    """``total`` 必须与筛选条件一致。

    这是最容易写错的一处：列表查询加了 tag 过滤、计数查询忘了加，
    于是 total 显示 3 而实际返回 20 条——前端分页器直接算错页数。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    for index in range(3):
        post = await _create_post(client, author, slug=f"tag-count-{index}", tag_names=[tag])
        await _publish(client, author, str(post["id"]))

    page = (await client.get(POSTS_URL, params={"tag": tag, "limit": 100})).json()["data"]

    assert page["total"] == 3
    assert len(page["items"]) == 3


async def test_pagination_pages_are_disjoint_and_cover_everything(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """翻页不能重复也不能漏——offset/limit 传错一个位置（比如先 limit 后 offset）就会这样。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    for index in range(3):
        post = await _create_post(client, author, slug=f"paged-{index}", tag_names=[tag])
        await _publish(client, author, str(post["id"]))

    filters: dict[str, object] = {"tag": tag, "limit": 2}
    first = (await client.get(POSTS_URL, params={**filters, "offset": 0})).json()["data"]
    second = (await client.get(POSTS_URL, params={**filters, "offset": 2})).json()["data"]

    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert set(_ids(first)).isdisjoint(_ids(second))


async def test_my_posts_requires_auth_and_is_scoped_to_me(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """「我的文章」只返回自己的，并含草稿；未登录 401。

    注意它**不要求 post:* 权限**：归属比权限码更强——
    连编辑权限都被收走的作者，依然应该能看到自己的草稿列表。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, other = await _actor(client, db_session, RoleCode.AUTHOR)
    mine = await _create_post(client, author, slug="my-post-a")

    anonymous = await client.get(MY_POSTS_URL)
    page = (await client.get(MY_POSTS_URL, headers=author)).json()["data"]
    others = (await client.get(MY_POSTS_URL, headers=other)).json()["data"]

    assert anonymous.status_code == 401
    assert str(mine["id"]) in _ids(page)
    assert _ids(others) == []


async def test_my_posts_are_ordered_by_updated_at_desc(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """自己的列表按**更新时间**倒序：刚改过的排最前，符合「继续编辑」的工作流。

    公开列表则按 ``published_at`` 倒序——两个列表的排序依据不同，
    这是刻意的，用同一个查询很容易被「顺手统一」掉。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    older = await _create_post(client, author, slug="ordered-older")
    newer = await _create_post(client, author, slug="ordered-newer")
    # 改动较早那篇，让它挤到最前
    await client.patch(f"{POSTS_URL}/{older['id']}", json={"title": "刚改过"}, headers=author)

    page = (await client.get(MY_POSTS_URL, headers=author)).json()["data"]

    assert _ids(page)[0] == str(older["id"])
    assert str(newer["id"]) in _ids(page)


async def test_invalid_status_filter_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``?status=publihsed`` 必须报错而不是被当成「不筛选」。

    静默忽略的话前端会收到整份列表且看起来完全正常，问题要很久以后才暴露。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)

    response = await client.get(MY_POSTS_URL, params={"status": "publihsed"}, headers=author)

    assert response.status_code == 400
    assert response.json()["code"] == INVALID_POST_STATUS


# ──────────────────────────── 发布 / 下架 / 删除 ────────────────────────────


async def test_publish_then_unpublish_removes_from_feed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """下架后从公开列表消失，但文章本身还在（作者仍能看到）。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    post = await _create_post(client, author, slug="lifecycle-demo", tag_names=[tag])
    await _publish(client, author, str(post["id"]))

    unpublished = await client.post(f"{POSTS_URL}/{post['id']}/unpublish", headers=author)
    page = (await client.get(POSTS_URL, params={"tag": tag})).json()["data"]
    mine = (await client.get(MY_POSTS_URL, headers=author)).json()["data"]

    assert unpublished.status_code == 200
    assert unpublished.json()["data"]["status"] == "archived"
    assert page["total"] == 0
    assert str(post["id"]) in _ids(mine)


async def test_unpublish_twice_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """重复下架报 40035。

    与「重复发布幂等」不对称是刻意的：发布可能被连点需要容错，
    而对着一篇已经归档的文章再点下架，说明调用方的状态认知是错的，
    继续返回成功只会把真正的 bug 藏起来。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="double-unpublish")
    await _publish(client, author, str(post["id"]))
    await client.post(f"{POSTS_URL}/{post['id']}/unpublish", headers=author)

    second = await client.post(f"{POSTS_URL}/{post['id']}/unpublish", headers=author)

    assert second.status_code == 400
    assert second.json()["code"] == INVALID_POST_STATUS


async def test_soft_deleted_post_disappears_everywhere(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """软删除后：详情 404、公开列表没有、我的列表也没有、slug 仍被占用。

    slug 仍被占用是**设计目标**：物理删除会让老链接指向一篇
    内容完全不同的新文章，比 404 危险得多。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    tag = _unique_tag()
    post = await _create_post(client, author, slug="soft-deleted-demo", tag_names=[tag])
    await _publish(client, author, str(post["id"]))

    deleted = await client.delete(f"{POSTS_URL}/{post['id']}", headers=author)
    detail = await client.get(f"{POSTS_URL}/soft-deleted-demo")
    feed = (await client.get(POSTS_URL, params={"tag": tag})).json()["data"]
    mine = (await client.get(MY_POSTS_URL, headers=author)).json()["data"]

    assert deleted.status_code == 204
    assert detail.status_code == 404
    assert detail.json()["code"] == POST_NOT_FOUND
    assert feed["total"] == 0
    assert str(post["id"]) not in _ids(mine)

    reused = await client.post(
        POSTS_URL,
        json={"title": "想复用 slug", "content": "正文", "slug": "soft-deleted-demo"},
        headers=author,
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == SLUG_TAKEN


async def test_slug_can_be_changed_explicitly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """改 slug 是**显式**动作：必须单独传 ``slug`` 才会变（见另一个 PATCH 用例）。

    顺带验证一件容易被忽略的事：老地址要真的 404。
    只断言「新地址能打开」是不够的——两个地址同时可用意味着旧链接
    还能访问到同一篇内容，那是另一个 bug（而不是找不到）。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _create_post(client, author, slug="before-change")
    await _publish(client, author, str(post["id"]))

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"slug": "after-change"}, headers=author
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["slug"] == "after-change"
    assert (await client.get(f"{POSTS_URL}/after-change")).status_code == 200
    assert (await client.get(f"{POSTS_URL}/before-change")).status_code == 404


async def test_patching_to_a_taken_slug_conflicts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """改成已被占用的 slug → 409，而不是静默截断或覆盖。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    await _create_post(client, author, slug="occupied-one")
    post = await _create_post(client, author, slug="occupied-two")

    response = await client.patch(
        f"{POSTS_URL}/{post['id']}", json={"slug": "occupied-one"}, headers=author
    )

    assert response.status_code == 409
    assert response.json()["code"] == SLUG_TAKEN


# ──────────────────────────── 入参校验 ────────────────────────────


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"title": "", "content": "正文"}, VALIDATION_FAILED),
        ({"title": "   ", "content": "正文"}, INVALID_POST_TITLE),
        ({"title": "标题", "content": ""}, VALIDATION_FAILED),
        ({"title": "标题"}, VALIDATION_FAILED),
    ],
)
async def test_invalid_payload_is_rejected_with_400(
    client: AsyncClient,
    db_session: AsyncSession,
    payload: dict[str, str],
    expected_code: int,
) -> None:
    """入参不合法一律 **400**（绝不是 FastAPI 默认的 422），但 ``code`` 分两层。

    这是全项目统一的对外契约：前端只需要理解一套错误结构
    （``{code, message, data}``），不必为「参数校验失败」再写一个分支。

    两层分工是有意的：
        schema 层（40000）只管「字段在不在、是不是明显为空」；
        领域层只管「语义上算不算空」——``"   "`` 能过 ``min_length=1``，
        只有 ``PostTitle`` 的 strip + 非空校验能看出来，所以它报 40030。
    更具体的 code 对前端是好事：能直接把错误挂到标题输入框上。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)

    response = await client.post(POSTS_URL, json=payload, headers=author)

    assert response.status_code == 400
    assert response.json()["code"] == expected_code


async def test_blank_title_error_points_at_the_title_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """领域错误带上 ``data.field``，前端才能把消息挂到对应输入框。

    没有它，前端只能靠字符串匹配消息内容——那种做法一改文案就断。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)

    response = await client.post(
        POSTS_URL, json={"title": "   ", "content": "正文"}, headers=author
    )

    assert response.json()["data"]["field"] == "title"
