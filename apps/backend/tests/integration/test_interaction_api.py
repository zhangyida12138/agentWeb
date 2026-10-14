"""互动接口的集成测试：真库 + 真 ASGI 应用。

为什么这一层不可省：互动这组接口的 bug 几乎全出在**接线**上而不是**规则**上——
    守卫挂错端点、`actor_can_override` 忘了传、软删除只过滤了根评论没过滤回复、
    `target_type` 忘了收敛、回复的归属算错了一层……这些只有「请求真的走完整条依赖链」
    才暴露得出来。规则本身（正文收敛、两把尺子、父链原样保留）由
    ``tests/unit/test_comment.py`` 验，这里不重复。

PLAN.md 给 M5 点名的两条验收标准，正是本文件的两个标题小节：
    ① **重复点赞不重复计数**；
    ② **回复归属正确**——这里的“正确”在重设计后指的是
       「回复的 ``parent_id`` 就是用户点的那条评论」（而不是归一到根），
       所以树可以是**任意深度**，而不只是两层。
       相应地，分页的 total 依旧是**根评论**数。

另外守住三条产品决策：
    ③ 未登录能读评论与统计，但读不到别人草稿下的任何东西（404 而不是 403）；
    ④ 「能发言」与「能删自己的发言」分开，管理员凭 ``comment:delete_any`` 越权；
    ⑤ 撤回是墓碑：被撤回的评论只要下面**还有活着的后代**，位置就必须留着
       （否则对话断裂）。任意深度下这条判据也只能是“有没有活着的后代”，
       而不能是“有没有直接子行”——中间层自己也可能被撤回（见
       ``test_deleted_mid_level_comment_stays_when_descendants_remain``）。

为什么还有一条专测**作者名**：
    “小明 回复 小红”要求服务端把名字解析好给出（否则前端就是 N+1），
    而名字属于**另一个上下文**（identity），只能靠用例跨上下文编排。
    它是本模块唯一一处需要 ``UserRepository`` 的地方，
    接错线（忘了注入）会让整个接口 500，只有真请求能发现。

前置数据（角色 / 权限矩阵）从哪来：见 ``tests/integration/conftest.py``——
``ASGITransport`` 不跑 lifespan，角色表不会自动填，得由 autouse 夹具灌进测试事务。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import RoleCode
from app.infrastructure.persistence.models.like import LikeModel
from app.infrastructure.persistence.repositories.access import SqlAccessRepository
from app.infrastructure.persistence.repositories.interaction import SqlLikeRepository

POSTS_URL = "/api/v1/posts"
MY_POSTS_URL = "/api/v1/me/posts"
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
LIKE_URL = "/api/v1/likes/toggle"
PASSWORD = "Sup3r-secret"

# 与 domain 里的错误码一一对应，写死数字以锁住对外契约
VALIDATION_FAILED = 40000
INVALID_COMMENT_CONTENT = 40040
INVALID_LIKE_TARGET = 40041
PERMISSION_DENIED = 40320
COMMENT_FORBIDDEN = 40340
POST_NOT_FOUND = 40430
COMMENT_NOT_FOUND = 40440
TARGET_NOT_FOUND = 40441
INTERACTION_CLOSED = 40940


def _comments_url(post_id: object) -> str:
    return f"{POSTS_URL}/{post_id}/comments"


def _stats_url(post_id: object) -> str:
    return f"{POSTS_URL}/{post_id}/interactions"


def _comment_url(comment_id: object) -> str:
    return f"/api/v1/comments/{comment_id}"


# ──────────────────────────── 辅助 ────────────────────────────
# 与 test_posts_api.py 刻意重复：测试之间共享工具会形成隐式耦合，
# 改一个辅助函数就可能让另一个文件的断言语境变掉。
# 几行重复换来「每个文件能独立读懂」，值得。


async def _actor(
    client: AsyncClient,
    db_session: AsyncSession,
    *role_codes: str,
    display_name: str | None = None,
) -> tuple[str, dict[str, str]]:
    """造一个拥有指定角色的已登录用户，返回 ``(user_id, headers)``。

    角色直接写库、不走接口：``PUT /users/{id}/roles`` 需要 ``user:assign_roles``，
    用它造前置数据会陷入「要管理员才能造管理员」的循环。
    不传角色时该用户**一个角色都没有**，用于验证 40320。

    ``display_name`` 不传就是 None（库里的既有默认），
    此时评论作者名会回落到用户名——而注册接口生成的是
    ``talk<随机后缀>``，所以不传时作者名就是那个用户名。
    """
    suffix = uuid4().hex[:10]
    email = f"talk{suffix}@example.com"
    response = await client.post(
        REGISTER_URL,
        json={
            "email": email,
            "username": f"talk{suffix}",
            "password": PASSWORD,
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    user_id = response.json()["data"]["id"]

    await SqlAccessRepository(db_session).assign_roles(UUID(user_id), set(role_codes))

    login = await client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.json()["data"]["token"]["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def _published_post(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "一篇可评论的文章",
) -> dict[str, object]:
    """造一篇**已发布**的文章，返回响应里的 ``data``。"""
    created = await client.post(
        POSTS_URL,
        json={"title": title, "content": "# 正文\n\n内容"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["data"]["id"]

    published = await client.post(f"{POSTS_URL}/{post_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return published.json()["data"]


async def _draft_post(
    client: AsyncClient,
    headers: dict[str, str],
) -> dict[str, object]:
    """造一篇**草稿**（未发布）的文章。"""
    created = await client.post(
        POSTS_URL,
        json={"title": "还没写完的草稿", "content": "草稿内容"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _comment(
    client: AsyncClient,
    headers: dict[str, str],
    post_id: object,
    *,
    content: str = "一条评论",
    parent_id: object = None,
) -> dict[str, object]:
    """发一条评论（或回复），返回响应里的 ``data``。"""
    body: dict[str, object] = {"content": content}
    if parent_id is not None:
        body["parent_id"] = str(parent_id)
    response = await client.post(_comments_url(post_id), json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _like(
    client: AsyncClient,
    headers: dict[str, str],
    target_id: object,
    *,
    target_type: str = "post",
) -> dict[str, object]:
    """切换一次点赞状态，返回响应里的 ``data``。"""
    response = await client.post(
        LIKE_URL,
        json={"target_type": target_type, "target_id": str(target_id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _stats(client: AsyncClient, post_id: object) -> dict[str, object]:
    """读互动统计（匿名），返回响应里的 ``data``。"""
    response = await client.get(_stats_url(post_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ──────────────────────────── 公开读取 ────────────────────────────


async def test_anonymous_can_read_comments(client: AsyncClient, db_session: AsyncSession) -> None:
    """未登录也能读评论树。

    「未登录也能看」这条决策在读接口上的落点：这里不能挂 ``CurrentUser``，
    否则匿名访问先被 401 拦下，评论区就成了会员区。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)

    response = await client.get(_comments_url(post["id"]))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 20,
    }


