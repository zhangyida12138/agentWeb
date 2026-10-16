"""标签上下文的应用层 DTO。

入参（``*Command`` / ``*Query``）与出参（``*DTO``）一律标准库 dataclass，
理由与 ``application/blog/dto.py`` 相同：参数格式校验归表现层 schema，
序列化格式同理——应用层承载的是「已经合法的数据」。

与博客 DTO 的一处刻意差异：这里**没有** ``UNSET`` 哨兵。

    文章的编辑接口是 PATCH，有 6 个字段可以单独改，所以必须区分
    「没传这个字段」和「传了 null 要清空」——那是 ``Unset`` 存在的唯一理由。

    标签只有两个可编辑的标量字段（name、description），
    而它的编辑接口是 **PUT**：整份表示一起提交，没传 description 就等于要清空。
    既然不存在「哪个字段被省略了」这个问题，也就没必要引入哨兵。
    少一个概念，就少一处 ``isinstance(x, Unset)`` 写错的地方。

    ⚠️ 状态（status）**不在** PUT 的入参里，它有独立的接口。
       理由是权限不同：改名/改描述是作者自己的事，
       下架/删除是作用于「别人也在用的公共词汇」的审核动作，只有管理员能做。
       如果把 status 塞进同一个 body，就会出现「同一个请求里，
       有的字段普通人能改、有的只有管理员能改」——这种规则既写不进 schema，
       也极容易在后续改动里被漏掉。拆成两个接口，权限边界就是两条路由。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.tag.entities import Tag, TagType

# ──────────────────────────── 入参：Query ────────────────────────────


@dataclass(frozen=True, slots=True)
class ListTagsQuery:
    """标签列表查询。

    五个筛选参数**全部是 ``None`` 表示「不筛」**：
        这一层不设默认值，因为「默认只显示正常标签」是一个 **API 契约**，
        属于 HTTP 层该拍板的事（见 ``endpoints/tag.py`` 里 ``status`` 的默认值）。
        放进这里的结果是：任何非 HTTP 的调用方（脚本、后台任务）
        都会继承一个它并不知道、也无从覆盖的隐藏默认。
        ``offset`` / ``limit`` 是例外——分页参数无论从哪个入口调都必须有值。
    """

    offset: int
    limit: int
    status: str | None = None
    # ``type`` 在 Python 里是个内建名，占了它会让这个 dataclass 的字段
    # 在 IDE 里变灰、也可能被某些工具误判。用 ``tag_type`` 更安全，
    # 代价只是映射到 JSON 时要显式写一次别名（表现层 schema 负责）。
    tag_type: str | None = None
    keyword: str | None = None
    author_id: uuid.UUID | None = None


# ──────────────────────────── 入参：Command ────────────────────────────


@dataclass(frozen=True, slots=True)
class CreateTagCommand:
    """新建标签命令。

    ``actor_id`` 由表现层从当前登录用户注入，**绝不**从请求体里读：
        与 ``CreatePostCommand.author_id`` 同一条铁律——
        一旦允许客户端指定归属，任何人都能以别人的名义建标签。
        把「归属是谁」从入参里彻底移除，这个漏洞在类型层面就不存在。
    """

    name: str
    actor_id: uuid.UUID
    description: str | None = None
    # 只有管理员能到达这个用例（路由上挂着 ``tag:manage``），
    # 所以允许在这里指定 system —— 那是「创建一个平台内置标签」的显式动作。
    type: str = TagType.USER


@dataclass(frozen=True, slots=True)
class UpdateTagCommand:
    """编辑标签（PUT 语义：整份表示一起提交）。

    ``description`` 没有 ``Unset`` 也没有默认值以外的含义：
        ``None`` 就是「这个标签没有描述」。想清空就传 ``null`` 或不传，
        没有第三种可能。这是 PUT 与 PATCH 的分界，也是这里不需要哨兵的原因。

    ``actor_can_manage_any`` 由表现层查出来再传进来：
        「调用者是否持有 tag:manage（管理员）」是权限系统的事，
        而权限查询要访问 AccessRepository——另一个上下文的仓储。
        让标签的用例直接依赖它，会把两个上下文焊死在一起。
        表现层本来就是「装配所有上下文」的地方，由它算好再传，依赖方向最干净。
        （与 ``UpdatePostCommand.actor_can_override`` 完全同构。）
    """

    tag_id: uuid.UUID
    actor_id: uuid.UUID
    actor_can_manage_any: bool
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeTagStatusCommand:
    """变更标签状态（下架 / 恢复 / 软删除共用）。

    三个动作共用同一个入参形状，所以不再拆成三个只差一个字符串的类——
    拆开的话，路由上也会跟着出现三条几乎一样的 ``@router.patch``，
    而它们唯一的差异就是 body 里的常量，前端还得知道该调哪一条。

    **没有 ``actor_id`` / ``actor_can_manage_any``**，与上面两个命令不同：
        这个动作只有管理员能做（路由上挂着 ``tag:manage``），
        而管理员对所有标签都有权——包括系统标签。
        加上这两个参数就等于加一个永远为 ``True`` 的判断：
        它不会挡住任何请求，却会让读代码的人以为「这里可能放行/拦下某个人」，
        于是花时间去追一条根本不存在的分支。

        真正需要区分「谁的标签」的是 ``UpdateTagCommand``，它才有归属问题。
    """

    tag_id: uuid.UUID
    status: str


@dataclass(frozen=True, slots=True)
class DeleteTagCommand:
    """删除标签命令（软删除 = 把 status 置为 deleted）。

    为什么软删除还要单独开一个接口，而不复用 ``ChangeTagStatusCommand``：
        HTTP 语义不同，前端写法也不同——``DELETE /tags/{id}`` 是一个
        「把资源删掉」的意图，不需要客户端知道 ``"deleted"`` 这个魔法字符串。
        让客户端拼状态值，等于把内部枚举泄漏成 API 契约，
        以后想改这个值（比如拆成 ``deleted`` + ``deleted_reason``）就得同时改前端。

    同样**没有** actor 字段，理由见 ``ChangeTagStatusCommand``。
    """

    tag_id: uuid.UUID


# ──────────────────────────── 出参：DTO ────────────────────────────


@dataclass(frozen=True, slots=True)
class TagDTO:
    """标签视图。

    为什么**不暴露** ``created_at`` / ``updated_at``：
        这两列在表里存在（审计用），但没有任何接口需要它们——
        列表的排序键是 ``post_count`` 与 ``name``，详情页也不显示时间。
        加进 DTO 的代价不是两个字段，而是「它从此是 API 契约的一部分，
        以后想去掉就是破坏性变更」。等真的有人需要再加。

    ``author_id`` 可以为 ``None``：
        它表示「这个标签没有归属」——存量数据（迁移前建的标签没人记过作者）
        或创建者账号已注销（外键 ``ON DELETE SET NULL``）。
        这个 ``None`` 是有意义的信息，不该被替换成某个默认用户或空字符串。
    """

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    status: str
    type: str
    author_id: uuid.UUID | None
    post_count: int

    @classmethod
    def from_entity(cls, tag: Tag) -> TagDTO:
        """领域实体 → 视图。

        这里**没有** ``if tag.id is None: raise``，与 ``PostSummaryDTO`` 不同：
            ``Tag.id`` 的类型就是 ``uuid.UUID``（不是 ``UUID | None``），
            因为标识在 ``Tag.create()`` 里就生成了，实体从不存在"还没有 id"的状态。
            那篇文章里需要的运行时检查，在这里被类型本身消掉了——
            这也是「标识由领域生成」那个决定带来的一个附带好处。
        """
        return cls(
            id=tag.id,
            name=tag.name,
            slug=tag.slug,
            description=tag.description,
            status=tag.status,
            type=tag.type,
            author_id=tag.author_id,
            post_count=tag.post_count,
        )


@dataclass(frozen=True, slots=True)
class TagPageDTO:
    """分页出参。

    ``offset`` / ``limit`` 原样回显**归一化后**的值，而不是客户端传来的值：
        客户端传 ``limit=1000`` 会被夹到 100。如果回显 1000，
        前端会以为「我要了 1000 条，后端只给了 20 条」，然后算出错误的页数。
        回显实际生效值，前端的分页算术才能和后台对齐。
    """

    items: tuple[TagDTO, ...]
    total: int
    offset: int
    limit: int


__all__ = [
    "ChangeTagStatusCommand",
    "CreateTagCommand",
    "DeleteTagCommand",
    "ListTagsQuery",
    "TagDTO",
    "TagPageDTO",
    "UpdateTagCommand",
]
