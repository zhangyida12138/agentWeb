"""互动上下文：点赞与互动统计的请求 / 响应 Schema（HTTP 边界）。

只有三个模型，因为点赞是本项目里最简单的一个写操作：
它没有「编辑」这个概念（有就是点赞，没有就是取消），
所以一个 toggle 请求 + 一个状态响应就覆盖了全部写交互；
再加一个只读的统计响应，让界面在点击之前就能显示正确的数字。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.application.interaction.dto import LikeStateDTO, PostInteractionStatsDTO
from app.domain.interaction.value_objects import (
    LIKE_TARGET_TYPE_MAX_LEN,
    LikeTargetType,
)

# ``target_type`` 在 schema 里只做**长度**约束，合法取值的判断交给
# ``LikeTargetType.parse``（用例里调用，非法值报 40041）。
#
# 为什么不在这里用 ``Literal["post", "comment"]``：
#    那会让 Pydantic 自己抛 ValidationError → 全局处理器把它变成 40000
#    （「参数校验失败」），而不是 40041（「点赞目标类型非法」）。
#    两个码对应两个完全不同的修复方向：40000 说明客户端把字段形状写错了，
#    40041 说明字段形状是对的、取值不在允许范围内。
#    这里要在边界处判取值的话，就得再写一次领域里已有的列表，
#    于是「加一种可点赞对象」要改两处，漏掉一处就会出现
#    「模型放行了、换算时 500」这种最难查的组合。
_TARGET_TYPE_HINT = " / ".join(sorted(LikeTargetType.ALL))


class ToggleLikeRequest(BaseModel):
    """点赞 / 取消点赞入参。

    同一个请求体表达两个相反的动作，由**当前状态**决定走哪边：
        这两个动作在数据上互为反面，让客户端先读状态再选接口，
        等于要求客户端在两个请求之间做一次无锁的状态判断——
        那正是「用户看到的是已赞，发出去的却是点赞」的成因。
        服务端握着权威状态，让它来定。

    ``target_type`` 用 ``str`` 而不是枚举，见文件头的说明。
    """

    target_type: str = Field(
        min_length=1,
        max_length=LIKE_TARGET_TYPE_MAX_LEN,
        description=f"目标类型，目前支持 {_TARGET_TYPE_HINT}",
    )
    target_id: uuid.UUID = Field(description="目标 id（文章 id 或评论 id，不是 slug）")


class LikeResultResponse(BaseModel):
    """点赞操作后的状态。

    回传 ``target_type`` / ``target_id`` 看起来是「把请求原样退回来」，
    但它让这个响应**自解释**：前端拿到它就能直接写进对应目标的缓存，
    不需要记住「这个响应是给哪次点击的」。
    尤其是在列表页上，同一个按钮可能在多个条目里同时被点。
    """

    target_type: str
    target_id: uuid.UUID
    liked: bool = Field(description="操作之后是否处于「已点赞」状态")
    like_count: int = Field(description="操作之后的真实赞数（实时聚合，不是 ±1 猜出来的）")

    @classmethod
    def from_dto(cls, dto: LikeStateDTO) -> LikeResultResponse:
        return cls(
            target_type=dto.target_type,
            target_id=dto.target_id,
            liked=dto.liked,
            like_count=dto.like_count,
        )


class PostInteractionStatsResponse(BaseModel):
    """一篇文章的互动统计（只读）。

    为什么需要这个只读接口，而不是只靠 toggle 的响应：
        按钮的初值必须来自服务端。只靠 toggle 的话，登录用户一进页面
        看到的就是「0 个赞 / 未点赞」，直到他点一下才变成真值——
        而已点赞的人点一下反而是**取消**。界面显示的初始状态必须是对的，
        否则这个按钮在第一次点击之前一直在骗人。

    三个字段里的 ``liked_by_me`` 对游客一律 false（而不是缺字段）：
        缺字段会让前端不得不写 ``stats.liked_by_me ?? false``，
        一个「总是要补默认值」的字段终有一天会被漏掉。
    """

    post_id: uuid.UUID
    like_count: int = Field(description="文章本身的赞数（不含评论的赞）")
    comment_count: int = Field(description="未撤回的评论总数（根评论 + 回复）")
    liked_by_me: bool = Field(description="当前访问者是否赞过这篇文章（游客恒为 false）")

    @classmethod
    def from_dto(cls, dto: PostInteractionStatsDTO) -> PostInteractionStatsResponse:
        return cls(
            post_id=dto.post_id,
            like_count=dto.like_count,
            comment_count=dto.comment_count,
            liked_by_me=dto.liked_by_me,
        )


__all__ = ["LikeResultResponse", "PostInteractionStatsResponse", "ToggleLikeRequest"]
