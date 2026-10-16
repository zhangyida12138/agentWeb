"""标签相关的请求 / 响应 Schema（HTTP 边界）。

这一层是**唯一**做参数格式校验的地方。校验通过后进入应用层的，
就是「已经是干净数据」的 ``*Command`` / ``*Query``。

长度常量一律 import 领域的值对象常量，不在本地重写数字：
    ``TagName`` 的上限（50）由 ``domain/blog/value_objects.py`` 定义、
    由 ``domain/tag/value_objects.py`` 转出。如果这里手抄一个 30，
    表现会是「schema 放行了、值对象拒绝」——一个只在边界输入下才出现的 400，
    而且在两个文件里各写一遍数字，改一处忘一处是必然结果。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.application.tag.dto import TagPageDTO
from app.domain.tag.value_objects import TAG_DESCRIPTION_MAX_LEN, TAG_NAME_MAX_LEN

# 标签名的请求体约束。写成 Annotated 而不是在每个字段上重复 Field(...)：
# 一个字段用两次（创建、编辑），重复写就会有一天只改到其中一处。
TagNameField = Annotated[str, Field(min_length=1, max_length=TAG_NAME_MAX_LEN)]
TagDescriptionField = Annotated[str, Field(max_length=TAG_DESCRIPTION_MAX_LEN)]


# ──────────────────────────── 请求 ────────────────────────────


class CreateTagRequest(BaseModel):
    """新建标签入参。

    没有 ``author_id`` 字段：
        创建者是**从 token 推导**出来的，不是客户端说了算。
        让请求体带上它，任何管理员都能以别人的名义建标签，
        而「谁该对这个标签负责」这条信息一旦可以伪造，归属校验就没有意义了。

    没有 ``status`` 字段：
        新建的标签**一定**是 ``normal``。允许建一个落地即 ``deleted``
        的标签只是给自己留一个必须记得清理的东西；
        要下架，建好之后调状态接口就行。
    """

    name: TagNameField = Field(description=f"标签名，1~{TAG_NAME_MAX_LEN} 字；网址部分由它自动生成")
    description: TagDescriptionField | None = Field(
        default=None,
        description=f"说明文字，最多 {TAG_DESCRIPTION_MAX_LEN} 字；标签多了以后它比名字更有用",
    )
    type: str = Field(
        default="user",
        description="标签类型：user（普通）/ system（平台内置，只有管理员能建）",
    )


class UpdateTagRequest(BaseModel):
    """编辑标签入参（**PUT** 语义：整份表示一起提交）。

    ⚠️ 与 ``UpdatePostRequest`` 相反，这里**不是 PATCH**：
        标签只有两个可编辑的标量字段，`PUT` 的「没传 = 清空」不会造成意外丢失——
        前端本来就是一个「名称 + 描述」的表单，提交时两个字段都在。
        而 PATCH 需要表现层用 ``exclude_unset=True`` 才能区分
        「没传」与「传了 null」，那套哨兵机制在这里没有换来任何好处，
        只换来一个必须记住的额外约定。

        ``description`` 因此就是 ``None`` = 没有描述，没有第三种含义。
    """

    name: TagNameField = Field(description=f"标签名，1~{TAG_NAME_MAX_LEN} 字；改名会重算网址")
    description: TagDescriptionField | None = Field(
        default=None,
        description="说明文字；传 null 或不传都表示清空",
    )


class ChangeTagStatusRequest(BaseModel):
    """变更标签状态入参（下架 / 恢复）。

    只有管理员能到达这个接口（路由上挂着 ``tag:manage``），
    所以这里不区分「谁的标签」。

    ``status`` 用 ``str`` 而不是 ``Literal`` / Enum：
        取值校验归领域（``TagStatus.parse``），这一层只做「是不是字符串、长不长」。
        在这里再列一遍可选值，就等于把同一份取值集合维护在两个地方，
        领域加一个新状态时这里会静默拒绝——错误信息还是 400 而不是「你少改了一处」。
    """

    status: str = Field(
        max_length=20,
        description="目标状态：normal（正常）/ abnormal（下架）/ deleted（已删除，可当恢复用）",
    )


# ──────────────────────────── 响应 ────────────────────────────


class TagResponse(BaseModel):
    """标签出参。

    ``post_count`` 是**算出来的**（已发布且未删除的文章数），表里没有这一列：
        存成一列就要在每次发文章/删文章/改标签时同步维护它，
        而任何一个漏掉的写路径都会让它慢慢变成一个错误但看起来正常的数字。
        代价是列表查询要做一次 JOIN + GROUP BY——对标签这个量级完全可以接受。

    ``author_id`` 允许为 ``null``，且这个 ``null`` 有意义：
        表示「这个标签没有归属」——存量数据，或创建者账号已注销
        （外键 ``ON DELETE SET NULL``）。前端应当据此隐藏「编辑」按钮，
        而不是把它当成一个名字叫 null 的用户。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    status: str
    type: str
    author_id: uuid.UUID | None = None
    post_count: int = Field(description="使用该标签的已发布文章数")


class TagPageResponse(BaseModel):
    """标签分页出参。"""

    items: list[TagResponse]
    total: int = Field(description="总条数（不只是本页），前端据它算总页数")
    offset: int = Field(description="本页起点，已被服务端收敛到合法区间")
    limit: int = Field(description="本页最大条数，已被服务端收敛到合法区间")

    @classmethod
    def from_dto(cls, dto: TagPageDTO) -> TagPageResponse:
        """从应用层的分页 DTO 构造响应。"""
        return cls(
            items=[TagResponse.model_validate(item) for item in dto.items],
            total=dto.total,
            offset=dto.offset,
            limit=dto.limit,
        )


__all__ = [
    "ChangeTagStatusRequest",
    "CreateTagRequest",
    "TagPageResponse",
    "TagResponse",
    "UpdateTagRequest",
]
