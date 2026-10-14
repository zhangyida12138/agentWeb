"""博客上下文的用例。

一个用例 = 一次完整的业务动作。它只做三件事：

    ① 把命令里的裸值变成值对象（触发校验）
    ② 调领域实体做决策（``ensure_owned_by`` / ``publish`` / ``soft_delete``）
    ③ 调仓储把结果落库

**事务边界不在这一层**。用例只 ``flush``（通过仓储），
真正的 ``commit`` 由 ``core/database.py::get_db`` 在请求结束时统一做。
好处是「一个请求 = 一个事务」这条不变量不需要每个用例自觉维护：
用了两个仓储、三步写入，失败时它们会一起回滚。

所有用例都不 import FastAPI / HTTPException：
    授权（你有没有这个权限）归表现层的守卫，
    归属（这一篇是不是你的）归领域实体，
    用例本身只负责按正确顺序调用它们——这样它才能被非 HTTP 的入口复用。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.application.blog.dto import (
    UNSET,
    ChangePostStatusCommand,
    CreatePostCommand,
    DeletePostCommand,
    GetPostQuery,
    ListMyPostsQuery,
    ListPublishedPostsQuery,
    PostDetailDTO,
    PostPageDTO,
    PostSummaryDTO,
    Unset,
    UpdatePostCommand,
)
from app.domain.blog.entities import Post, PostStatus
from app.domain.blog.exceptions import (
    InvalidPostSlugError,
    PostNotFoundError,
    SlugAlreadyTakenError,
)
from app.domain.blog.value_objects import PostContent, PostTitle, Slug, TagName

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from app.domain.blog.repositories import PostRepository

# 「标题撞车」时最多尝试的后缀数：``xxx`` → ``xxx-2`` … ``xxx-20``。
# 再往上就说明有人在故意刷，直接跳随机后缀，避免 20 次往返查询变成一个 DoS 面。
_MAX_SLUG_SUFFIX_ATTEMPTS = 20


async def _load_post(posts: PostRepository, post_id: uuid.UUID) -> Post:
    """按 id 取文章，取不到就抛 404。

    抽成公共函数而不是每个用例各写一遍：这三行里隐含一条规则——
    「软删除的文章等同于不存在」。写一次，所有入口自动一致；
    分散写法迟早会出现某个入口忘了判 ``deleted_at``，
    于是「已删除的文章还能被编辑」。
    """
    post = await posts.get_by_id(post_id)
    if post is None:
        raise PostNotFoundError()
    post.ensure_not_deleted()
    return post


async def _resolve_creatable_slug(
    posts: PostRepository,
    *,
    requested: str | None,
    title: PostTitle,
) -> Slug:
    """为新文章定下 slug。

    两种情况分得很开：
        客户端**指定**了 slug → 撞车就直接 409 报错。
            这里是「你明确要这个名字，但它被占了」，静默改掉是最糟的反馈：
            用户以为文章的地址是 ``my-post``，实际存的是 ``my-post-2``。
        客户端**没指定** → 由标题推导，撞车就自动加后缀。
            这是「系统帮我起的名字」，用户没表达过偏好，替它让步是合理的。
    """
    if requested is not None:
        candidate = Slug(requested)
        if await posts.exists_slug(candidate):
            raise SlugAlreadyTakenError()
        return candidate

    base = Slug.from_title(title.value)
    for index in range(1, _MAX_SLUG_SUFFIX_ATTEMPTS + 1):
        candidate = base if index == 1 else base.with_suffix(index)
        if not await posts.exists_slug(candidate):
            return candidate
    # 兜底：连 ``-20`` 都被占了，用随机后缀收尾（概率极低，但不能留一个 500 的出口）
    return base.with_suffix(uuid.uuid4().hex[:8])


# ──────────────────────────── 读 ────────────────────────────


class ListPublishedPostsUseCase:
    """公开文章列表（未登录可访问，只含已发布）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, query: ListPublishedPostsQuery) -> PostPageDTO:
        tag = TagName(query.tag_name) if query.tag_name else None
        # 先查总数还是先查数据？这里选先数据后总数是随意的——两条都在同一事务里，
        # 真正重要的是**两者用同一份过滤条件**，否则会出现「共 10 条但只翻出 3 条」。
        items = await self._posts.list_published(query.offset, query.limit, tag=tag)
        total = await self._posts.count_published(tag=tag)
        return PostPageDTO(
            items=tuple(PostSummaryDTO.from_entity(post) for post in items),
            total=total,
            offset=query.offset,
            limit=query.limit,
        )