async def test_comments_of_unknown_post_return_404(client: AsyncClient) -> None:
    """文章不存在 → 40430（而不是空列表）。

    空列表会让前端显示「还没有评论，快来抢沙发」，
    而真相是**这篇文章根本不在**——用户于是去检查网络，
    而不是检查自己点进来的链接。
    """
    response = await client.get(_comments_url(uuid4()))

    assert response.status_code == 404
    assert response.json()["code"] == POST_NOT_FOUND


async def test_comments_of_someone_elses_draft_return_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """别人草稿下的评论区对所有人 404（包括登录用户）。

    404 而不是 403：403 等于承认「这里确实有一篇草稿」，
    而别人未发布内容的**存在性**本身就是私有信息。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, stranger = await _actor(client, db_session, RoleCode.READER)
    draft = await _draft_post(client, author)

    anonymous = await client.get(_comments_url(draft["id"]))
    logged_in = await client.get(_comments_url(draft["id"]), headers=stranger)

    assert anonymous.status_code == 404
    assert anonymous.json()["code"] == POST_NOT_FOUND
    assert logged_in.status_code == 404
    assert logged_in.json()["code"] == POST_NOT_FOUND


async def test_author_can_read_comments_of_own_draft(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """作者本人能读自己草稿的评论区。

    读接口**不**判「互动是否开放」——那是写入口的门槛。
    作者在发布前预览页面时看到的评论区必须是同一份数据，
    否则「发布后评论突然冒出来」会让人以为是别人抢先发的。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    draft = await _draft_post(client, author)

    response = await client.get(_comments_url(draft["id"]), headers=author)

    assert response.status_code == 200


# ──────────────────────────── 发表评论 ────────────────────────────


async def test_reader_can_comment_on_published_post(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """读者在已发布文章下发言 → 201 + 完整评论。

    返回完整评论而不是只回 id：前端要把它**就地插入**评论区，
    只回 id 的话还得再拉整棵树才能知道它长什么样。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    reader_id, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": "  写得不错  "},
        headers=reader,
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["content"] == "写得不错"  # 首尾空白在领域里被抹平
    assert data["author_id"] == reader_id
    assert data["post_id"] == post["id"]
    assert data["parent_id"] is None
    assert data["is_deleted"] is False
    assert data["like_count"] == 0
    assert data["liked_by_me"] is False
    assert data["replies"] == []


async def test_anonymous_cannot_comment(client: AsyncClient, db_session: AsyncSession) -> None:
    """未登录发言 → 401（缺 token，不是缺权限）。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)

    response = await client.post(_comments_url(post["id"]), json={"content": "我是游客"})

    assert response.status_code == 401


async def test_comment_requires_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """无 ``comment:create`` 的登录用户 → 40320。

    这条同时锁住「读者角色必须带 comment:create」这个配置事实：
    如果哪天有人在角色矩阵里手滑摘掉它，这里会红。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, nobody = await _actor(client, db_session)  # 一个角色都没有
    post = await _published_post(client, author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": "我能不能说话？"},
        headers=nobody,
    )

    assert response.status_code == 403
    assert response.json()["code"] == PERMISSION_DENIED


async def test_comment_on_draft_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """草稿下不能发言 → 40940。

    作者在自己的草稿上都不行：草稿的评论区一旦开放，
    就等于「未发布内容可以产生公开互动」，而互动是会被别人看见的。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    draft = await _draft_post(client, author)

    response = await client.post(
        _comments_url(draft["id"]),
        json={"content": "自说自话"},
        headers=author,
    )

    assert response.status_code == 409
    assert response.json()["code"] == INTERACTION_CLOSED


