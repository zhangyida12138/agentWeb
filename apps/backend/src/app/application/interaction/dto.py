"""互动上下文的应用层数据载体（命令 / 查询 / DTO）。

与 ``application/blog/dto.py`` 同一套约定：

    · 命令与查询是 ``frozen=True`` 的 dataclass，且是**扁平**的
      （不做 ``Command(actor=User(...))`` 这种嵌套）——
      扁平结构让「这个用例需要哪些输入」一眼可见，
      也让表现层构造命令时不需要先拼装一半的对象图。
    · DTO 是标准库 dataclass，**不是 Pydantic**：
      应用层一旦用了 Pydantic，就等于把「HTTP 序列化」这件事写进了业务层，
      于是同一个用例想被 CLI / 定时任务复用时，会莫名其妙地要求一个 HTTP 形状的请求。
      Pydantic 只出现在 presentation 的 schemas 里（那才是真正的边界）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.interaction.entities import Comment

# ──────────────────────────── 出参 DTO ────────────────────────────


@dataclass(frozen=True, slots=True)
class CommentNodeDTO:
    """评论树里的一个节点（含它下面的全部回复）。

    ``replies`` 直接内嵌同类型的元组，而不是另开一个 ``ReplyDTO``：
        回复与根评论在**所有**字段上完全一致（它是同一种东西，只是位置不同），
        分成两个类就得写两份 ``from_entity``、两份 schema、两份前端类型，
        而它们永远不会不同——这种「为了对称而复制」的代价会在每次改字段时收一次。
        元组（而不是 list）是为了配合 ``frozen=True``：
        一个可以被外部 append 的 list 会让「不可变」这个承诺变成半句话。

    ``content`` 在评论被撤回时是**空串**（见 ``Comment.public_content``），
    ``is_deleted`` 是给界面用的——前端据此渲染「该评论已删除」占位，
    而不是渲染一个空段落。

    树是**任意深度**的：``replies`` 里可以再套 ``replies``，层数不设限。
        界面只在第二层缩进一次（再深也停在同一级），
        但**数据层不替界面做这个决定**——
        详情页要显示「3 条回复」、将来要做「只看某人参与的讨论」，
        都需要真实的层级关系，而它一旦被压平就再也算不出来了。

    ``author_display_name`` / ``parent_author_display_name`` 是**服务端解析好的名字**：
        界面要显示「小明 回复 小红」，而响应里只有两个 uuid，
        让前端拿着 ``author_id`` 回查 ``GET /users/{id}`` 会把一个 N+1
        从数据库搬到浏览器（一页评论树几十个请求），
        顺带把「谁能看到谁的用户名」这个授权问题也弄得无处安放。
        名字由用例**批量**查一次查询填好（见 ``ListCommentsUseCase``）。

        ``parent_author_display_name`` 为 None 表示这是一条根评论，
        界面不该渲染「回复 xxx」。
        它跟着 ``parent_id`` 一起出现、一起为 None，
        于是界面可以只看名字而不用自己拼「有 parent_id 但名字缺失」这种情形——
        那种半截状态只会在服务端拼树出错时出现，会当场表现出来。
    """

    id: UUID
    post_id: UUID
    author_id: UUID
    author_display_name: str
    # 被回复者的显示名。根评论为 None
    parent_author_display_name: str | None
    parent_id: UUID | None
    content: str
    is_deleted: bool
    like_count: int
    liked_by_me: bool
    created_at: datetime
    updated_at: datetime
    replies: tuple[CommentNodeDTO, ...] = ()

    @classmethod
    def from_entity(
        cls,
        comment: Comment,
        *,
        author_display_name: str,
        parent_author_display_name: str | None = None,
        like_count: int = 0,
        liked_by_me: bool = False,
        replies: tuple[CommentNodeDTO, ...] = (),
    ) -> CommentNodeDTO:
        """由实体 + 已解析的名字 + 两个统计值构造节点。

        为什么点赞数要**从外面传进来**而不是放在实体上：
            它是 ``likes`` 表的聚合结果，不属于 ``Comment`` 这条记录。
            把它做成实体的字段，就等于宣布「评论实体自带赞数」，
            于是每处构造评论的地方（测试、导入脚本）都要考虑它填什么，
            还会诱导出「实体上的赞数过期了怎么办」这类假问题。
            统计值是用例查出来再拼上去的，实体保持纯粹。

        ``author_display_name`` 也走同一条路（传进来而不是从实体推）：
            名字在**另一个上下文**（identity）里，``Comment`` 只知道 ``author_id``。
            让实体自己去查用户，就是让领域实体拿一个仓储——
            那是把整个分层拆掉。解析名字是用例的编排职责。

        点赞数默认 0 / 未赞：这个默认值只给「不需要统计」的场景用
        （单测、未来可能的通知场景），**请求路径上一律显式传入**——
        默认值在请求路径里被静默使用，表现就是「赞数永远是 0」。
        名字没有默认值，正是为了不留这种口子：
        少传一个名字，代码根本跑不起来（而不是渲染出一个空名字）。
        """
        if comment.id is None:  # pragma: no cover - 仓储返回的实体必然有 id
            raise ValueError("评论尚未落库，无法构造 DTO")
        return cls(
            id=comment.id,
            post_id=comment.post_id,
            author_id=comment.author_id,
            author_display_name=author_display_name,
            parent_id=comment.parent_id,
            parent_author_display_name=parent_author_display_name,
            content=comment.public_content,
            is_deleted=comment.is_deleted,
            like_count=like_count,
            liked_by_me=liked_by_me,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            replies=replies,
        )


@dataclass(frozen=True, slots=True)
class CommentThreadDTO:
    """一页评论树。

    ``total`` 是**根评论**的条数（不是所有评论），因为分页的也是根评论：
        如果这里给「全部评论数」，前端会拿它算出一个远大于实际页数的总页数，
        然后发现最后一页是空的。名字上故意不叫 ``comment_total``——
        容易误读成「评论总数」。要看真正的评论总数用文章列表/详情里的
        ``comment_count``。
    """

    items: tuple[CommentNodeDTO, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class PostInteractionStatsDTO:
    """一篇文章的互动统计（给文章列表与详情用）。"""

    post_id: UUID
    like_count: int = 0
    comment_count: int = 0
    liked_by_me: bool = False


@dataclass(frozen=True, slots=True)
class LikeStateDTO:
    """点赞开关操作后的最新状态。

    **返回操作后的真实计数**，而不是让前端自己 ``+1``：
        乐观更新（前端先改数字再等响应）能让按钮立刻有反馈，
        但「以为 +1 了其实没写进去」会让计数越用越偏。
        后端回一个权威数字，前端在 ``onSuccess`` 里覆盖掉乐观值，
        既快又不会漂。
    """

    target_type: str
    target_id: UUID
    liked: bool
    like_count: int


# ──────────────────────────── 入参 ────────────────────────────


@dataclass(frozen=True, slots=True)
class ListCommentsQuery:
    """读某篇文章的评论树。

    ``post_id`` 而不是 slug：评论接口的路径参数是文章 id（与 ``POST /likes/toggle``
    一致）。两个互动入口用同一个标识不是巧合——点赞的目标本来就是一个 id
    （文章和评论共用一套多态目标），如果评论接口改成收 slug，
    同一个页面上就会同时存在「按 slug 读评论」和「按 id 点赞」，
    迟早有人把 slug 传给点赞接口（换来一个 40441）。
    而文章 id 前端从详情响应里就已经拿到了，不需要多一次请求。
    """

    post_id: UUID
    viewer_id: UUID | None
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class CreateCommentCommand:
    """发表评论或回复。

    ``content`` 是**裸字符串**而不是 ``CommentContent``：
        命令是表现层构造的，如果它要求值对象，表现层就得 import 领域类型
        并自己 new 一个——那等于把领域校验挪到了 HTTP 边界，
        而「校验必须发生在领域」正是值对象存在的理由。
        用例内部第一件事就是 ``CommentContent(command.content)``。

    ``parent_id`` 为 None 表示这是一条根评论；
    非 None 表示「回复那条评论」，落库时**原样保留**（不归一到根）：
        回复一条回复时 parent_id 就是那条回复的 id，于是树可以是任意深度。
        层数由界面自己决定缩几级，数据模型不替它做取舍
        （理由见 ``Comment`` 与 ``repo`` 的说明：
        归一发生在落库那一刻，是不可逆的信息丢失）。
    """

    post_id: UUID
    actor_id: UUID
    content: str
    parent_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DeleteCommentCommand:
    """撤回评论（软删除）。

    ``actor_can_override`` 由表现层的守卫一并查出（它已经查过权限码，
    顺手判一下 ``comment:delete_any``），而不是在用例里再查一次权限。
    理由与博客一致：两次查询之间管理员可能被撤权，会出现
    「守卫放行了、这里说没有」的自相矛盾。共用同一份权限快照就不可能不一致。
    """

    comment_id: UUID
    actor_id: UUID
    actor_can_override: bool


@dataclass(frozen=True, slots=True)
class ToggleLikeCommand:
    """点赞 / 取消点赞（同一个入口）。

    ``target_type`` 是裸字符串，由用例用 ``LikeTargetType.parse`` 收敛：
        这是唯一一个「外部输入直接决定写入哪张逻辑分区」的字段，
        校验必须显式发生（40041），不能靠默认值兜底。

    ``target_id`` 是文章 **id** 而不是 slug：
        点赞的目标既可能是文章也可能是评论，两者共用一个 id 字段，
        所以它只能是 uuid。前端从文章详情里已经拿得到 ``post.id``，
        不需要多一次请求。
    """

    actor_id: UUID
    target_type: str
    target_id: UUID


@dataclass(frozen=True, slots=True)
class GetPostInteractionStatsQuery:
    """批量取多篇文章的互动统计（喂给文章列表 / 详情）。

    ``viewer_id`` 为 None（游客）时不查「我赞过哪些」，
    于是 ``liked_by_me`` 一律 False——这正是游客该看到的界面。

    ``post_ids`` 用元组而不是列表：查询是不可变的输入，
    元组避免调用方传进来之后又被谁 append 一下。
    """

    post_ids: tuple[UUID, ...]
    viewer_id: UUID | None = None


__all__ = [
    "CommentNodeDTO",
    "CommentThreadDTO",
    "CreateCommentCommand",
    "DeleteCommentCommand",
    "GetPostInteractionStatsQuery",
    "LikeStateDTO",
    "ListCommentsQuery",
    "PostInteractionStatsDTO",
    "ToggleLikeCommand",
]
