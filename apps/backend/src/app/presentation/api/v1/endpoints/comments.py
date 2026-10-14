"""评论接口：公开读 + 登录后发言 / 撤回。

沿用了 ``endpoints/posts.py`` 的两条规则：

① 读接口不挂 ``require_permission``
    评论列表服务的是「读者」，其中绝大多数没有登录。
    它只要求文章对该访问者可见（草稿的评论区只有作者能读），
    识别不到身份就按游客口径返回。

② 写接口除了认证还要授权，而且**每条都要单独判归属**
    ``comment:delete`` 只说明「这人能删评论」，不说明「这条是他的」；
    归属判断在用例里（``comment.ensure_deletable_by``）。
    守卫 40340 管不到它，因为它取决于**具体是哪一条**。

路径形状有一处值得说明：**同一个模块里有两个 router**。
    ``/posts/{post_id}/comments`` 表达的是「某篇文章下的评论集合」，
    集合的父资源是文章，所以路径必须挂在 /posts 下；
    而 ``DELETE /comments/{id}`` 操作的是一个**已知 id 的单条评论**，
    它的父资源并不是「我这次请求的那篇文章」（虽然事实上存在一篇）。
    把删除写成 ``DELETE /posts/{post_id}/comments/{id}`` 会多要求一个
    服务端已经知道的信息——客户端得多带一个 id，而且两个 id 对不上时
    就得决定听谁的。拆成两个 router，路径各自表达各自的事实。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from agent_web_shared.pagination import DEFAULT_LIMIT, MAX_LIMIT, normalize_pagination
from app.application.interaction.dto import (
    CreateCommentCommand,
    DeleteCommentCommand,
    ListCommentsQuery,
)
from app.application.interaction.use_cases import (
    CreateCommentUseCase,
    DeleteCommentUseCase,
    ListCommentsUseCase,
)
from app.domain.access.entities import PermissionCode
from app.presentation.api.v1.schemas.comment import (
    CommentPageResponse,
    CommentResponse,
    CreateCommentRequest,
)
from app.presentation.dependencies import (
    CurrentUserId,
    OptionalCurrentUser,
    get_create_comment_use_case,
    get_delete_comment_use_case,
    get_list_comments_use_case,
    require_permission,
    require_permission_with_codes,
)

# 集合挂在文章下：/posts/{post_id}/comments
router = APIRouter(prefix="/posts", tags=["interaction"])

# 单条评论的操作：/comments/{comment_id}
comments_router = APIRouter(prefix="/comments", tags=["interaction"])


# ──────────────────────────── 公开读 ────────────────────────────


@router.get(
    "/{post_id}/comments",
    response_model=CommentPageResponse,
    summary="评论树（公开，无需登录）",
)
async def list_comments(
    post_id: uuid.UUID,
    use_case: Annotated[ListCommentsUseCase, Depends(get_list_comments_use_case)],
    viewer: OptionalCurrentUser,
    offset: Annotated[int, Query(description="偏移量（单位是**根评论**），负数按 0 处理")] = 0,
    limit: Annotated[int, Query(description=f"每页根评论数，上限 {MAX_LIMIT}")] = DEFAULT_LIMIT,
) -> CommentPageResponse:
    """读取一篇文章的评论树（**任意深度**，未登录可读）。

    树的形状就是数据里的父子关系：回复的回复会一直往下嵌，
        不设层数上限，也不做任何归一。
        响应里每层都带 ``author_display_name``，非根节点还带
        ``parent_author_display_name``，于是前端可以直接渲染
        「小明 回复 小红」，不需要为每条评论再回查一次用户。
        至于缩进几级（本项目的界面从第二层起就不再缩进）是**前端**的决定：
        那是排版，不是数据。

    分页单位是**根评论**而不是单条评论：
        如果按单条评论分页，一页里就可能出现「某条回复但它的被回复者不在这页」，
        读者会看到一句莫名其妙的应答。按「一段对话」分页，
        每一页里的每一条回复都能在本页找到它上面的那条根评论。

    回复不参与分页（一组对话里的回复数在真实场景下很小），所以
    ``total`` 表示的是根评论总数——前端的「加载更多」是按这个数算的。

    未登录也能读：``viewer`` 为空时，每条评论的 ``liked_by_me`` 一律 false。
    这比返回 401 更合适——评论区是公开内容的一部分，
    挡掉它等于让游客连文章下面的讨论都看不到。
    """
    safe_offset, safe_limit = normalize_pagination(offset, limit)
    thread = await use_case.execute(
        ListCommentsQuery(
            post_id=post_id,
            viewer_id=viewer.id if viewer is not None else None,
            offset=safe_offset,
            limit=safe_limit,
        )
    )
    return CommentPageResponse.from_dto(thread)


# ──────────────────────────── 写 ────────────────────────────


@router.post(
    "/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="发表评论或回复",
    dependencies=[Depends(require_permission(PermissionCode.COMMENT_CREATE))],
)
async def create_comment(
    post_id: uuid.UUID,
    payload: CreateCommentRequest,
    actor_id: CurrentUserId,
    use_case: Annotated[CreateCommentUseCase, Depends(get_create_comment_use_case)],
) -> CommentResponse:
    """在某篇文章下发一条评论；带 ``parent_id`` 时是回复。

    返回 201 + 完整评论（而不是只回 id）：
        前端要把它**就地插入**评论区（乐观更新的落点），
        只回 id 的话还得再拉一次整棵评论树才能知道它长什么样、排在哪。

    回的是单个节点而不是整棵树：一次评论只会改变一个位置，
    回整棵树等于把一个可能上千条的响应体塞给一次点击。

    这里不校验 ``parent_id`` 指向的评论是否属于这篇文章——
    那是用例的职责（schema 无从知道库里有什么），
    错误的 parent 会得到 40440 而不是 400：对调用方来说
    「这条评论不存在」和「这条评论不在这个帖子下」都是「你给的这个 id 用不了」。
    """
    node = await use_case.execute(
        CreateCommentCommand(
            post_id=post_id,
            actor_id=actor_id,
            content=payload.content,
            parent_id=payload.parent_id,
        )
    )
    return CommentResponse.from_dto(node)


@comments_router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="撤回评论（作者本人，或持有 comment:delete_any 的管理员）",
)
async def delete_comment(
    comment_id: uuid.UUID,
    actor_id: CurrentUserId,
    codes: Annotated[
        frozenset[str],
        Depends(require_permission_with_codes(PermissionCode.COMMENT_DELETE)),
    ],
    use_case: Annotated[DeleteCommentUseCase, Depends(get_delete_comment_use_case)],
) -> None:
    """撤回一条评论（软删除）。

    回 204 而不是 200 + 空对象：撤回之后没有「剩余的表示」可回。

    为什么用 ``comment:delete`` 这个码而不是复用 ``comment:create``：
        「能发言」和「能撤回自己的发言」是两件事。
        如果共用 create，将来一旦出现「禁止某人发言」的处置，
        他会连自己已经发出去的评论都撤不回来——
        那是两件应该分开的能力。

    越权删除用 ``comment:delete_any``，与 ``post:delete_any`` 同一个设计：
        管理员处置违规内容不该需要「冒充作者」。

    ``actor_can_override`` 由权限码集合推出，**不接收客户端传入**：
        越权钥匙必须来自服务端自己查到的权限，
        否则任何登录用户都能自称管理员去删别人的评论。

    重复删除回 **40440** 而不是 204，与 ``DELETE /posts/{id}`` 同口径：
        「已撤回的评论对所有入口都等同于不存在」是领域层的不变量，
        而 ``ensure_deletable_by`` 的第一行就是 ``ensure_not_deleted()``。
        早期注释曾写“幂等返回 204”，那是错的——
        真要幂等就得让删除流程先经过一个“过滤掉已删除行”的读，
        那又会把“删成功”和“早就没了”混成一件事。
        重试的客户端应该把 404 当作“已经删掉了”（这是删除重试的标准做法）。
    """
    await use_case.execute(
        DeleteCommentCommand(
            comment_id=comment_id,
            actor_id=actor_id,
            actor_can_override=PermissionCode.COMMENT_DELETE_ANY in codes,
        )
    )


__all__ = ["comments_router", "router"]