async def test_comment_on_archived_post_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """已归档（下架）文章下不能发言 → 40940。

    归档意味着作者不希望这个页面继续积累新的互动，
    而已有评论仍然可读——这是「下架」与「删除」的区别在评论上的体现。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)
    await client.post(f"{POSTS_URL}/{post['id']}/unpublish", headers=author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": "还能说话吗"},
        headers=author,
    )

    assert response.status_code == 409
    assert response.json()["code"] == INTERACTION_CLOSED


async def test_comment_on_unknown_post_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """文章不存在 → 40430（先判可见，再判开放）。"""
    _, reader = await _actor(client, db_session, RoleCode.READER)

    response = await client.post(
        _comments_url(uuid4()),
        json={"content": "有人在吗"},
        headers=reader,
    )

    assert response.status_code == 404
    assert response.json()["code"] == POST_NOT_FOUND


@pytest.mark.parametrize("content", ["", None])
async def test_empty_comment_is_rejected_by_the_schema(
    client: AsyncClient,
    db_session: AsyncSession,
    content: str | None,
) -> None:
    """完全空的内容 → 40000（在 schema 这一层就被拦下）。

    只有「长度为 0」和「根本没传」能被 ``min_length=1`` 拦住（外加 ``None``：
    必填字段传 null）。纯空白拿到的会是 40040——那是下一条用例的事。
    两个码的分工：40000 是「字段形状不对」，40040 是「形状对了、内容不合法」。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": content},
        headers=reader,
    )

    assert response.status_code == 400
    assert response.json()["code"] == VALIDATION_FAILED


@pytest.mark.parametrize("content", ["   ", "\n\t ", "　"])
async def test_whitespace_only_comment_reaches_domain_validation(
    client: AsyncClient,
    db_session: AsyncSession,
    content: str,
) -> None:
    """纯空白（非空字符串）→ 40040，由领域值对象负责。

    这一条专门证明「schema 不是唯一防线」：
    ``"   "`` 长度为 3，完全能通过 ``min_length=1``；
    如果领域不 strip 再判空，库里就会出现一条**看不见的**评论——
    评论区里多出一个什么都不占、却需要滑动才能越过的空隙。

    第三个取值 ``"　"`` 是全角空格（U+3000）：它**同样**被 Python 的
    ``str.strip()`` 视作空白，所以不需要为它写任何特殊逻辑。
    列在这里是为了把这个事实钉住——哪天有人用「排除 ASCII 空格」
    之类的正则去改写收敛逻辑，这一条会立刻变红。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": content},
        headers=reader,
    )

    assert response.status_code == 400
    assert response.json()["code"] == INVALID_COMMENT_CONTENT


# ──────────────────────────── 回复归属正确 ────────────────────────────


async def test_reply_is_attached_to_its_parent(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**验收标准 ②**：回复挂在被回复的那条根评论下。

    这条同时验证三件事：
        ① ``parent_id`` 被如实保存（不是被当成根评论）；
        ② 树响应里它以 ``replies`` 的形式出现在那条根评论下（不是顶层）；
        ③ ``total`` 只数根评论——把回复也算进去的话，
           前端的「加载更多」会在最后几页请求到空数据。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="沙发")

    reply = await _comment(client, author, post["id"], content="回沙发", parent_id=root["id"])

    assert reply["parent_id"] == root["id"]

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["total"] == 1  # 只有一条根评论
    assert len(tree["items"]) == 1
    assert tree["items"][0]["id"] == root["id"]
    assert [item["id"] for item in tree["items"][0]["replies"]] == [reply["id"]]
    assert tree["items"][0]["replies"][0]["content"] == "回沙发"


async def test_reply_to_a_reply_keeps_its_real_parent(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**验收标准 ②**：回复「回复的回复」保留**真实父级**，树可以任意深。

    这条是本项目最重要的一条回归：早先的实现把 parent 归一到根评论，
    于是「他回的是谁」在落库那一刻就被抹掉了，
    而界面上要显示「小明 回复 小红」时，库里的信息已经不够了。

    现在 parent_id 原样落库，于是：
        ① 三楼的 parent 是二楼（而不是一楼）；
        ② 三楼出现在二楼的 ``replies`` 里，**不**作为一楼的回复兄弟；
        ③ 树的深度不再有上限——第三层真的存在于响应里。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="一楼")
    first_reply = await _comment(client, author, post["id"], content="二楼", parent_id=root["id"])

    # 用户点的是「回复二楼」
    second_reply = await _comment(
        client,
        reader,
        post["id"],
        content="三楼",
        parent_id=first_reply["id"],
    )

    assert second_reply["parent_id"] == first_reply["id"]
    assert second_reply["parent_id"] != root["id"]  # 明确断言没被归一

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["total"] == 1  # 分页单位仍然是根评论
    assert len(tree["items"]) == 1
    node = tree["items"][0]
    # 二楼是一楼唯一的回复（三楼 **不是** 它的兄弟）
    assert [item["id"] for item in node["replies"]] == [first_reply["id"]]
    # 三楼挂在二楼下面——这就是「第三层没有在响应里丢掉」的断言
    assert [item["id"] for item in node["replies"][0]["replies"]] == [second_reply["id"]]
    assert node["replies"][0]["replies"][0]["content"] == "三楼"


async def test_deep_thread_keeps_every_level(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """五层的链接一字不差地嵌出来。

    为什么要测到五层：任何「只多取一层」的实现（比如把 SQL 写成
    ``parent_id IN (root_ids)``）在两层时与正确的实现完全同形，
    要到三层才会开始丢数据，而且丢得很安静——不会报错，
    只是树上少了一截。五层同时盖住「递归只跑一轮」与「只跑到第 N 层」两种错误。

    同时确认每一条的 ``parent_id`` 就是它的上一条：
    这是「显示 xxx 回复 xxx」能成立的前提。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)

    chain = [await _comment(client, author, post["id"], content="第 1 层")]
    for depth in range(2, 6):
        chain.append(
            await _comment(
                client,
                author,
                post["id"],
                content=f"第 {depth} 层",
                parent_id=chain[-1]["id"],
            )
        )

    for index in range(1, 5):
        assert chain[index]["parent_id"] == chain[index - 1]["id"]

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["total"] == 1  # 五层链接只算一段对话
    node = tree["items"][0]
    for index in range(1, 5):
        assert len(node["replies"]) == 1, f"第 {index + 1} 层应该只有一个孩子"
        node = node["replies"][0]
        assert node["id"] == chain[index]["id"]
        assert node["content"] == f"第 {index + 1} 层"
    assert node["replies"] == []  # 第五层没有下级


