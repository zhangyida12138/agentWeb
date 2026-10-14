"""互动上下文的用例。

与 ``application/blog/use_cases.py`` 同一套约定：

    ① 把命令里的裸值变成值对象（触发校验）
    ② 调领域实体做决策（``ensure_deletable_by`` / ``soft_delete``）
    ③ 调仓储把结果落库

并且同样**不 import FastAPI**——授权归表现层守卫，归属归领域实体，
用例只负责按顺序调用它们。

本文件比博客的用例文件多承担了一件事：**跨上下文编排**。
    评论一定属于某篇文章，所以每个写用例都要先通过 ``PostRepository``
    确认「这篇文章存在、你看得见、而且它现在开放互动」。
    另一头，评论树要把「谁写的 / 回了谁」渲染成人名，而名字在身份上下文里，
    于是读评论树的用例还要通过 ``UserRepository`` 批量取作者。
    这两份依赖刻意只落在这一层：领域层只拿裸 ``post_id`` / ``author_id``，
    将来要把互动拆成独立服务，需要改的只有这一层的那几次调用。

★ 跨上下文的批量查询是这一层的硬规矩（不只在博客里）：
    一页评论树涉及几十个作者，逐个 ``get_by_id`` 就是几十次往返，
    而且随页大小线性增长。凡是「循环里查库」的形状，都要换成一次批量。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from app.application.interaction.dto import (
    CommentNodeDTO,
    CommentThreadDTO,
    CreateCommentCommand,
    DeleteCommentCommand,
    GetPostInteractionStatsQuery,
    LikeStateDTO,
    ListCommentsQuery,
    PostInteractionStatsDTO,
    ToggleLikeCommand,
)
from app.domain.blog.entities import PostStatus
from app.domain.blog.exceptions import PostNotFoundError
from app.domain.interaction.entities import Comment
from app.domain.interaction.exceptions import (
    CommentNotFoundError,
    InteractionClosedError,
    InteractionTargetNotFoundError,
)
from app.domain.interaction.value_objects import CommentContent, LikeTargetType

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from app.domain.blog.entities import Post
    from app.domain.blog.repositories import PostRepository
    from app.domain.identity.entities import User
    from app.domain.identity.repositories import UserRepository
    from app.domain.interaction.repositories import CommentRepository, LikeRepository


# ──────────────────────────── 内部辅助 ────────────────────────────


def _comment_id(comment: Comment) -> UUID:
    """取评论 id，为空说明实体没落过库。

    仓储返回的实体必然有 id，所以这里只是为了让类型检查器收窄
    ``UUID | None`` → ``UUID``。写成函数而不是在每个调用点 ``assert``：
    ``assert`` 在 ``-O`` 下会被整个剥掉，留不下任何保证。
    """
    if comment.id is None:  # pragma: no cover - 仓储返回的实体必然已落库
        raise ValueError("评论尚未落库，无法取得 id")
    return comment.id


def _post_id(post: Post) -> UUID:
    """同上，用于文章实体。"""
    if post.id is None:  # pragma: no cover
        raise PostNotFoundError()
    return post.id


async def _load_visible_post(
    posts: PostRepository,
    post_id: UUID,
    *,
    viewer_id: UUID | None,
) -> Post:
    """按 id 取一篇**调用者看得见**的文章，否则 404。

    抽成公共函数而不是每个用例各写一遍：这几行里隐含一条规则——
    「看不见的文章等同于不存在」（草稿与归档只有作者本人可见）。
    写一次，所有入口自动一致；分散写法迟早会出现某个入口忘了调
    ``ensure_visible_to``，于是「别人草稿的评论」泄露了出去。

    ``get_by_id`` 已经在 SQL 里排除了软删除，所以「取不到」同时覆盖
    「本来就不存在」与「已被删除」，不需要再判一次。
    """
    post = await posts.get_by_id(post_id)
    if post is None:
        raise PostNotFoundError()
    post.ensure_visible_to(viewer_id)
    return post


def _ensure_interaction_open(post: Post) -> None:
    """文章当前状态是否开放互动（评论 / 点赞）。

    规则只有一条：**只有已发布的文章可以互动**。
        草稿：它还没有读者，评论自己的草稿没有意义，而且草稿一旦被删，
              评论会连带消失——评论不该承载「还没决定的文章」这个状态。
        已归档：语义是「作者主动撤下了它」。允许新评论，等于让一条讨论
              在一个作者已经不想让它公开的页面上继续生长。
              已归档的文章对非作者而言本来就 404，所以这条规则主要是在
              阻止作者在自己的归档文章下继续评论——那基本只会是误操作。

    这里抛 40940 而不是 404：文章确实存在、调用者也确实看得见它，
    只是当前状态不允许。伪装成 404 会让作者以为自己的文章没了。
    """
    post.ensure_not_deleted()
    if post.status != PostStatus.PUBLISHED:
        raise InteractionClosedError()


async def _load_comment(comments: CommentRepository, comment_id: UUID) -> Comment:
    """按 id 取一条**未被撤回**的评论，否则 404。

    为什么读出来之后立刻判 ``is_deleted``（而不是交给调用方）：
        「已撤回的评论等同于不存在」是这个上下文的一条不变量，
        就像「已软删除的文章等同于不存在」。让每个入口各自记得判一次，
        迟早会漏——而漏掉的后果是「撤回」形同虚设。
    """
    comment = await comments.get_by_id(comment_id)
    if comment is None:
        raise CommentNotFoundError()
    comment.ensure_not_deleted()
    return comment


def _display_name(user: User | None, user_id: UUID) -> str:
    """用户实体 → 界面上该显示的名字。

    ``display_name`` 优先、回落 ``username``：
        与 ``UserDTO.from_entity`` 逐字一致。两处各写一份早晚会分叉，
        而它们分叉的表现是「同一张页面上同一个人有两个名字」，
        看起来很像缓存问题，查起来很耗时间。

    用户取不到（``None``）时回落成一个截断的 id，而不是空串：
        用户目前**没有**删除入口，而且 ``comments.author_id`` 的外键是 RESTRICT，
        所以这条路在请求路径上根本走不到。但真走到了（人工改库、
        将来加了注销），一个「用户 3f9a2b1c」远比一个空名字可诊断——
        空名字在界面上表现为「回复了空白」，而 id 能直接拿去查。
    """
    if user is None:
        return f"用户 {str(user_id)[:8]}"
    return user.display_name or user.username.value


async def _resolve_display_names(
    users: UserRepository,
    author_ids: Iterable[UUID],
) -> dict[UUID, str]:
    """把一批评论作者的 id 解析成可直接显示的名字（一次查询）。

    为什么做成一个能解析**一批** id 的函数而不是在拼树里逐个查：
        拼树是个递归过程，在递归里调仓储就是“在循环里查库”——
        一页树几十个作者、几十次往返，而且随着树的变深还会更糟。
        这里先把整棵树的作者 id 收齐、查一次、再拿着字典拼。

    ``set`` 去重不是优化而是正确性的一部分：
        同一个人在一页里发了好几条评论是常态，
        不去重会把同一个 id 反复传给 ``IN (...)``（结果一样，白传）。

    ``sorted`` 只是为了给 SQL 一个确定的参数顺序：
        对同一份数据生成同一条 SQL，日志与 ``EXPLAIN`` 对比起来才有意义。
        正确性不依赖顺序（返回值是字典）。
    """
    unique_ids = set(author_ids)
    if not unique_ids:
        return {}
    found = await users.get_by_ids(sorted(unique_ids))
    return {user_id: _display_name(found.get(user_id), user_id) for user_id in unique_ids}


def _build_thread(
    roots: Sequence[Comment],
    descendants: Sequence[Comment],
    *,
    like_counts: Mapping[UUID, int],
    liked_ids: Iterable[UUID],
    author_names: Mapping[UUID, str],
) -> tuple[CommentNodeDTO, ...]:
    """把两条平坦查询的结果拼成**任意深度**的评论树。

    拼树放在应用层而不是仓储里，理由见 ``CommentRepository`` 的模块说明：
    仓储只负责数据，形状留给上层。

    整个拼树就两步：
        ① 按 ``parent_id`` 把后代归到各自的父节点下（一次字典分组）；
        ② 从根开始递归下降。
    第②步用递归函数而不是显式栈，是因为缩进规则读起来就是递归的形状；
    深度受真实数据限制（评论链不会很深），不会撞栈。

    ★ 剪枝是**自底向上**的，而且只能在这里做：
        SQL 那边只管「这一页有哪些可见根评论」（那里必须能分页，
        所以只能算出一组 id）；一旦某条根评论进了这一页，
        它整棵子树都是**全取**回来的（后代不分页），
        于是“哪条留、哪条丢”可以在内存里精确地一次算完。
        规则是：一条已撤回的评论，**只要下面还有活着的后代**就保留为墓碑。
        这正好是「对话没有断在半空」的形式化描述：
        真正的判据是“有没有活着的后代”，而不是“有没有直接子行”——
        中间层可能自己也被撤回了（那条被撤回的子行不是存活的后代）。
        自底向上递归恰好天然算对这件事：子节点先剪，父节点再看
        手里还剩几个孩子。反过来（自上而下）就得上两次。

    ★ ``parent_author_display_name`` 取自**直接父节点**，而不是根评论：
        界面要说的是「他回的是哪句话」，而那就是他的 ``parent_id``。
        名字从递归上一层带下来（而不是再查一次父节点），
        因为父节点就在栈上——为一件手里已有的事情再查一次库，
        是这类渲染代码里最常见的浪费。

    ``author_names`` 缺 key 不会发生（调用方已经按整棵树的作者 id 收齐了），
    真缺了也只会得到一个 id 形式的闲名字，不会抛错：
        为了一个不会发生的分支让整个列表页 500，不划算。
        （真缺了说明调用方漏收集了作者 id，集成测试里会当场看出来。）
    """
    liked = set(liked_ids)
    children_by_parent: dict[UUID, list[Comment]] = {}
    for comment in descendants:
        # 保留**已删除**的后代：它们是“墓碑的子树还在不在”这个判据的原料，
        # 要交给递归去判断该不该接着往下走（见上面★）
        if comment.parent_id is not None:
            children_by_parent.setdefault(comment.parent_id, []).append(comment)

    def name_of(user_id: UUID) -> str:
        return author_names.get(user_id) or _display_name(None, user_id)

    def build(comment: Comment, parent_author_name: str | None) -> CommentNodeDTO | None:
        """构造一个节点；返回 ``None`` 表示这条评论被剪掉了。"""
        comment_id = _comment_id(comment)
        replies: list[CommentNodeDTO] = []
        for child in children_by_parent.get(comment_id, ()):
            node = build(child, name_of(comment.author_id))
            if node is not None:
                replies.append(node)
        # 已撤回且没有一个活着的后代：它不承载任何对话，只是个纯墓碑。
        # 对根评论与中间层一视同仁——这正是“墓碑规则”在任意深度下唯一自洽的写法
        if comment.is_deleted and not replies:
            return None
        return CommentNodeDTO.from_entity(
            comment,
            author_display_name=name_of(comment.author_id),
            # 根评论的 parent_id 本就是 None，这里跟着为 None，两者不会矛盾
            parent_author_display_name=parent_author_name,
            like_count=like_counts.get(comment_id, 0),
            liked_by_me=comment_id in liked,
            replies=tuple(replies),
        )

    nodes: list[CommentNodeDTO] = []
    for root in roots:
        # 根的 parent_author_name 恒为 None：界面不会在根评论上写「回复 xxx」
        node = build(root, None)
        if node is not None:  # pragma: no cover - 可见根评论必然有活着的后代
            nodes.append(node)
    return tuple(nodes)


# ──────────────────────────── 读 ────────────────────────────


class ListCommentsUseCase:
    """读一篇文章的评论树（公开，未登录可访问）。

    只要求「文章对调用者可见」，**不要求已发布**：
        作者看自己草稿的评论区应当能读到内容（历史上发布过又下架的文章
        会留下评论），而游客对这篇草稿本来就 404。
        真正被「必须已发布」限制的是**写**入（见 ``_ensure_interaction_open``）。

    它同时是三个上下文的接合点：文章（blog）、评论与点赞（interaction）、
    作者名（identity）。它们必须在**同一个事务**里读，否则
    「评论已经写进去了但作者还没落地」这种中间态会泄露成一个无名评论。
    """

    def __init__(
        self,
        posts: PostRepository,
        comments: CommentRepository,
        likes: LikeRepository,
        users: UserRepository,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._likes = likes
        self._users = users

    async def execute(self, query: ListCommentsQuery) -> CommentThreadDTO:
        post = await _load_visible_post(
            self._posts,
            query.post_id,
            viewer_id=query.viewer_id,
        )
        post_id = _post_id(post)

        # 总数与数据必须用同一套过滤条件（都在仓储里），否则会出现
        # 「共 10 条」但翻到第二页就空了——分页最常见的那个 bug。
        total = await self._comments.count_threads(post_id)
        roots = await self._comments.list_thread_roots(post_id, query.offset, query.limit)

        # 没有根评论就不必再查任何东西：空页面上的三次批量查是纯粹的浪费
        descendants: list[Comment] = []
        like_counts: dict[UUID, int] = {}
        liked_ids: set[UUID] = set()
        author_names: dict[UUID, str] = {}
        if roots:
            root_ids = [_comment_id(root) for root in roots]
            # 一次性取回**整棵子树**（任意深度），而不是只取一层：
            # 只取一层在两层树时代是对的，改成无限深度后会静默丢掉第三层往后
            descendants = list(await self._comments.list_descendants(root_ids))
            # 一次把根评论和后代的 id 都算进去：点赞是按评论 id 存的，
            # 根与后代在这件事上没有区别，分两次查只是白白多一次往返
            target_ids = [*root_ids, *(_comment_id(item) for item in descendants)]
            like_counts = await self._likes.count_many(
                target_type=LikeTargetType.COMMENT,
                target_ids=target_ids,
            )
            # 未登录时根本不发这次查询：游客没有「我赞过哪些」这个概念，
            # 而把 user_id 传 None 进仓储会把「有没有登录」渗进数据层
            if query.viewer_id is not None:
                liked_ids = await self._likes.liked_ids(
                    query.viewer_id,
                    target_type=LikeTargetType.COMMENT,
                    target_ids=target_ids,
                )
            # 作者名要按**整棵树**收齐后查一次（见 _resolve_display_names）：
            # 已删除的评论也要算进去——墓砾上总显示谁的发言被撤回了，
            # 而“作者已注销”只能显示成 id，读者反而更困惑。
            author_names = await _resolve_display_names(
                self._users,
                [root.author_id for root in roots] + [item.author_id for item in descendants],
            )

        return CommentThreadDTO(
            items=_build_thread(
                roots,
                descendants,
                like_counts=like_counts,
                liked_ids=liked_ids,
                author_names=author_names,
            ),
            total=total,
            offset=query.offset,
            limit=query.limit,
        )


class GetPostInteractionStatsUseCase:
    """批量取多篇文章的互动统计（赞数、评论数、我赞过没）。

    这个用例是 ``blog`` 与 ``interaction`` 两个上下文的**接合点**：
        文章列表与详情要显示互动数据，但那些数据属于互动上下文。
        与其让博客的仓储去 JOIN 互动的表（那会把两个上下文的表结构焊死在一起），
        不如让表现层把两个用例的结果拼起来——它本来就是组装点。

    为什么要批量：文章列表一次 20 篇，逐篇查就是 40 次往返（赞数 + 评论数）。
    批量版本恒定 2~3 次查询，与页大小无关。
    """

    def __init__(self, comments: CommentRepository, likes: LikeRepository) -> None:
        self._comments = comments
        self._likes = likes

    async def execute(
        self, query: GetPostInteractionStatsQuery
    ) -> dict[UUID, PostInteractionStatsDTO]:
        if not query.post_ids:
            # 空列表要提前返回：某些驱动对 ``WHERE id IN ()`` 会报语法错误，
            # 而「列表页这一页恰好是空的」是极常见的正常情况
            return {}

        comment_counts = await self._comments.count_by_posts(query.post_ids)
        like_counts = await self._likes.count_many(
            target_type=LikeTargetType.POST,
            target_ids=query.post_ids,
        )
        liked_ids: set[UUID] = set()
        if query.viewer_id is not None:
            liked_ids = await self._likes.liked_ids(
                query.viewer_id,
                target_type=LikeTargetType.POST,
                target_ids=query.post_ids,
            )

        # 以**请求的 id 列表**为准构造结果，而不是以查询结果的键为准：
        # 没有评论/没有赞的文章不会出现在聚合结果里，若照着结果构造，
        # 调用方就会拿不到那几篇文章的条目，只能到处写 ``.get(id)`` 判空。
        return {
            post_id: PostInteractionStatsDTO(
                post_id=post_id,
                like_count=like_counts.get(post_id, 0),
                comment_count=comment_counts.get(post_id, 0),
                liked_by_me=post_id in liked_ids,
            )
            for post_id in query.post_ids
        }


# ──────────────────────────── 写 ────────────────────────────


class CreateCommentUseCase:
    """发表评论或回复。

    「回复一条回复」是这个用例要处理的**正常输入**，不是错误：
        它落库时保留真实的 ``parent_id``，于是树可以是任意深度，
        而界面只需要从第二层起不再加缩进。
        早先的版本会把它归一到根评论下（树恒为两层），
        代价是「他到底在回谁」在落库那一刻就被抹掉了——不可逆。
    """

    def __init__(
        self,
        posts: PostRepository,
        comments: CommentRepository,
        users: UserRepository,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._users = users

    async def execute(self, command: CreateCommentCommand) -> CommentNodeDTO:
        # 先看文章：看得见（404）且开放互动（409）。顺序不能反——
        # 对别人的草稿，我们要回 404（不存在）而不是 409（存在但不开放），
        # 后者等于承认「这里有一篇你看不到的文章」。
        post = await _load_visible_post(
            self._posts,
            command.post_id,
            viewer_id=command.actor_id,
        )
        _ensure_interaction_open(post)
        post_id = _post_id(post)

        parent: Comment | None = None
        if command.parent_id is not None:
            parent = await self._comments.get_by_id(command.parent_id)
            # 父评论不存在、已被撤回，或**不属于这篇文章**，一律当作「找不到」：
            # 让调用者能区分这三种情况，只会泄露「别处存在这样一条评论」。
            if parent is None or parent.post_id != post_id:
                raise CommentNotFoundError()
            parent.ensure_not_deleted()

        comment = Comment.create(
            post_id=post_id,
            author_id=command.actor_id,
            # 值对象的构造就是校验，非法内容在这一行被拦下（40040）
            content=CommentContent(command.content),
            # ★ 如实保存用户点的那条评论，不做任何归一。
            #   允许指向第 N 层回复，于是树可以一直深下去——
            #   存真实父子关系，界面才有机会自己决定缩几级。
            parent_id=None if parent is None else _comment_id(parent),
        )

        created = await self._comments.add(comment)
        # 刚发出来的评论不可能有人赞过，所以这里给默认的 0 / False 是**正确**的，
        # 不是「忘了查统计」——与读路径上必须显式传统计值的规矩并不冲突。
        # 但作者名与「回复了谁」必须查：它们不能从这颗新评论自身推出来，
        # 而返回值会被直接插进前端的评论树，空名字会在那一刻就显示出来。
        author_names = await _resolve_display_names(
            self._users,
            ([command.actor_id] if parent is None else [command.actor_id, parent.author_id]),
        )
        return CommentNodeDTO.from_entity(
            created,
            author_display_name=author_names[command.actor_id],
            parent_author_display_name=(None if parent is None else author_names[parent.author_id]),
        )


class DeleteCommentUseCase:
    """撤回评论（软删除）。

    删除的是**自己**的评论；管理员凭 ``comment:delete_any`` 可以删任何人的。
    无论谁删，这条评论都会被替换成墓碑（内容不外传、界面显示「已删除」），
    它下面的回复保持原位——那些回复是别人写的内容，不该因为楼上撤回而消失。
    """

    def __init__(self, comments: CommentRepository) -> None:
        self._comments = comments

    async def execute(self, command: DeleteCommentCommand) -> None:
        comment = await self._comments.get_by_id(command.comment_id)
        if comment is None:
            raise CommentNotFoundError()

        # 归属判断（40340）。放在最前面而不是「先删再判」：
        # 越权请求不该在库里留下任何痕迹，哪怕最后会回滚。
        comment.ensure_deletable_by(
            command.actor_id,
            has_override=command.actor_can_override,
        )

        # 幂等：已撤回的评论再删一次静默成功，不报 404。
        # ``DELETE`` 会被网关重试、被用户连点，报错会让「删成功却提示失败」。
        comment.soft_delete()
        await self._comments.update(comment)


class ToggleLikeUseCase:
    """点赞 / 取消点赞（同一个入口）。

    为什么是 toggle 而不是 POST /likes + DELETE /likes/{id}：
        界面上的动作是「点一下心形」，前端并不知道也不关心
        「这一下是点赞还是取消」——它只知道当前状态，然后点了一下。
        做成 toggle 之后，前端不需要在本地维护「该调哪个方法」的分支
        （那个分支正是「取消时误发成点赞」的 bug 来源），
        而且天然幂等于「同一状态被点两次」这种重试场景。

    返回的是操作**之后**的真实计数值，前端用它覆盖乐观更新的数字，
    这样既有点击即变的反馈，又不会把计数越用越偏。
    """

    def __init__(
        self,
        posts: PostRepository,
        comments: CommentRepository,
        likes: LikeRepository,
    ) -> None:
        self._posts = posts
        self._comments = comments
        self._likes = likes

    async def execute(self, command: ToggleLikeCommand) -> LikeStateDTO:
        # 先收敛目标类型（40041）：这是唯一一个由外部输入决定「写到哪张逻辑分区」
        # 的字段，必须显式校验，不能靠默认值兜底。
        target_type = LikeTargetType.parse(command.target_type)
        await self._ensure_target_exists(
            target_type,
            command.target_id,
            # 把「谁在点」传下去：可见性是**相对于访问者**的，
            # 同一个目标对不同的人有不同的答案（自己的草稿 vs 别人的草稿）
            viewer_id=command.actor_id,
        )

        liked_before = await self._likes.is_liked(
            command.actor_id,
            target_type=target_type,
            target_id=command.target_id,
        )
        if liked_before:
            await self._likes.unlike(
                command.actor_id,
                target_type=target_type,
                target_id=command.target_id,
            )
        else:
            # 幂等插入（ON CONFLICT DO NOTHING）：连点两下不会造出两行，
            # 并发下的第二次会静默命中冲突而不是抛 500
            await self._likes.like(
                command.actor_id,
                target_type=target_type,
                target_id=command.target_id,
            )

        # 计数在写入之后现查，而不是在 Python 里对旧值 +1/-1：
        # 后者在并发下会互相覆盖（两个请求各自读到 N，都写回 N±1）。
        # 让数据库聚合，计数与真实行数永远一致。
        count = await self._likes.count(
            target_type=target_type,
            target_id=command.target_id,
        )
        return LikeStateDTO(
            target_type=target_type,
            target_id=command.target_id,
            liked=not liked_before,
            like_count=count,
        )

    async def _ensure_target_exists(
        self,
        target_type: str,
        target_id: UUID,
        *,
        viewer_id: UUID,
    ) -> None:
        """点赞前确认目标**看得见且开放互动**（40441 / 40940）。

        文章分两步判，顺序不能反：
            ① ``ensure_visible_to``（→ 40441）——看不见的东西不许点赞。
               少了这一步，这个接口就成了探测工具：别人的草稿 id
               会得到 40940（“存在但未发布”）、不存在的 id 得到 40441，
               两次试探就能确认“这篇文章确实存在”。
               评论接口对别人的草稿回 404，两个入口必须同口径。
            ② ``_ensure_interaction_open``（→ 40940）——看得见不等于能互动。
               作者点赞自己的草稿在这里被拦下：草稿的赞数没有意义，
               而它会跟着发布一起出现在读者眼前。

        为什么点赞也要复核文章状态（而不是只靠评论存在性推断）：
            一篇文章被下架之后，它的评论还在库里——只判评论存在
            会让「已归档文章下的评论仍能被点赞」，而归档意味着作者
            不希望这个页面继续积累新的互动。

        评论只判存在与未撤回（40441）：评论没有“草稿”形态，
            它一旦可见就是可见的，所以不需要第二次判断。

        为什么把 ``PostNotFoundError`` 转成 ``InteractionTargetNotFoundError``：
            ``ensure_visible_to`` 抛的是文章上下文的 40430。但本接口的词汇里
            没有「文章」这个概念，只有**多态目标**——所以「目标不存在」
            应当只有 40441 这一个答案。不转的话，同一句“这个 id 对你不存在”
            会因为底层行是否物理存在而给出两个不同的码（不存在的 uuid 得 40441、
            别人的草稿得 40430），前端就得为同一件事写两条分支。
            对比：评论接口的 404 仍然是 40430，因为那个接口的词汇确实是「文章」——
            **错误码的口径跟着端点的词汇走，而不是跟着抛出它的那层走**。
        """
        if target_type == LikeTargetType.POST:
            post = await self._posts.get_by_id(target_id)
            # get_by_id 已经在 SQL 里排除了软删除，取不到就是真的不存在
            if post is None:
                raise InteractionTargetNotFoundError()
            try:
                post.ensure_visible_to(viewer_id)
            except PostNotFoundError:
                # 别人的草稿 / 已归档的文章：对访问者而言就是不存在
                raise InteractionTargetNotFoundError() from None
            _ensure_interaction_open(post)
            return

        comment = await self._comments.get_by_id(target_id)
        if comment is None or comment.is_deleted:
            raise InteractionTargetNotFoundError()


__all__ = [
    "CreateCommentUseCase",
    "DeleteCommentUseCase",
    "GetPostInteractionStatsUseCase",
    "ListCommentsUseCase",
    "ToggleLikeUseCase",
]
