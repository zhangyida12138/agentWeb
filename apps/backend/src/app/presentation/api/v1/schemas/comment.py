"""互动上下文：评论的请求 / 响应 Schema（HTTP 边界）。

与 ``schemas/post.py`` 同一套原则：
    请求 schema 只做**格式**校验（长度、类型、必填），
    真正的业务判断（内容 strip 后非空）还是由 ``CommentContent`` 值对象做——
    schema 是第二道防线，不是唯一一道。

响应结构与 ``CommentNodeDTO`` 一一对应，包括**递归的 replies**：
    评论树是自引用结构，响应模型也必须自引用，否则前端就得在两套
    「跟帖」和「回复」的类型之间转换。
    递归深度不设限（树的形状是数据决定的），缩进级数是**界面**的事。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.application.interaction.dto import CommentNodeDTO, CommentThreadDTO
from app.domain.interaction.value_objects import COMMENT_CONTENT_MAX_LEN

# ──────────────────────────── 请求 ────────────────────────────


class CreateCommentRequest(BaseModel):
    """发表评论入参。

    没有 ``post_id`` 字段：文章由**路径**决定（``POST /posts/{post_id}/comments``）。
    如果让请求体再带一个 post_id，就会出现「路径说 A、体里说 B」的冲突输入，
    而无论怎么裁决，都有一半调用方会拿到与自己预期相反的结果。

    没有 ``author_id`` 字段：作者从 token 推导，不由客户端声明。

    ``parent_id`` 传 null / 不传 = 发表根评论；传一个 id = 回复那条评论。
    它是不是「这条评论的回复」由**用例**去校验（必须属于同一篇文章、
    且未被撤回），schema 只能确认它是一个 UUID。

    ``parent_id`` 可以指向**任意一条**评论，包括一条回复：
        那时它会原样落库（不归一到根），于是树可以一直深下去，
        而界面从第二层起就不再缩进（缩进是展示决策，不是数据约束）。
    """

    content: str = Field(
        min_length=1,
        max_length=COMMENT_CONTENT_MAX_LEN,
        description=f"评论内容，1~{COMMENT_CONTENT_MAX_LEN} 字（首尾空白会被忽略）",
    )
    parent_id: uuid.UUID | None = Field(
        default=None,
        description="要回复的评论 id；不传表示发表根评论",
    )


# ──────────────────────────── 响应 ────────────────────────────


class CommentResponse(BaseModel):
    """一条评论（含它下面的回复）。

    ``content`` 在被撤回时是**空串**，同时 ``is_deleted`` 为 true：
        前端据此渲染「该评论已删除」的占位块。
        为什么不干脆不给这条记录：因为它的回复还在，抹掉它会让那些回复
        变成一串没有上下文的句子。
        为什么内容一定不传：撤回的语义就是「读不到了」。内容仍留在库里
        （管理员可追溯），但绝不能出现在响应里——那等于撤回没生效。

    ``author_display_name`` / ``parent_author_display_name`` 是**已经解析好的名字**：
        界面要显示「小明 回复 小红」。如果只给 id，前端只能拿着去问
        ``GET /users/{id}``，那就是把 N+1 从数据库搬到了浏览器（一页几十个请求），
        而且每个请求都要再过一遍鉴权。名字在这里是**展示字段**，
        不是另一个实体的引用，所以直接给字符串。

        ``parent_author_display_name`` 与 ``parent_id`` 同生共死：
            根评论两者都是 null。界面因此可以只看这对字段就决定
            要不要渲染「回复 xxx」，不需要自己判两次。

    ``replies`` 是**任意深度**的递归，不是只有两层：
        为此专门有一条集成测试造出 3 层链，确认第三层不会在响应里消失。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    post_id: uuid.UUID
    author_id: uuid.UUID
    author_display_name: str = Field(description="评论者显示名（display_name 优先，回落 username）")
    parent_id: uuid.UUID | None = None
    parent_author_display_name: str | None = Field(
        default=None,
        description="被回复者的显示名；根评论为 null",
    )
    content: str
    is_deleted: bool
    like_count: int
    liked_by_me: bool
    created_at: datetime
    updated_at: datetime
    replies: list[CommentResponse] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, dto: CommentNodeDTO) -> CommentResponse:
        """把应用层节点 DTO 递归翻译成响应。

        手写递归而不是靠 ``model_validate(dto)`` 的嵌套自动转换：
            自动转换会依赖 ``from_attributes`` 在嵌套位置是否生效、
            以及元组→列表的隐式转换这些细节。这些行为都没错，
            但它们**没有出现在这段代码里**，所以读到这里的人无法确认
            「回复到底会不会被带上」。显式写出来，行为就是可读的。

        递归在这里是安全的：它的深度就是树的深度（见 ``CommentNodeDTO``），
        而树深受真实对话长度限制，不会撞栈。
        """
        return cls(
            id=dto.id,
            post_id=dto.post_id,
            author_id=dto.author_id,
            author_display_name=dto.author_display_name,
            parent_id=dto.parent_id,
            parent_author_display_name=dto.parent_author_display_name,
            content=dto.content,
            is_deleted=dto.is_deleted,
            like_count=dto.like_count,
            liked_by_me=dto.liked_by_me,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
            replies=[CommentResponse.from_dto(child) for child in dto.replies],
        )


class CommentPageResponse(BaseModel):
    """评论分页出参。"""

    items: list[CommentResponse]
    total: int = Field(description="根评论总数（分页单位是「一段对话」而不是单条评论）")
    offset: int = Field(description="本页起点，已被服务端收敛到合法区间")
    limit: int = Field(description="本页最大条数，已被服务端收敛到合法区间")

    @classmethod
    def from_dto(cls, dto: CommentThreadDTO) -> CommentPageResponse:
        return cls(
            items=[CommentResponse.from_dto(item) for item in dto.items],
            total=dto.total,
            offset=dto.offset,
            limit=dto.limit,
        )


__all__ = [
    "CommentPageResponse",
    "CommentResponse",
    "CreateCommentRequest",
]