async def test_comment_response_carries_author_names(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """响应里带「谁写的 / 回了谁」的**显示名**，前端不需要再回查用户。

    这是界面能渲染「小明 回复 小红」的全部依据：
        响应里只有两个 uuid，让前端拿着 id 去查 ``GET /users/{id}``
        会把一个 N+1 从数据库搬到浏览器（一页几十个请求），
        而且每个请求都得再鉴权一次。

    ``display_name`` 优先、回落 ``username``：
        第三个作者刻意不填 display_name，应当看到用户名（``talk`` 开头）。
    """
    _, alice = await _actor(client, db_session, RoleCode.AUTHOR, display_name="小明")
    _, bob = await _actor(client, db_session, RoleCode.READER, display_name="小红")
    _, carol = await _actor(client, db_session, RoleCode.READER)  # 没填 display_name
    post = await _published_post(client, alice)

    root = await _comment(client, alice, post["id"], content="主楼")
    reply = await _comment(client, bob, post["id"], content="跟一楼", parent_id=root["id"])
    await _comment(client, carol, post["id"], content="也跟一楼", parent_id=root["id"])

    assert root["author_display_name"] == "小明"
    # 根评论没有「被回复者」：两个字段一起为 null，前端只判一次
    assert root["parent_id"] is None
    assert root["parent_author_display_name"] is None

    assert reply["author_display_name"] == "小红"
    assert reply["parent_author_display_name"] == "小明"

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    replies = tree["items"][0]["replies"]
    assert replies[0]["author_display_name"] == "小红"
    assert replies[1]["author_display_name"].startswith("talk")  # 回落成 username
    assert all(item["parent_author_display_name"] == "小明" for item in replies)


async def test_replies_keep_chronological_order(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """回复按时间正序，与根评论一致。

    不能靠「数据库碰巧按插入顺序返回」——没有 ``ORDER BY`` 时
    PostgreSQL 的返回顺序取决于执行计划，换个索引就会变。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="一楼")

    first = await _comment(client, author, post["id"], content="A", parent_id=root["id"])
    second = await _comment(client, reader, post["id"], content="B", parent_id=root["id"])
    third = await _comment(client, author, post["id"], content="C", parent_id=root["id"])

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert [item["id"] for item in tree["items"][0]["replies"]] == [
        first["id"],
        second["id"],
        third["id"],
    ]


async def test_reply_to_unknown_parent_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """回复一个不存在的评论 → 40440（而不是把它当根评论）。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": "回空气", "parent_id": str(uuid4())},
        headers=reader,
    )

    assert response.status_code == 404
    assert response.json()["code"] == COMMENT_NOT_FOUND


async def test_reply_to_parent_of_another_post_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """回复「另一篇文章下的评论」→ 40440。

    这是最容易被漏掉的一条：``parent_id`` 本身是合法的、
    指向的评论也确实存在，只是不属于这篇文章。
    只按 id 判存在性就会让跨文章的回复被接受，
    于是 B 文章的评论出现在了 A 文章的评论树里（而且看起来完全正常）。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post_a = await _published_post(client, author, title="A 文章")
    post_b = await _published_post(client, author, title="B 文章")
    other_root = await _comment(client, reader, post_b["id"], content="B 的评论")

    response = await client.post(
        _comments_url(post_a["id"]),
        json={"content": "错位回复", "parent_id": other_root["id"]},
        headers=reader,
    )

    assert response.status_code == 404
    assert response.json()["code"] == COMMENT_NOT_FOUND


async def test_reply_to_deleted_parent_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """回复一条**已撤回**的评论 → 40440。

    它的正文已经不外传了，新回复挂上去之后读者看到的是一条指向空白的对话，
    像是界面出了 bug——不如直接拒绝。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="我待会撤回")

    assert (await client.delete(_comment_url(root["id"]), headers=reader)).status_code == 204

    response = await client.post(
        _comments_url(post["id"]),
        json={"content": "我还想回", "parent_id": root["id"]},
        headers=author,
    )

    assert response.status_code == 404
    assert response.json()["code"] == COMMENT_NOT_FOUND


# ──────────────────────────── 墓碑与树的分页 ────────────────────────────