class GetPostBySlugUseCase:
    """按 slug 读单篇（公开，未登录可访问；作者的草稿本人可预览）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, query: GetPostQuery) -> PostDetailDTO:
        post = await self._posts.get_by_slug(Slug(query.slug))
        if post is None:
            raise PostNotFoundError()

        # 可见性规则写在实体上（已发布人人可读；草稿/归档只有作者可见）。
        # 未发布的对他人的存在性一并隐藏——统一 404，不泄露「这里有篇文章」。
        post.ensure_visible_to(query.viewer_id)

        post_id = post.id
        if post_id is None:  # pragma: no cover - 来自仓储的实体必然已落库，id 不会为空
            raise PostNotFoundError()

        # 作者自己刷新页面不该涨阅读量：那更像是「编辑时的预览」，
        # 而且作者反复自测会把计数刷得毫无参考价值。
        if post.author_id != query.viewer_id:
            post.register_view(await self._posts.increment_view_count(post_id))

        return PostDetailDTO.from_entity(post)


class ListMyPostsUseCase:
    """我的文章列表（含草稿、归档；按更新时间倒序）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, query: ListMyPostsQuery) -> PostPageDTO:
        # 状态过滤要显式校验：``?status=publihsed`` 这种笔误若被当成「不筛选」，
        # 前端会拿到整份列表且看起来一切正常，问题要很久以后才暴露。
        status = PostStatus.parse(query.status) if query.status else None
        items = await self._posts.list_by_author(
            query.author_id, query.offset, query.limit, status=status
        )
        total = await self._posts.count_by_author(query.author_id, status=status)
        return PostPageDTO(
            items=tuple(PostSummaryDTO.from_entity(post) for post in items),
            total=total,
            offset=query.offset,
            limit=query.limit,
        )


# ──────────────────────────── 写 ────────────────────────────


class CreatePostUseCase:
    """新建文章（总是以 ``draft`` 落地）。

    为什么新建不给「直接发布」的选项：
        编辑器上的「保存草稿」和「发布」是两个动作，如果新建接口能一次做成 published，
        就等于承认「存在一篇从未经过保存校验、直接面向读者的文章」。
        统一先落草稿、再 ``publish``，状态机只有一条入口，
        ``published_at`` 的写入时机也只有一个地方需要维护。
    """

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, command: CreatePostCommand) -> PostDetailDTO:
        title = PostTitle(command.title)
        content = PostContent(command.content)
        slug = await _resolve_creatable_slug(self._posts, requested=command.slug, title=title)

        post = Post.create(
            author_id=command.author_id,
            title=title,
            slug=slug,
            content=content,
            summary=command.summary,
            cover_url=command.cover_url,
            tags=tuple(TagName(name) for name in command.tag_names),
        )
        created = await self._posts.add(post)
        return PostDetailDTO.from_entity(created)


