"""博客接口：公开阅读 + 作者写作（含管理员越权编辑）。

本文件是整个项目里**第一条同时服务游客与登录用户**的接口集合，
所以有两条看起来「不一致」但都是有意的规则：

① 读接口不挂 ``require_permission``
    列表与详情只使用可选身份解析：识别到本人就多给一点可见范围（能看自己的草稿），
    识别不到（游客 / token 失效）就按游客口径返回。未登录不该被 401 挡住。

② 写接口除了「认证」还要「授权」，而且**每条都要单独判归属**
    ``post:update`` 只说明「这人能写文章」，不说明「这篇是他的」。
    归属判断在用例里（``post.ensure_owned_by``），守卫管不到——
    因为它取决于**具体是哪一篇**，那是请求体之外的信息。
    两者的分工是：守卫 40320（你没这个能力），归属 40330（这不是你的东西）。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from agent_web_shared.pagination import DEFAULT_LIMIT, MAX_LIMIT, normalize_pagination
from app.application.blog.dto import (
    ChangePostStatusCommand,
    CreatePostCommand,
    DeletePostCommand,
    GetPostQuery,
    ListMyPostsQuery,
    ListPublishedPostsQuery,
    UpdatePostCommand,
)
from app.application.blog.use_cases import (
    CreatePostUseCase,
    DeletePostUseCase,
    GetPostBySlugUseCase,
    ListMyPostsUseCase,
    ListPublishedPostsUseCase,
    PublishPostUseCase,
    UnpublishPostUseCase,
    UpdatePostUseCase,
)
from app.domain.access.entities import PermissionCode
from app.presentation.api.v1.schemas.post import (
    CreatePostRequest,
    PostDetailResponse,
    PostPageResponse,
    UpdatePostRequest,
)
from app.presentation.dependencies import (
    CurrentUserId,
    OptionalCurrentUser,
    get_create_post_use_case,
    get_delete_post_use_case,
    get_list_my_posts_use_case,
    get_list_published_posts_use_case,
    get_post_by_slug_use_case,
    get_publish_post_use_case,
    get_unpublish_post_use_case,
    get_update_post_use_case,
    require_permission,
    require_permission_with_codes,
)

router = APIRouter(prefix="/posts", tags=["blog"])

# 「我的文章」单独挂在 /me/posts 而不是 /posts/mine。
#
# 为什么不放在 /posts/mine：
#   那样路径就与 ``/posts/{slug}`` 是**同一个模板**，谁能命中完全取决于注册顺序，
#   于是 slug 恰好叫 ``mine`` 的文章（标题写「Mine」就会生成它）永远打不开——
#   而访问它不会报 404，会返回「我的文章列表」，是一个不报错的错。
#   靠「把 /posts/mine 声明在前面」只能让冲突变得确定，不能消除它。
#   把「当前用户的资源」放到独立前缀下，这类遮蔽在结构上就不可能发生。
#
# 另外这也让授权语义更直白：/me/* 下的东西一律只属于调用者，
# 归属不是靠用例去比对 author_id，而是路径本身已经表达了。
me_router = APIRouter(prefix="/me/posts", tags=["blog"])


# ──────────────────────────── 公开读 ────────────────────────────


@router.get(
    "",
    response_model=PostPageResponse,
    summary="文章列表（公开，无需登录）",
)
async def list_posts(
    use_case: Annotated[ListPublishedPostsUseCase, Depends(get_list_published_posts_use_case)],
    # 与用户列表同一套收敛口径：越界的 offset/limit 不报 422，直接收敛到合法区间，
    # 并把收敛后的值回填进响应，让客户端能看出「我传的 1000 变成了 100」
    offset: Annotated[int, Query(description="偏移量，负数按 0 处理")] = 0,
    limit: Annotated[int, Query(description=f"每页条数，上限 {MAX_LIMIT}")] = DEFAULT_LIMIT,
    tag: Annotated[str | None, Query(description="按标签 slug 过滤")] = None,
) -> PostPageResponse:
    """列出**已发布**的文章。

    草稿和归档无论调用者是谁都不会出现在这里：
        这是「别人的文章」的列表，而别人的草稿对你不存在。
        作者想找自己的草稿走 ``/me/posts``。
    """
    safe_offset, safe_limit = normalize_pagination(offset, limit)
    page = await use_case.execute(
        ListPublishedPostsQuery(offset=safe_offset, limit=safe_limit, tag_name=tag)
    )
    return PostPageResponse.from_dto(page)


@me_router.get(
    "",
    response_model=PostPageResponse,
    summary="我的文章（含草稿与归档）",
)
async def list_my_posts(
    actor_id: CurrentUserId,
    use_case: Annotated[ListMyPostsUseCase, Depends(get_list_my_posts_use_case)],
    offset: Annotated[int, Query(description="偏移量，负数按 0 处理")] = 0,
    limit: Annotated[int, Query(description=f"每页条数，上限 {MAX_LIMIT}")] = DEFAULT_LIMIT,
    post_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="按状态过滤：draft / published / archived",
        ),
    ] = None,
) -> PostPageResponse:
    """列出当前登录用户的文章，**含草稿与已归档**。

    这里只要求**登录**，不要求任何 ``post:*`` 权限，理由是一条归属原则：
        这些内容的所有者就是调用者本人，归属已经是比权限码更强的约束
        （权限码可以被授予，归属不能）。如果改成要求 ``post:create``，
        一个被收回作者角色的人会连自己写过的草稿都看不到——
        内容没有消失，但所有者访问不到它，这在数据层面是不可接受的。

    排序按 ``updated_at`` 倒序而不是 ``published_at``：
        作者在这个列表里找的是「我最近在弄哪篇」，草稿没有发布时间，
        按 published_at 排会让所有草稿挤成一团且顺序无意义。

    查询参数在 Python 侧叫 ``post_status`` 是因为 ``status`` 与
    ``fastapi.status`` 模块同名（本文件要用 ``status.HTTP_204_NO_CONTENT``），
    在同一个命名空间里会撞车；对外仍然通过 ``alias`` 暴露成 ``?status=``。
    """
    safe_offset, safe_limit = normalize_pagination(offset, limit)
    page = await use_case.execute(
        ListMyPostsQuery(
            author_id=actor_id,
            offset=safe_offset,
            limit=safe_limit,
            status=post_status,
        )
    )
    return PostPageResponse.from_dto(page)


@router.get(
    "/{slug}",
    response_model=PostDetailResponse,
    summary="文章详情（公开，无需登录）",
)
async def get_post(
    slug: str,
    use_case: Annotated[GetPostBySlugUseCase, Depends(get_post_by_slug_use_case)],
    viewer: OptionalCurrentUser,
) -> PostDetailResponse:
    """按 slug 读取单篇文章。

    可见性规则：已发布人人可读；草稿 / 已归档只有作者本人可读，
    对其他人（包括游客）一律 404 而不是 403——
        403 等于告诉对方「这里确实有一篇文章，只是不给你看」。
        别人未发布的内容，其**存在性**本身就是私有信息。

    阅读量：只有「不是作者本人」的访问才计数，
    否则作者反复预览自己的文章会把数字刷得毫无参考价值。
    """
    detail = await use_case.execute(
        GetPostQuery(slug=slug, viewer_id=viewer.id if viewer is not None else None)
    )
    return PostDetailResponse.from_dto(detail)


# ──────────────────────────── 写 ────────────────────────────


@router.post(
    "",
    response_model=PostDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建文章（总是以草稿落地）",
    dependencies=[Depends(require_permission(PermissionCode.POST_CREATE))],
)
async def create_post(
    payload: CreatePostRequest,
    actor_id: CurrentUserId,
    use_case: Annotated[CreatePostUseCase, Depends(get_create_post_use_case)],
) -> PostDetailResponse:
    """创建一篇草稿。

    返回 201 + 完整详情（而不是只回 id）：
        编辑器保存后通常立刻要切到「已保存」状态并显示 slug 与发布时间，
        只回 id 的话前端还得再发一次 GET，而那次 GET 可能读到别的请求造成的中间态。

    ``author_id`` 从 ``current_user`` 取，请求体里没有这个字段——
        让客户端指定作者等于允许冒充他人发文章。
    """
    detail = await use_case.execute(
        CreatePostCommand(
            author_id=actor_id,
            title=payload.title,
            content=payload.content,
            summary=payload.summary,
            slug=payload.slug,
            cover_url=payload.cover_url,
            tag_names=tuple(payload.tag_names),
        )
    )
    return PostDetailResponse.from_dto(detail)


@router.patch(
    "/{post_id}",
    response_model=PostDetailResponse,
    summary="编辑文章（作者本人，或持有 post:update_any 的管理员）",
)
async def update_post(
    post_id: uuid.UUID,
    payload: UpdatePostRequest,
    actor_id: CurrentUserId,
    codes: Annotated[
        frozenset[str],
        Depends(require_permission_with_codes(PermissionCode.POST_UPDATE)),
    ],
    use_case: Annotated[UpdatePostUseCase, Depends(get_update_post_use_case)],
) -> PostDetailResponse:
    """局部更新文章。

    用 PATCH 而不是 PUT：编辑器里「只改标题」不该顺手把正文也覆盖一遍，
    而 PUT 的语义要求客户端提交完整表示——那样每次保存都要带上全文，
    并发编辑时后保存的人会把前一个人的正文改动整体抹掉。

    请求体用 ``model_dump(exclude_unset=True)`` 取值，这一步是本接口的核心：
        它把「客户端没提这个字段」和「客户端明确说把它清空」区分开，
        用例才能把前者当 ``UNSET``（不改）、后者当 ``None``（清空）。
        漏掉 ``exclude_unset`` 会让所有未提交的字段变成 None，
        表现为「只改标题，摘要和标签全没了」。

    ``actor_can_override`` 由权限码集合推出，不接收客户端传入：
        越权钥匙必须来自服务端自己查到的权限，
        否则任何登录用户都能自称管理员去改别人的文章。
    """
    fields = payload.model_dump(exclude_unset=True)
    # slug 没有「清空」这个合法状态（NOT NULL 永久链接）。
    # 显式传 null 时直接丢掉这个键，语义退化为「不改 slug」——
    # 比让用例抛 400 更贴合调用方意图（客户端表单清空 slug 输入框）
    if fields.get("slug", "") is None:
        fields.pop("slug")
    # 标签列表转成元组：命令对象是不可变 DTO，传一个可变 list 进去，
    # 就等于允许调用方在用例跑了一半时把标签改掉（共享可变状态）
    if isinstance(fields.get("tag_names"), list):
        fields["tag_names"] = tuple(fields["tag_names"])

    detail = await use_case.execute(
        UpdatePostCommand(
            post_id=post_id,
            actor_id=actor_id,
            actor_can_override=PermissionCode.POST_UPDATE_ANY in codes,
            **fields,
        )
    )
    return PostDetailResponse.from_dto(detail)


@router.post(
    "/{post_id}/publish",
    response_model=PostDetailResponse,
    summary="发布文章（作者本人，或持有 post:update_any 的管理员）",
)
async def publish_post(
    post_id: uuid.UUID,
    actor_id: CurrentUserId,
    codes: Annotated[
        frozenset[str],
        Depends(require_permission_with_codes(PermissionCode.POST_PUBLISH)),
    ],
    use_case: Annotated[PublishPostUseCase, Depends(get_publish_post_use_case)],
) -> PostDetailResponse:
    """发布文章（``draft`` → ``published``，幂等）。

    设计成 ``POST /{id}/publish`` 这个动作用子资源，而不是 ``PATCH`` 里改 ``status``：
        状态迁移是有方向的（草稿→发布；发布→下架；已发布**不能**回到草稿），
        把它做成「可写字段」意味着客户端可以提交任意状态值，
        服务端就得在 PATCH 里再实现一遍状态机的合法性判断。
        用动作子资源则每个迁移各有一个端点，非法迁移在路由层面就不存在。

    发布权限单独用一个码（``post:publish``）：作者能写草稿，
    但「让内容对外可见」是另一件事——将来若需要「先审后发」，
    只需要把 ``post:publish`` 从作者角色里摘掉，接口与用例一行都不用改。

    越权改的是 ``post:update_any`` 而不是单独的 ``post:publish_any``：
        发布/下架和编辑一样都是「改动这篇文章」，用同一把钥匙，
        免得管理员的开关散落成四五个近似权限码。
    """
    detail = await use_case.execute(
        ChangePostStatusCommand(
            post_id=post_id,
            actor_id=actor_id,
            actor_can_override=PermissionCode.POST_UPDATE_ANY in codes,
        )
    )
    return PostDetailResponse.from_dto(detail)


@router.post(
    "/{post_id}/unpublish",
    response_model=PostDetailResponse,
    summary="下架文章（已发布 → 已归档）",
)
async def unpublish_post(
    post_id: uuid.UUID,
    actor_id: CurrentUserId,
    codes: Annotated[
        frozenset[str],
        Depends(require_permission_with_codes(PermissionCode.POST_PUBLISH)),
    ],
    use_case: Annotated[UnpublishPostUseCase, Depends(get_unpublish_post_use_case)],
) -> PostDetailResponse:
    """把文章从公开列表撤下（``published`` → ``archived``）。

    下架**不等于删除**：文章仍在库里、作者仍能在 ``/me/posts`` 里看到并重新发布，
    只是不再出现在公开列表里。已建立的永久链接仍然可达（返回文章本身，
    但状态是 archived）——这一点与「删除」有本质区别，
    删除后链接会 404，所以删除的操作必须比下架更难触发（UI 上要二次确认）。

    重复下架会得到 40035（非法状态迁移）而不是静默成功，
    而重复**发布**是幂等的：这两者的区别在于
        「已经下架了再下架」说明调用方对当前状态的理解是错的（值得报错），
        「已经发布了再发布」只是重试（不该报错）。
    """
    detail = await use_case.execute(
        ChangePostStatusCommand(
            post_id=post_id,
            actor_id=actor_id,
            actor_can_override=PermissionCode.POST_UPDATE_ANY in codes,
        )
    )
    return PostDetailResponse.from_dto(detail)


@router.delete(
    "/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除文章（软删除，作者本人或持有 post:delete_any 的管理员）",
)
async def delete_post(
    post_id: uuid.UUID,
    actor_id: CurrentUserId,
    codes: Annotated[
        frozenset[str],
        Depends(require_permission_with_codes(PermissionCode.POST_DELETE)),
    ],
    use_case: Annotated[DeletePostUseCase, Depends(get_delete_post_use_case)],
) -> None:
    """软删除文章。

    回 204 而不是 200 + 空对象：删除之后没有「剩余的表示」可回，
    再包一层 ``{"ok": true}`` 只是多一个需要和后端保持同步的字段。

    软删除（写 ``deleted_at``）而不是 ``DELETE FROM posts``：
        文章与 ``post_tags`` 是外键关联的，物理删除会连带影响标签的唯一性判断
        （某个标签可能因此变成零引用）；而且误删无法恢复。
        软删除之后 slug 仍然被占用（唯一索引不认 ``deleted_at``），
        所以「删了再发一篇同标题的」会拿到带序号的 slug 而不是复活旧链接——
        这对已经有外链的旧地址来说是更安全的行为。

    越权删除用 ``post:delete_any`` 而不是复用 ``post:update_any``：
        删除不可逆（至少对用户来说），把它和编辑共用一把钥匙会让
        「我只想让人帮忙改错别字」顺带获得删光的能力。
    """
    await use_case.execute(
        DeletePostCommand(
            post_id=post_id,
            actor_id=actor_id,
            actor_can_override=PermissionCode.POST_DELETE_ANY in codes,
        )
    )


__all__ = ["me_router", "router"]