async def test_deleted_root_with_replies_stays_as_placeholder(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**撤回是墓碑**：根评论被撤回但回复还在时，位置必须留着。

    这是软删除（而不是 ``DELETE FROM``）在互动上下文里的全部理由。
    如果整棵子树一起消失，B 回复 A 的那段对话就断在半空，
    读者看到的是「一条没有上文的回复」——比一条「该评论已删除」更让人困惑。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="原话")
    reply = await _comment(client, author, post["id"], content="引用它", parent_id=root["id"])

    assert (await client.delete(_comment_url(root["id"]), headers=reader)).status_code == 204

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["total"] == 1  # 占位符仍然算一条根评论
    placeholder = tree["items"][0]
    assert placeholder["id"] == root["id"]
    assert placeholder["is_deleted"] is True
    assert placeholder["content"] == ""  # 原文不外传，但回复还在
    assert [item["id"] for item in placeholder["replies"]] == [reply["id"]]


async def test_deleted_root_without_replies_disappears(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """没有回复的根评论被撤回后彻底从树里消失。

    留一个空占位符在这里没有任何意义——它不承载任何对话，
    只会让评论区顶端挂着一排「该评论已删除」。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="我说错了")

    assert (await client.delete(_comment_url(root["id"]), headers=reader)).status_code == 204

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["items"] == []
    assert tree["total"] == 0


async def test_deleted_reply_disappears_from_the_tree(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**回复**被撤回后直接消失（不占位）。

    与根评论的差别来自「有没有下级」：回复没有下级，
    它自己走了这段对话就结束了，没有谁的上下文被破坏。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="一楼")
    reply = await _comment(client, author, post["id"], content="二楼", parent_id=root["id"])
    kept = await _comment(client, reader, post["id"], content="三楼", parent_id=root["id"])

    assert (await client.delete(_comment_url(reply["id"]), headers=author)).status_code == 204

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert [item["id"] for item in tree["items"][0]["replies"]] == [kept["id"]]


async def test_deleted_mid_level_comment_stays_when_descendants_remain(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**中间层**被撤回且它下面还有人说话时，同样留占位。

    这是「墓碑」在任意深度下唯一自洽的写法：
        判据是「有没有**活着的后代**」，而不是「有没有直接子行」。
        如果按后者判，这里会出现一个很难看的洞——
        中间层被撤回后直接消失，而它的孙子还挂在树上，
        表现为「三楼在回一句不存在的话」，而且 ``parent_id`` 指向的行不在这页。

    构造的正是这个坑：一楼 → 二楼（撤回） → 三楼（还在）。
    二楼自己也是被撤回的，所以它既算“已删除”，又有一个“活着的后代”。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="一楼")
    middle = await _comment(client, author, post["id"], content="二楼", parent_id=root["id"])
    leaf = await _comment(client, reader, post["id"], content="三楼", parent_id=middle["id"])

    assert (await client.delete(_comment_url(middle["id"]), headers=author)).status_code == 204

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    node = tree["items"][0]
    # 二楼留了占位（它下面还有人说话）
    assert [item["id"] for item in node["replies"]] == [middle["id"]]
    placeholder = node["replies"][0]
    assert placeholder["is_deleted"] is True
    assert placeholder["content"] == ""
    # 被回复者的名字照样给出：占位块上写「三楼作者 回复 <谁>」仍然要有名字，
    # 而那条评论的正文已经读不到了——界面因此可以渲染成「回复了已删除的评论」
    assert placeholder["author_display_name"]
    assert [item["id"] for item in placeholder["replies"]] == [leaf["id"]]
    assert placeholder["replies"][0]["is_deleted"] is False
    assert (
        placeholder["replies"][0]["parent_author_display_name"]
        == (placeholder["author_display_name"])
    )


async def test_pagination_counts_roots_not_replies(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """分页单位是**根评论**，回复永远跟着自己的根一起出现。

    如果按单条评论分页，一页里就可能出现「某条回复但它的被回复者不在这页」，
    读者会看到一句莫名其妙的应答。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    roots = []
    for index in range(3):
        root = await _comment(client, reader, post["id"], content=f"第 {index} 楼")
        roots.append(root)
        await _comment(client, author, post["id"], content=f"回复 {index}", parent_id=root["id"])

    first_page = (await client.get(_comments_url(post["id"]), params={"limit": 2})).json()["data"]
    second_page = (
        await client.get(_comments_url(post["id"]), params={"limit": 2, "offset": 2})
    ).json()["data"]

    assert first_page["total"] == 3  # 6 条评论，但只有 3 条根评论
    assert [item["id"] for item in first_page["items"]] == [
        roots[0]["id"],
        roots[1]["id"],
    ]
    assert all(len(item["replies"]) == 1 for item in first_page["items"])
    assert [item["id"] for item in second_page["items"]] == [roots[2]["id"]]


# ──────────────────────────── 撤回评论：归属判定 ────────────────────────────


async def test_author_can_delete_own_comment(client: AsyncClient, db_session: AsyncSession) -> None:
    """作者删自己的评论 → 204，之后从树里消失。

    这里**不**断言响应体为空：本项目的全局响应中间件会把 204 的空体
    也包成 ``{code,data,message}`` 信封（既有行为，M4 的删除接口也一样），
    所以 204 在这个应用里不代表「没有 body」。断言状态码与**效果**即可。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="待会撤回")

    response = await client.delete(_comment_url(root["id"]), headers=reader)

    assert response.status_code == 204

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["items"] == []


async def test_second_delete_returns_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """再删一次 → 40440（未找到），而不是再回一次 204。

    这条与被验的领域不变量直接挂钩：「已撤回的评论对**所有**入口都等同于不存在」。
    如果第二次删除回 204，那个不变量就要开一个例外——而“对已删除的东西操作
    得到 404”与 M4 的 ``DELETE /posts/{id}`` 完全同口径（重复删除文章也是 404）。

    代价写清楚：客户端在超时重试时会拿到 404 而不是 204。
    这里仍然选 404，因为「重试的 DELETE 得到 404 就当作已删除」是客户端
    处理删除重试的标准做法，而为了照顾单个客户端把「已删除」伪装成
    「刚删除」会让整个接口的语义变模糊（服务端无法区分“删了”和“刚删”）。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="删两次")

    assert (await client.delete(_comment_url(root["id"]), headers=reader)).status_code == 204
    second = await client.delete(_comment_url(root["id"]), headers=reader)

    assert second.status_code == 404
    assert second.json()["code"] == COMMENT_NOT_FOUND