class UpdatePostUseCase:
    """编辑文章（作者本人，或持有 ``post:update_any`` 的管理员）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, command: UpdatePostCommand) -> PostDetailDTO:
        post = await _load_post(self._posts, command.post_id)

        # 归属判定是这次编辑的**第一个**动作，排在字段解析之前：
        #   如果放在后面，一个越权请求仍会先跑完标题/正文的校验，
        #   于是攻击者能通过「400 还是 403」的差异探测出「哪些字段值合法」——
        #   在不该有任何信息泄露的路径上泄露了信息。
        post.ensure_owned_by(command.actor_id, has_override=command.actor_can_override)

        post.update_content(
            # ``or ""`` 不是偷懒：``"title": null`` 这种请求如果直接透传给 ``PostTitle``，
            # 会在 ``None.strip()`` 处抛 AttributeError（500）。
            # 归一成空串后走向值对象的正常校验分支，得到的是 400 + 40030。
            title=(UNSET if isinstance(command.title, Unset) else PostTitle(command.title or "")),
            content=(
                UNSET if isinstance(command.content, Unset) else PostContent(command.content or "")
            ),
            summary=UNSET if isinstance(command.summary, Unset) else command.summary,
            cover_url=(UNSET if isinstance(command.cover_url, Unset) else command.cover_url),
            tags=(
                UNSET
                if isinstance(command.tag_names, Unset)
                # ``or ()`` 不是防御性写法：显式传 ``"tag_names": null`` 时
                # 命令里是 None 而不是 UNSET，直接迭代 None 会在生成器里抛
                # TypeError，也就是一个 500。与 ``summary: null`` 保持同一个口径
                # （显式 null = 清空），所以 None 等价于空列表。
                # 少了这一句，客户端「整表单提交」一次就会打到 500。
                else tuple(TagName(name) for name in (command.tag_names or ()))
            ),
        )

        # slug 单独处理：它需要查重，而且**只有显式传了**才动。
        # 表现层已经把 ``"slug": null`` 过滤掉，能进到这里的一定是非空字符串。
        if not isinstance(command.slug, Unset):
            if not command.slug:
                raise InvalidPostSlugError("slug 不能为空")
            candidate = Slug(command.slug)
            if await self._posts.exists_slug(candidate, exclude_id=post.id):
                raise SlugAlreadyTakenError()
            post.change_slug(candidate)

        updated = await self._posts.update(post)
        return PostDetailDTO.from_entity(updated)


class PublishPostUseCase:
    """发布文章（幂等）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, command: ChangePostStatusCommand) -> PostDetailDTO:
        post = await _load_post(self._posts, command.post_id)
        post.ensure_owned_by(command.actor_id, has_override=command.actor_can_override)
        post.publish()
        updated = await self._posts.update(post)
        return PostDetailDTO.from_entity(updated)


class UnpublishPostUseCase:
    """下架文章（published → archived）。"""

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, command: ChangePostStatusCommand) -> PostDetailDTO:
        post = await _load_post(self._posts, command.post_id)
        post.ensure_owned_by(command.actor_id, has_override=command.actor_can_override)
        # 下架同样要求归属：否则任何人都能把别人的文章从首页撤下来。
        # 「发布」和「下架」的权限码是同一个（post:publish），
        # 因为它俩是同一件事的两个方向——只给一个方向等于给了半个开关。
        post.unpublish()
        updated = await self._posts.update(post)
        return PostDetailDTO.from_entity(updated)


class DeletePostUseCase:
    """软删除文章。

    返回 ``None``：删除之后没有「剩余的表示」可回。
    刻意不回 ``{"ok": true}`` 之类的信封——HTTP 层已经用 204 表达了同一件事，
    再在 body 里说一遍只会多一个需要保持同步的地方。
    """

    def __init__(self, posts: PostRepository) -> None:
        self._posts = posts

    async def execute(self, command: DeletePostCommand) -> None:
        post = await _load_post(self._posts, command.post_id)
        post.ensure_owned_by(command.actor_id, has_override=command.actor_can_override)
        post.soft_delete()
        await self._posts.update(post)


__all__ = [
    "CreatePostUseCase",
    "DeletePostUseCase",
    "GetPostBySlugUseCase",
    "ListMyPostsUseCase",
    "ListPublishedPostsUseCase",
    "PublishPostUseCase",
    "UnpublishPostUseCase",
    "UpdatePostUseCase",
]
