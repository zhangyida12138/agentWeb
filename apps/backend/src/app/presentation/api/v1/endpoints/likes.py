"""点赞与互动统计接口：一个 toggle 覆盖点赞与取消，外加一个只读的统计。

只有 toggle 一个写端点，这是本模块最重要的设计说明：

    为什么不是 ``POST /likes`` + ``DELETE /likes``（或 ``DELETE /likes/{id}``）：
        点赞和取消是一对**互斥**的操作，它们的合法前提是「当前处于相反状态」。
        把它拆成两个端点，就等于把「我现在是什么状态」这个判断
        推给客户端——而客户端手里的状态是它自己缓存的一份副本，
        可能已经过期（另一个标签页点了取消、或者别的设备动过）。
        于是会出现「界面上显示已赞，用户点了一下想取消，客户端却发出了点赞」，
        结果什么都没变，用户以为按钮坏了。
        服务端握着权威状态，让它来定方向，客户端只需要表达「点了一下」。

    代价是接口不是严格幂等的（连点两次会抵消）。这个代价值得，
    因为它对应的是**用户真实意图**：连点两次心形就是要取消。
    真正需要防的并发问题（两个并发的「点赞」写入两份记录）
    已经由数据库唯一约束 + ON CONFLICT 兜住，与端点形状无关。

两个 router 的解释：写端点挂在 ``/likes`` 下（它操作的是一个目标，
    而目标是不限类型的）；统计挂在 ``/posts/{id}/interactions`` 下。
    后者看上去可以改成 ``/likes/stats``，但「有多少个赞」
    描述的是**那篇文章**的属性，不是一个叫 stats 的全局资源——
    挂在文章下，路径本身就说明了这个数字属于谁。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.interaction.dto import (
    GetPostInteractionStatsQuery,
    ToggleLikeCommand,
)
from app.application.interaction.use_cases import (
    GetPostInteractionStatsUseCase,
    ToggleLikeUseCase,
)
from app.domain.access.entities import PermissionCode
from app.presentation.api.v1.schemas.like import (
    LikeResultResponse,
    PostInteractionStatsResponse,
    ToggleLikeRequest,
)
from app.presentation.dependencies import (
    CurrentUserId,
    OptionalCurrentUser,
    get_post_interaction_stats_use_case,
    get_toggle_like_use_case,
    require_permission,
)

router = APIRouter(prefix="/likes", tags=["interaction"])

# 读侧：某篇文章的互动统计，形状与 /posts/{id}/comments 平行
posts_router = APIRouter(prefix="/posts", tags=["interaction"])


@router.post(
    "/toggle",
    response_model=LikeResultResponse,
    summary="点赞 / 取消点赞（同一个入口）",
    dependencies=[Depends(require_permission(PermissionCode.LIKE_TOGGLE))],
)
async def toggle_like(
    payload: ToggleLikeRequest,
    actor_id: CurrentUserId,
    use_case: Annotated[ToggleLikeUseCase, Depends(get_toggle_like_use_case)],
) -> LikeResultResponse:
    """切换某个目标的点赞状态。

    ``actor_id`` 从 token 推导（谁点的），``target_id`` 从请求体来（点的是谁）。
    两者绝不能来自同一个地方：如果请求体里能指定 ``user_id``，
    那点赞数就成了任何人都能随意篡改的东西。

    **为什么用 POST 而不是 PUT**：PUT 要求客户端指定目标状态
    （``{"liked": true}``），那又回到了「客户端决定方向」，
    同样会在过期状态下做错事。POST 的语义是「提交一个动作」，
    正好匹配「我点了一下」这个事实。

    **为什么匿名不能点赞**：点赞是一人一票的记录，必须知道是谁。
    （如果将来做匿名点赞，那它就变成了纯计数而不是关系，
    界面上「我赞过没」也就消失了，是另一种产品。）

    **路径里的动作词**（``/likes/toggle``）而不是把动作放进请求体或 query：
        路径是这个接口唯一能被反代、日志、监控一眼看懂的部分。
        写成 ``POST /likes`` 带 ``{"action": "toggle"}`` 就没人能靠路径
        判断它在干什么。

    目标校验由用例完成：
        目标不存在 → 40441；目标是一篇未发布（草稿/归档）的文章 → 40940。
        两者都在写库之前发生，所以在「点赞一个不存在的东西」这条路径上，
        ``likes`` 表不会留下任何痕迹。
    """
    state = await use_case.execute(
        ToggleLikeCommand(
            actor_id=actor_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
        )
    )
    return LikeResultResponse.from_dto(state)


@posts_router.get(
    "/{post_id}/interactions",
    response_model=PostInteractionStatsResponse,
    summary="文章的互动统计（公开，无需登录）",
)
async def get_post_interaction_stats(
    post_id: uuid.UUID,
    use_case: Annotated[
        GetPostInteractionStatsUseCase, Depends(get_post_interaction_stats_use_case)
    ],
    viewer: OptionalCurrentUser,
) -> PostInteractionStatsResponse:
    """取一篇文章的赞数与评论数（以及「我赞过没」）。

    公开可读，与评论树口径一致：这两个数字是文章页面的公共信息，
    挡掉它等于让游客连「这篇文章有多少人喜欢」都看不到。
    未登录时 ``liked_by_me`` 恒为 false，而不是 401。

    这里**不**校验文章是否可见，直接在数据库里按 post_id 聚合：
        传入一个不存在（或别人的草稿）的 id 会得到一个全 0 的结果。
        不是疏忽——这个接口需要能同时服务列表页（一次问多篇），
        而列表页里出现一篇刚好被删掉的文章不该让整页 404。
        它能泄露的信息为零：那些数字本来就是 0，而且它不返回任何标题/正文。

    为什么要批量化的用例却只暴露单个 post_id 的路径：
        列表页将来需要「一次拿一页文章的互动数」才能避开 N+1，
        所以用例接口天生就是批量的（``post_ids`` 元组）；
        当前只开放单篇路径，是因为详情页只需要一篇，
        而多篇的查询参数形状（重复 key？逗号分隔？）还没有确定。
    """
    stats = await use_case.execute(
        GetPostInteractionStatsQuery(
            post_ids=(post_id,),
            viewer_id=viewer.id if viewer is not None else None,
        )
    )
    # 用例保证「请求过的 id 一定有键」（即使库里没有任何数据），
    # 所以这里不需要再写一个兜底对象——那种兜底会把
    # 「用例返回了空字典」这类真实 bug 掩盖成 0。
    return PostInteractionStatsResponse.from_dto(stats[post_id])


__all__ = ["posts_router", "router"]