async def test_other_user_cannot_delete_comment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """非作者且无特权 → 40340，且评论**没有**被删掉。

    40340 而不是 40440：评论是公开可见的内容，假装它不存在
    既不保护任何东西，又会让调用方以为 id 写错了。
    「权限被拒」和「对象不存在」必须能分辨，否则前端无法给出正确提示。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, writer = await _actor(client, db_session, RoleCode.READER)
    _, stranger = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, writer, post["id"], content="不许删我")

    response = await client.delete(_comment_url(root["id"]), headers=stranger)

    assert response.status_code == 403
    assert response.json()["code"] == COMMENT_FORBIDDEN

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["total"] == 1


async def test_admin_can_delete_any_comment(client: AsyncClient, db_session: AsyncSession) -> None:
    """管理员凭 ``comment:delete_any`` 删别人的评论 → 204。

    处置违规内容不该需要「冒充作者」——这也正是越权位存在的理由。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, writer = await _actor(client, db_session, RoleCode.READER)
    _, admin = await _actor(client, db_session, RoleCode.ADMIN)
    post = await _published_post(client, author)
    root = await _comment(client, writer, post["id"], content="管理员的靶子")

    response = await client.delete(_comment_url(root["id"]), headers=admin)

    assert response.status_code == 204


async def test_forbidden_response_does_not_contain_author_identity(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """40340 的响应里不能带上「这条评论是谁写的」。

    越权失败时把作者 id 回给调用方，等于送出一份
    「谁拥有哪条评论」的对应表——攻击者据此可以挑出
    「最不可能被发现的受害者」来试探。错误体里只需要一个码和一个通用文案。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    writer_id, writer = await _actor(client, db_session, RoleCode.READER)
    _, stranger = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, writer, post["id"], content="别看我")

    body = (await client.delete(_comment_url(root["id"]), headers=stranger)).json()

    assert body["code"] == COMMENT_FORBIDDEN
    assert "author_id" not in body
    assert writer_id not in str(body)


async def test_deleting_unknown_comment_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """删一个不存在的评论 → 40440。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)

    response = await client.delete(_comment_url(uuid4()), headers=author)

    assert response.status_code == 404
    assert response.json()["code"] == COMMENT_NOT_FOUND


async def test_anonymous_cannot_delete_comment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """未登录删评论 → 401。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, reader, post["id"], content="游客别动")

    response = await client.delete(_comment_url(root["id"]))

    assert response.status_code == 401


# ──────────────────────────── 重复点赞不重复计数 ────────────────────────────


async def test_like_toggle_flips_state_and_count(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**验收标准 ①**的 HTTP 侧：一次点击改变状态，再一次撤销。

    响应里回的是**操作之后的真实计数**（现查聚合），
    不是前端 ±1 猜出来的数字——后者在并发下会互相覆盖。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    liked = await _like(client, reader, post["id"])
    assert liked == {
        "target_type": "post",
        "target_id": post["id"],
        "liked": True,
        "like_count": 1,
    }

    unliked = await _like(client, reader, post["id"])
    assert unliked["liked"] is False
    assert unliked["like_count"] == 0


async def test_repeated_like_does_not_double_count(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """**验收标准 ①**：同一个用户重复点赞不会造出第二行、也不会重复计数。

    这是本文件里唯一一条**不走 HTTP** 的用例，原因值得写清楚：
        走 HTTP 时这个场景只能表现为「并发连点」——两个请求同时读到
        「未点赞」，于是都执行插入。而测试客户端把整条依赖链接到同一个
        ``AsyncSession`` 上，并发请求会撞在同一个会话上（那是测试基础设施的
        限制，不是被测代码的 bug），所以只能在**仓储这一层**复现这个竞态。

    ``like()`` 用 ``INSERT ... ON CONFLICT DO NOTHING`` 实现，
    于是「重复插入」是一个数据库级空操作：
        哪怕两个并发请求都通过了 ``is_liked`` 检查，最终也只有一行。
    这条用例正是不让任何人把 ``ON CONFLICT`` 改成「先查再插」的护栏——
    后者在并发下必然产生两行，而点赞数会永久偏大。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    reader_id, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    repository = SqlLikeRepository(db_session)

    await repository.like(UUID(reader_id), target_type="post", target_id=UUID(str(post["id"])))
    await repository.like(UUID(reader_id), target_type="post", target_id=UUID(str(post["id"])))

    rows = await db_session.scalar(
        select(func.count()).select_from(LikeModel).where(LikeModel.user_id == UUID(reader_id))
    )
    assert rows == 1

    # 再走一次 HTTP 确认计数与行数一致（1 而不是 2）
    assert (await _stats(client, post["id"]))["like_count"] == 1
    assert (await _like(client, reader, post["id"]))["liked"] is False  # 已赞过 → 这次是取消


