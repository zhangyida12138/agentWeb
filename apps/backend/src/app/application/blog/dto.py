"""博客上下文的应用层 DTO。

入参（``*Command`` / ``*Query``）与出参（``*DTO``）一律标准库 dataclass，
理由见 ``application/identity/dto.py`` 顶部：参数格式校验归表现层 schema，
序列化格式同理——应用层承载的是「已经合法的数据」。

出参刻意分成 **摘要视图** 与 **详情视图** 两个类，而不是一个类加上
``content: str | None``：

    列表接口一页 20 篇，若带上正文，一页响应可能是 2MB——
    而列表页一个字都不显示正文。用一个「什么字段都可能为 None」的类去覆盖两种场景，
    代价是每个读到 ``post.content`` 的地方都得先判空，
    而判空的正确分支又取决于「我这个响应是列表还是详情」——
    这份信息在类型里丢掉了。两个类各自字段确定，反而更简单。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.blog.entities import UNSET, Post, Unset

# ──────────────────────────── 入参：Command ────────────────────────────


@dataclass(frozen=True, slots=True)
class CreatePostCommand:
    """新建文章命令。

    ``author_id`` 由表现层从当前登录用户注入，**绝不**从请求体里读：
        一旦允许客户端指定作者，任何人都能以别人的名义发文。
        把「作者是谁」从入参里彻底移除，这个漏洞在类型层面就不存在。
    """

    author_id: uuid.UUID
    title: str
    content: str
    summary: str | None = None
    # ``None`` 表示「按标题自动生成」。客户端不需要为 slug 操心，
    # 想指定时才填——这是「零配置也能用」的默认值选择。
    slug: str | None = None
    cover_url: str | None = None
    tag_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdatePostCommand:
    """编辑文章命令（PATCH 语义）。

    ``slug`` 的类型是 ``str | Unset``（**没有** ``None``）：
        对 slug 来说 ``None`` 不是一个有意义的输入——「把 slug 清空」是不允许的。
        去掉 ``None`` 之后，表现层把 ``"slug": null`` 过滤掉再构造命令，
        用例这侧就不必再写一次「万一是 None 怎么办」。
    """

    post_id: uuid.UUID
    actor_id: uuid.UUID
    # 由表现层查出来的「调用者是否持有 post:update_any」。
    # 为什么由外面传进来而不是用例自己去查：
    #   权限查询要访问 AccessRepository，而那是另一个上下文的仓储。
    #   让 blog 的用例直接依赖它，会把两个上下文焊死在一起；
    #   表现层本来就是「装配所有上下文」的地方，由它算好再传，依赖方向最干净。
    actor_can_override: bool = False

    title: str | Unset = UNSET
    content: str | Unset = UNSET
    summary: str | Unset | None = UNSET
    slug: str | Unset = UNSET
    cover_url: str | Unset | None = UNSET
    tag_names: tuple[str, ...] | Unset = UNSET


@dataclass(frozen=True, slots=True)
class ChangePostStatusCommand:
    """状态流转命令（发布 / 下架共用）。

    两个动作共用同一个入参形状，所以不再拆成 ``PublishPostCommand`` /
    ``UnpublishPostCommand`` 两个只差一个布尔值的类；
    「要做什么」体现在调用哪个用例方法上（``execute`` vs ``execute_unpublish``），
    没有「传错布尔值就在做另一件事」的风险。
    """

    post_id: uuid.UUID
    actor_id: uuid.UUID
    actor_can_override: bool = False


@dataclass(frozen=True, slots=True)
class DeletePostCommand:
    """删除文章命令。"""

    post_id: uuid.UUID
    actor_id: uuid.UUID
    actor_can_override: bool = False


# ──────────────────────────── 入参：Query ────────────────────────────


@dataclass(frozen=True, slots=True)
class ListPublishedPostsQuery:
    """公开文章列表查询。"""

    offset: int
    limit: int
    tag_name: str | None = None


@dataclass(frozen=True, slots=True)
class ListMyPostsQuery:
    """我的文章列表查询。

    ``status`` 允许为空（看全部），允许 ``draft`` / ``published`` / ``archived``。
    """

    author_id: uuid.UUID
    offset: int
    limit: int
    status: str | None = None


@dataclass(frozen=True, slots=True)
class GetPostQuery:
    """按 slug 查单篇（公开阅读入口）。

    ``viewer_id`` 可以为 ``None``（未登录访客）：
        它能看到的只有已发布的文章。作者的草稿预览能成立，
        正是因为请求带上了 token、``viewer_id`` 等于作者自己的 id。
    """

    slug: str
    viewer_id: uuid.UUID | None = None


# ──────────────────────────── 出参：DTO ────────────────────────────


@dataclass(frozen=True, slots=True)
class PostSummaryDTO:
    """列表项的公共字段（不含正文）。"""

    id: uuid.UUID
    author_id: uuid.UUID
    title: str
    slug: str
    summary: str | None
    cover_url: str | None
    status: str
    published_at: datetime | None
    view_count: int
    tags: tuple[str, ...]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, post: Post) -> PostSummaryDTO:
        """领域实体 → 摘要视图。

        取不到 id 说明实体还没落库就被拿去构造响应了——这是编程错误，
        必须当场炸掉，而不是在响应里塞 ``None`` 让前端拿到空 id
        （与 ``UserDTO.from_entity`` 同一套判断）。
        """
        if post.id is None:
            msg = "PostSummaryDTO 只能由已持久化的实体构造（此时 id 必然已生成）"
            raise ValueError(msg)
        return cls(
            id=post.id,
            author_id=post.author_id,
            title=post.title.value,
            slug=post.slug.value,
            summary=post.summary,
            cover_url=post.cover_url,
            status=post.status,
            published_at=post.published_at,
            view_count=post.view_count,
            # 值对象在出口处才降级成字符串：领域内部用 TagName 保证合法，
            # 到了 DTO 这一层只剩「展示」这一件事，没必要让前端也理解值对象
            tags=tuple(str(tag) for tag in post.tags),
            created_at=post.created_at,
            updated_at=post.updated_at,
        )


@dataclass(frozen=True, slots=True)
class PostDetailDTO:
    """详情视图 = 摘要视图的全部字段 + 正文。

    用**组合**（持有一个 ``PostSummaryDTO``）而不是复制一遍字段：
        「详情比摘要多一个 content」这条关系写进类型里，
        以后给摘要视图加字段（比如评论数），详情视图自动跟上，不会漏。
        代价是出参 JSON 会变成嵌套结构 ``{...summary, "content": ...}``，
        所以表现层 schema 要做一次扁平化（见 ``schemas/post.py::PostDetailResponse``）。
    """

    summary_fields: PostSummaryDTO
    content: str

    @classmethod
    def from_entity(cls, post: Post) -> PostDetailDTO:
        return cls(summary_fields=PostSummaryDTO.from_entity(post), content=post.content.value)


@dataclass(frozen=True, slots=True)
class PostPageDTO:
    """分页出参。

    ``offset`` / ``limit`` 原样回显**归一化后**的值，而不是客户端传来的值：
        客户端传 ``limit=1000`` 会被夹到 100，如果回显 1000，
        前端会以为「我要了 1000 条，后端给了 20 条」，然后算出错误的页数。
        回显实际生效值，前端拿到的分页算术才是可对齐的。
    """

    items: tuple[PostSummaryDTO, ...]
    total: int
    offset: int
    limit: int


__all__ = [
    "UNSET",
    "ChangePostStatusCommand",
    "CreatePostCommand",
    "DeletePostCommand",
    "GetPostQuery",
    "ListMyPostsQuery",
    "ListPublishedPostsQuery",
    "PostDetailDTO",
    "PostPageDTO",
    "PostSummaryDTO",
    "Unset",
    "UpdatePostCommand",
]
