"""博客相关的请求 / 响应 Schema（HTTP 边界）。

这是**唯一**该做参数格式校验的地方：请求一到这层立刻被规矩住，
验证通过后进入应用层的就是已经干净的数据。

响应模型与领域实体刻意不复用同一套类（与 ``schemas/auth.py`` 同一原则）：
    出参是给外部看的**契约**，字段一旦发出去就很难收回。
    让它和实体分开，实体加一个内部字段时不会「顺手」泄露到 API。

关于长度常量：这里直接 import 领域的值对象常量，而不是像 ``schemas/auth.py``
那样在本地再写一遍数字。理由是这个上下文的限额多且不好记
（正文上限 100_000、标签最多 10 个），手抄一遍极易抄错，
而抄错的表现是「schema 放行了、值对象拒绝」——一个只在极端输入下才出现的 400。
``auth.py`` 那边数字少且都是小整数，两者取向不同是有意的。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.application.blog.dto import PostDetailDTO, PostPageDTO
from app.domain.blog.value_objects import (
    MAX_TAGS_PER_POST,
    POST_CONTENT_MAX_LEN,
    POST_COVER_URL_MAX_LEN,
    POST_SLUG_MAX_LEN,
    POST_SUMMARY_MAX_LEN,
    POST_TITLE_MAX_LEN,
    TAG_NAME_MAX_LEN,
)

# 单个标签名的长度约束。写成 Annotated 而不是在每个字段上重复一遍 Field(...)
TagNameField = Annotated[str, Field(min_length=1, max_length=TAG_NAME_MAX_LEN)]


# ──────────────────────────── 请求 ────────────────────────────


class CreatePostRequest(BaseModel):
    """新建文章入参。

    没有 ``status`` 字段：新建一律落草稿（见 ``CreatePostUseCase`` 的说明）。
    让客户端能在这里指定 published 等于开了第二条发布路径，
    状态机就不再只有一条入口了。

    没有 ``author_id`` 字段：作者是**从 token 推导**出来的，不是客户端说了算。
    如果让请求体带上它，任何人都能以别人的名义发文章。
    """

    title: str = Field(
        min_length=1,
        max_length=POST_TITLE_MAX_LEN,
        description=f"标题，1~{POST_TITLE_MAX_LEN} 字",
    )
    content: str = Field(
        min_length=1,
        max_length=POST_CONTENT_MAX_LEN,
        description=f"正文（Markdown），1~{POST_CONTENT_MAX_LEN} 字",
    )
    summary: str | None = Field(
        default=None,
        max_length=POST_SUMMARY_MAX_LEN,
        description="摘要，留空则列表里截取正文",
    )
    slug: str | None = Field(
        default=None,
        max_length=POST_SLUG_MAX_LEN,
        description="永久链接；留空则由标题生成，撞车时自动加序号",
    )
    cover_url: str | None = Field(
        default=None,
        max_length=POST_COVER_URL_MAX_LEN,
        description="封面图 URL",
    )
    tag_names: list[TagNameField] = Field(
        default_factory=list,
        max_length=MAX_TAGS_PER_POST,
        description=f"标签名列表，最多 {MAX_TAGS_PER_POST} 个，不存在的标签会自动创建",
    )


class UpdatePostRequest(BaseModel):
    """编辑文章入参（PATCH 语义）。

    全部字段可选，**未出现**与**显式 null** 含义不同：
        未出现的字段在 ``model_dump(exclude_unset=True)`` 里根本不存在，
        于是用例收到 ``UNSET``，意思是「不改动」；
        显式 ``"summary": null`` 会出现在 dump 里，用例收到 ``None``，意思是「清空」。
    这正是为什么表现层必须用 ``exclude_unset=True``：
    直接 ``model_dump()`` 会把「没传的字段」也填成 None，于是一次「只改标题」的保存
    会把摘要、封面、标签全部清空——一个非常容易被漏测的数据丢失。

    ``slug`` 单独说明：它写成 ``str | None`` 是为了接受 JSON 里的 null，
    但真值为 null 时会被表现层**过滤掉**（不是清空，也不是报错）——
    slug 是 NOT NULL 的永久链接，没有「清空」这个合法状态。
    """

    title: str | None = Field(
        default=None,
        max_length=POST_TITLE_MAX_LEN,
        description="标题；不传表示不改",
    )
    content: str | None = Field(
        default=None,
        max_length=POST_CONTENT_MAX_LEN,
        description="正文；不传表示不改",
    )
    summary: str | None = Field(
        default=None,
        max_length=POST_SUMMARY_MAX_LEN,
        description="摘要；传 null 表示清空",
    )
    slug: str | None = Field(
        default=None,
        max_length=POST_SLUG_MAX_LEN,
        description="永久链接；null 会被忽略（没有清空这个状态）",
    )
    cover_url: str | None = Field(
        default=None,
        max_length=POST_COVER_URL_MAX_LEN,
        description="封面图 URL；传 null 表示清空",
    )
    tag_names: list[TagNameField] | None = Field(
        default=None,
        max_length=MAX_TAGS_PER_POST,
        description=f"标签名列表（整体替换）；传 null 表示清空，最多 {MAX_TAGS_PER_POST} 个",
    )


# ──────────────────────────── 响应 ────────────────────────────


class PostSummaryResponse(BaseModel):
    """文章摘要出参（列表项）。

    ``author_id`` 只给 id，不给作者名：
        带上作者名就要在这一层再查一次 users 表（或让仓储 JOIN），
        而本期列表页并不展示作者——先不加。需要时再扩展，
        比先塞进去再删掉一个已发布字段容易得多。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID
    title: str
    slug: str
    summary: str | None = None
    cover_url: str | None = None
    status: str
    published_at: datetime | None = None
    view_count: int
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PostDetailResponse(PostSummaryResponse):
    """文章详情出参 = 摘要字段 + 正文。

    用**继承**而不是把 DTO 的 ``summary_fields`` 原样嵌进来：
        应用层的 ``PostDetailDTO`` 是「摘要 + 正文」的组合，
        那是为了让摘要逻辑只有一份实现；但对外契约不需要暴露这个组合结构。
        前端拿到的应该是一个扁平对象——嵌套一层 ``summary_fields``
        只会让每个用到详情的地方都多写一层属性访问。

    继承同时保证了「详情里的摘要字段和列表里的**是同一组字段**」，
    两边不会各自演化出不一致的字段集。
    """

    content: str

    @classmethod
    def from_dto(cls, dto: PostDetailDTO) -> PostDetailResponse:
        """把组合式的应用层 DTO 摊平成对外契约。"""
        summary = PostSummaryResponse.model_validate(dto.summary_fields)
        return cls(**summary.model_dump(), content=dto.content)


class PostPageResponse(BaseModel):
    """文章分页出参。"""

    items: list[PostSummaryResponse]
    total: int = Field(description="总条数（不只是本页），前端据它算总页数")
    offset: int = Field(description="本页起点，已被服务端收敛到合法区间")
    limit: int = Field(description="本页最大条数，已被服务端收敛到合法区间")

    @classmethod
    def from_dto(cls, dto: PostPageDTO) -> PostPageResponse:
        """从应用层的分页 DTO 构造响应。"""
        return cls(
            items=[PostSummaryResponse.model_validate(item) for item in dto.items],
            total=dto.total,
            offset=dto.offset,
            limit=dto.limit,
        )


__all__ = [
    "CreatePostRequest",
    "PostDetailResponse",
    "PostPageResponse",
    "PostSummaryResponse",
    "UpdatePostRequest",
]