async def test_like_count_aggregates_across_users(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """不同用户各点一次 → 计数 2。

    与上一条互为对照：去重只针对「同一个人 + 同一个目标」，
    不能宽到把不同人也当成重复。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, first = await _actor(client, db_session, RoleCode.READER)
    _, second = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)

    assert (await _like(client, first, post["id"]))["like_count"] == 1
    assert (await _like(client, second, post["id"]))["like_count"] == 2

    # 第一个人再点一次是「取消」，计数回到 1
    assert (await _like(client, first, post["id"]))["like_count"] == 1


async def test_likes_on_post_and_comment_are_separate(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """文章与评论的赞互相独立（多态目标不能串味）。

    ``(user_id, target_type, target_id)`` 的唯一约束必须带上 ``target_type``——
    否则「先赞了某篇文章、再去赞一条 id 恰好相同的评论」会被判成重复，
    表现为「我点不动某个赞」这种毫无线索的 bug。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    comment = await _comment(client, reader, post["id"], content="给我点个赞")

    post_like = await _like(client, reader, post["id"], target_type="post")
    comment_like = await _like(client, reader, comment["id"], target_type="comment")

    assert post_like["like_count"] == 1
    assert comment_like["like_count"] == 1

    tree = (await client.get(_comments_url(post["id"]))).json()["data"]
    assert tree["items"][0]["like_count"] == 1
    assert (await _stats(client, post["id"]))["like_count"] == 1


async def test_like_unknown_target_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """不存在的目标 → 40441（先判存在，再写库）。"""
    _, reader = await _actor(client, db_session, RoleCode.READER)

    post_response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": str(uuid4())},
        headers=reader,
    )
    comment_response = await client.post(
        LIKE_URL,
        json={"target_type": "comment", "target_id": str(uuid4())},
        headers=reader,
    )

    assert post_response.status_code == 404
    assert post_response.json()["code"] == TARGET_NOT_FOUND
    assert comment_response.status_code == 404
    assert comment_response.json()["code"] == TARGET_NOT_FOUND


async def test_like_draft_of_other_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """给别人草稿点赞 → 40441（而不是 40940，也不是文章上下文的 40430）。

    这是「看不见的东西等于不存在」在点赞接口上的落点。
    如果这里回 40940（存在但未发布），这个接口就成了存在性探测器：
    拿一个 id 试一次就能确认「确实有这篇草稿」。

    码是 40441 而不是 40430：点赞接口的目标是多态的，它的词汇里没有
    「文章」，所以「目标不存在」只应有 40441 一个答案。
    不然同一个「对你不存在的 id」会因为底层行是否物理存在而给出两个码，
    前端得为同一件事写两条分支。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    draft = await _draft_post(client, author)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": draft["id"]},
        headers=reader,
    )

    assert response.status_code == 404
    assert response.json()["code"] == TARGET_NOT_FOUND


async def test_like_own_draft_returns_409(client: AsyncClient, db_session: AsyncSession) -> None:
    """给自己的草稿点赞 → 40940（看得见，但互动没开放）。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    draft = await _draft_post(client, author)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": draft["id"]},
        headers=author,
    )

    assert response.status_code == 409
    assert response.json()["code"] == INTERACTION_CLOSED


async def test_like_deleted_comment_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """给已撤回的评论点赞 → 40441。

    撤回的语义是「这段话不再存在」，那么它的赞数也不该存在——
    否则一条看不见的评论会永远挂在某个数字上。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    comment = await _comment(client, reader, post["id"], content="撤回前的遗言")

    assert (await client.delete(_comment_url(comment["id"]), headers=reader)).status_code == 204

    response = await client.post(
        LIKE_URL,
        json={"target_type": "comment", "target_id": comment["id"]},
        headers=reader,
    )

    assert response.status_code == 404
    assert response.json()["code"] == TARGET_NOT_FOUND


async def test_like_archived_post_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """已归档文章不能被点赞 → 40940（由**作者本人**发起）。

    必须用作者来点，不能用读者：归档后文章对外不可见，
    读者请求会在 ``ensure_visible_to`` 就先得到 40441（看不见等于不存在），
    根本走不到「互动是否开放」这一步。
    这与 M4 的可见性规则一致，也说明两道门是有先后的：可见 → 开放。

    已有点赞仍然显示（数据没删），只是不再接受新的。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)
    await client.post(f"{POSTS_URL}/{post['id']}/unpublish", headers=author)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": post["id"]},
        headers=author,
    )

    assert response.status_code == 409
    assert response.json()["code"] == INTERACTION_CLOSED


async def test_invalid_target_type_returns_40041(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """非法 ``target_type`` → 40041，而不是 40000。

    区分很重要：40000 说明客户端把字段**形状**写错了（该传字符串却传了数组），
    40041 说明形状是对的、**取值**不在允许范围内。
    两个码对应两个完全不同的修复方向，合并成一个会让排查多绕一圈。
    这里也不用 ``Literal`` 让 Pydantic 去拦——那样出来的就是 40000 了，
    而且领域里那份「合法取值」列表会在边界处被复制第二遍。
    """
    _, reader = await _actor(client, db_session, RoleCode.READER)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "posts", "target_id": str(uuid4())},
        headers=reader,
    )

    assert response.status_code == 400
    assert response.json()["code"] == INVALID_LIKE_TARGET


async def test_anonymous_cannot_like(client: AsyncClient, db_session: AsyncSession) -> None:
    """未登录点赞 → 401。

    点赞是一人一票的记录，必须知道是谁——匿名点赞就没有
    「我赞过没」这个概念了，是另一种产品。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    post = await _published_post(client, author)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": post["id"]},
    )

    assert response.status_code == 401


async def test_like_toggle_requires_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """无 ``like:toggle`` 的登录用户 → 40320。"""
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, nobody = await _actor(client, db_session)
    post = await _published_post(client, author)

    response = await client.post(
        LIKE_URL,
        json={"target_type": "post", "target_id": post["id"]},
        headers=nobody,
    )

    assert response.status_code == 403
    assert response.json()["code"] == PERMISSION_DENIED


# ──────────────────────────── 互动统计（读侧） ────────────────────────────


async def test_stats_are_public_and_zero_for_unknown_post(client: AsyncClient) -> None:
    """统计公开可读；不存在的文章给全 0 而不是 404。

    不返回 404 是刻意的：这个接口需要能同时服务列表页（一次问多篇），
    而列表页里出现一篇刚好被删掉的文章不该让整页 404。
    它能泄露的信息为零——不返回任何标题或正文。
    """
    response = await client.get(_stats_url(uuid4()))

    assert response.status_code == 200
    assert response.json()["data"]["like_count"] == 0
    assert response.json()["data"]["comment_count"] == 0
    assert response.json()["data"]["liked_by_me"] is False


async def test_stats_reflect_likes_and_comments(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """统计 = 文章的赞数 + 未撤回的评论总数（根评论与回复都算）。

    注意两个数字口径不同且都对：
        ``like_count`` 只算**文章本身**的赞（评论的赞在各自的节点上），
        ``comment_count`` 算全部评论（评论区的规模）。
        界面上前者是作者的影响力，后者是讨论的热度。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, first = await _actor(client, db_session, RoleCode.READER)
    _, second = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, first, post["id"], content="一楼")
    await _comment(client, second, post["id"], content="二楼", parent_id=root["id"])

    await _like(client, first, post["id"])
    await _like(client, second, post["id"])

    stats = await _stats(client, post["id"])
    assert stats["post_id"] == post["id"]
    assert stats["like_count"] == 2
    assert stats["comment_count"] == 2
    assert stats["liked_by_me"] is False  # 匿名访问者


async def test_stats_liked_by_me_is_per_viewer(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``liked_by_me`` 随访问者变化，而 ``like_count`` 不变。

    按钮的初值必须来自服务端：只靠 toggle 的响应的话，
    已点赞的人一进页面看到的是「未点赞」，点一下反而是**取消**——
    这个按钮在第一次点击之前一直在骗人。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, liker = await _actor(client, db_session, RoleCode.READER)
    _, other = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    await _like(client, liker, post["id"])

    liker_view = (await client.get(_stats_url(post["id"]), headers=liker)).json()["data"]
    other_view = (await client.get(_stats_url(post["id"]), headers=other)).json()["data"]

    assert liker_view["liked_by_me"] is True
    assert other_view["liked_by_me"] is False
    assert liker_view["like_count"] == other_view["like_count"] == 1


async def test_stats_comment_count_excludes_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """统计里的评论数不算已撤回的。

    「有多少条评论」是给读者看的社区规模，不是审计口径。
    已撤回的评论对外不存在，它就不该出现在这个数字里。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, reader = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    await _comment(client, reader, post["id"], content="留下的")
    removed = await _comment(client, reader, post["id"], content="要撤回的")

    assert (await client.delete(_comment_url(removed["id"]), headers=reader)).status_code == 204

    stats = await _stats(client, post["id"])
    assert stats["comment_count"] == 1  # 发出过两条，撤回一条


async def test_comment_response_exposes_like_count_and_liked_by_me(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """评论树里每条评论都带自己的赞数与「我赞过没」。

    读评论时顺带把赞带上（一次批量查询），前端就不用为每条评论
    各发一个请求——那正是 N+1。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    _, liker = await _actor(client, db_session, RoleCode.READER)
    post = await _published_post(client, author)
    root = await _comment(client, author, post["id"], content="值得一赞")
    await _like(client, liker, root["id"], target_type="comment")

    anonymous = (await client.get(_comments_url(post["id"]))).json()["data"]["items"][0]
    as_liker = (await client.get(_comments_url(post["id"]), headers=liker)).json()["data"]["items"][
        0
    ]

    assert anonymous["like_count"] == as_liker["like_count"] == 1
    assert anonymous["liked_by_me"] is False
    assert as_liker["liked_by_me"] is True


async def test_blog_endpoints_still_work_after_permission_catalog_change(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """回归护栏：互动接口不影响现有文章接口。

    M5 改了 ``models/__init__.py``（多注册两张表）与权限目录（多了 4 个码）。
    这一条跑的是 M4 的接口，但依赖 M5 改过的那张权限表——
    把「改权限矩阵时顺手改坏了别的接口」这类回归钉住。
    """
    _, author = await _actor(client, db_session, RoleCode.AUTHOR)
    await _published_post(client, author)

    response = await client.get(MY_POSTS_URL, headers=author)

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
