"""博客上下文的实体：``Post``。

实体与值对象的分工（和 identity 上下文的 ``User`` 完全一致）：

===========================  =========================================
值对象                       没有身份，值相等就是同一个东西
                            （``Slug("a")`` 两个实例是同一件事）
实体                         有终身不变的身份（``id``），
                            状态随生命周期演进，靠领域方法保证「只能合法地变」
===========================  =========================================

所以「文章能不能发布」「这个人能不能改这篇」这类判断，全都写成 ``Post`` 上的方法，
而不是散在用例里的 if：用例负责编排（取数据、存数据、发事件），
实体负责拍板「这事合不合规矩」。将来新增一个「批量发布」入口时，
它照样只能走 ``publish()``，规则不会被绕过。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from app.domain.blog.exceptions import (
    InvalidPostStatusTransitionError,
    PostForbiddenError,
    PostNotFoundError,
)
from app.domain.blog.value_objects import (
    PostContent,
    PostTitle,
    Slug,
    TagName,
    normalize_cover_url,
    normalize_summary,
    normalize_tags,
)


class PostStatus:
    """文章状态取值与状态机。

    用「类 + 常量」而不是 ``enum.Enum``：
        enum 成员在 JSON 序列化、SQLAlchemy 绑定、Pydantic 校验之间来回转换需要额外处理，
        而这里的值本身就是字符串、直接进数据库、直接出接口——
        多一层枚举只会多一层 ``.value``。
        （access 上下文的 ``RoleCode`` 也是同样的取舍。）
    """

    DRAFT: Final = "draft"
    PUBLISHED: Final = "published"
    ARCHIVED: Final = "archived"

    ALL: Final = frozenset({DRAFT, PUBLISHED, ARCHIVED})

    """状态机（合法流转只有这三条）：::

        draft ──publish──> published ──publish──> (幂等，无变化)
                              ↑  │
                         publish  unpublish
                              │  ↓
                           archived ──publish──> published

    刻意**不提供** ``published → draft``：草稿态意味着「内容还不算数」，
    而已经发过、别人读过、可能被引用的文章退回 draft，
    会让它从所有列表里凭空消失——这更像是删除，那就该走软删除。
    """

    @classmethod
    def parse(cls, value: str) -> str:
        """把外部传入的状态字符串校验成合法取值（列表筛选用）。

        不合法时抛 ``InvalidPostStatusTransitionError``（40035）而不是静默忽略：
        ``?status=publihsed`` 这种笔误如果被当成「不筛选」，
        前端会收到整份列表并且看起来完全正常，问题会被埋到很久以后。
        """
        if value not in cls.ALL:
            raise InvalidPostStatusTransitionError(f"未知的文章状态：{value}")
        return value


# ──────────────────────────── PATCH 语义的哨兵 ────────────────────────────
# 为什么哨兵定义在**领域层**而不是像 identity 那样放在 application 层：
#     ``Post.update_content`` 需要它，而 domain 绝不能反向 import application
#     （依赖方向是 out → in，反向 import 会立刻构成环）。
#     于是哨兵下沉到 domain，application 层的命令对象反过来 import 这里。


class Unset:
    """「调用方没传这个字段」的标记。

    必须把「没传」和「传了 null」区分开，否则 PATCH 会退化成
    「没传的字段一律清空」——改个标题顺手把摘要和封面抹掉，这显然不对。
    用 UNSET 哨兵而不是 ``None`` 来表达「没传」：

    - ``UNSET`` → 本次不改
    - ``None``  → 本次清空
    - 其他值    → 本次改成该值
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()


def _utc_now() -> datetime:
    """当前时间（带时区）。

    绝不用 ``datetime.now()``：那是**本地时间且不带 tzinfo**，
    存进 ``TIMESTAMP WITH TIME ZONE`` 列时会被按「服务器所在时区」解释一次，
    于是同一个瞬间在不同机器上得到不同结果。测试本机通过、CI 换个时区就挂。
    """
    return datetime.now(UTC)


@dataclass(slots=True)
class Post:
    """文章实体（聚合根）。

    「聚合根」的意思是：``tags`` 属于这篇文章、不单独对外暴露 id 供增删，
    要对标签做任何改动只能通过改这篇文章来完成。这样就永远不存在
    「孤儿标签关联」或「两个入口并发改标签顺序」这类跨聚合问题。
    """

    author_id: uuid.UUID
    title: PostTitle
    slug: Slug
    content: PostContent

    id: uuid.UUID | None = None
    summary: str | None = None
    cover_url: str | None = None
    status: str = PostStatus.DRAFT
    # 首次发布时刻。之后反复 unpublish/publish **不会**刷新它——
    # 它表示「这篇文章第一次面向读者是什么时候」，刷新它等于篡改历史，
    # 列表按发布时间排序时文章会莫名其妙跳到最前。
    published_at: datetime | None = None
    view_count: int = 0
    deleted_at: datetime | None = None
    tags: tuple[TagName, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    # ────────────── 构造 ──────────────

    @classmethod
    def create(
        cls,
        *,
        author_id: uuid.UUID,
        title: PostTitle,
        slug: Slug,
        content: PostContent,
        summary: str | None = None,
        cover_url: str | None = None,
        tags: tuple[TagName, ...] = (),
    ) -> Post:
        """工厂方法：造一篇**尚未落库**的新文章。

        为什么必须有 ``id=uuid.uuid4()`` 这一行（而不是交给数据库）：
            底层的 ``UuidPk`` 用的是 ``insert_default``——那是**列级默认值**，
            而本项目的实体→模型映射是「把实体字段显式搬进模型」，
            构造 ``PostModel`` 时不会去读列默认值。所以 id 必须由领域先生成，
            否则 ``to_model`` 断言 id 非空时就会炸。
            （详见 infrastructure/persistence/base.py 的说明。）

        为什么 ``title`` / ``slug`` / ``content`` 收的是**值对象**而不是裸字符串：
            用例在调用本方法之前**必须先**构造 ``Slug``——因为要拿它去查重
            （``exists_slug``）。既然已经构造好了，这里再收裸串等于把
            「已经校验过」的保证丢掉又捡一遍。这跟 ``UserRepository.get_by_email``
            收 ``Email`` 值对象是同一个理由：接口按「已校验」的类型说话。

        三个可选字段收裸值、由本方法内部归一化：
            它们没有「先构造、再拿去查库」的需求，收裸值可以让用例少写三行样板，
            而且归一化规则（空串→None、长度上限）只在这一个地方生效。
        """
        return cls(
            id=uuid.uuid4(),
            author_id=author_id,
            title=title,
            slug=slug,
            content=content,
            summary=normalize_summary(summary),
            cover_url=normalize_cover_url(cover_url),
            tags=tags,
        )

    # ────────────── 可见性 / 归属 ──────────────

    def ensure_not_deleted(self) -> None:
        """已软删除的文章对**任何**入口都等同于不存在。

        把它抽成方法、并在每个读/写路径上调用，是为了让「软删除」成为一个
        无法忘掉的规则：只要是从实体出发的操作，就绕不过这一关。
        """
        if self.deleted_at is not None:
            raise PostNotFoundError()

    def ensure_owned_by(self, actor_id: uuid.UUID, *, has_override: bool) -> None:
        """行级归属判定：``actor_id`` 是不是这篇的作者（或持有管理特权）。

        两把尺子量一件事，顺序不能反：
            ① ``has_override`` —— 由表现层查出来「调用者是否有 ``post:update_any``」。
               有就直接放行：管理员需要能改任何人的文章（处理违规、修错字）。
            ② 否则比对 ``author_id`` —— 这正是「作者只能改自己的文章」的落点。

        注意本方法**不负责**判断「你有没有 post:update 权限」：
            那是角色/权限层面的事，由表现层的守卫负责（40320）。
            这里只管「这一篇是不是你的」（40330）。两件事分开，
            将来加一个「作者可以改自己的文章，哪怕没有被授予 post:update」
            的产品决策时，只需要调守卫、不必动领域。
        """
        self.ensure_not_deleted()
        if has_override:
            return
        if self.author_id != actor_id:
            raise PostForbiddenError()

    def ensure_visible_to(self, viewer_id: uuid.UUID | None) -> None:
        """公开阅读的可见性规则。

        已发布的文章：任何人（含未登录，``viewer_id is None``）都能读；
        未发布的草稿 / 归档：**只有作者本人**能看，其他人一律 404。

        为什么对「别人的草稿」回 404 而不是 403：
            403 等于承认「这里有一篇你没权限的文章」，可以据此枚举出
            标题、作者、发布时间等元信息。草稿的内容与存在性都属于作者私有，
            对外应当**完全不存在**。这与「已发布文章归属越界给 403」并不矛盾——
            已发布的文章本来就人人可读，它的存在不是秘密。
        """
        self.ensure_not_deleted()
        if self.status == PostStatus.PUBLISHED:
            return
        if viewer_id is not None and self.author_id == viewer_id:
            return
        raise PostNotFoundError()

    # ────────────── 内容变更（PATCH 语义） ──────────────

    def update_content(
        self,
        *,
        title: PostTitle | Unset = UNSET,
        content: PostContent | Unset = UNSET,
        summary: str | Unset | None = UNSET,
        cover_url: str | Unset | None = UNSET,
        tags: tuple[TagName, ...] | Unset = UNSET,
    ) -> None:
        """改标题 / 正文 / 摘要 / 封面 / 标签。

        ``slug`` **刻意不在这里**：它是地址，改动它会打断所有既有链接，
        所以它是独立的一次显式调用（``change_slug``），不会被「顺手保存」带上。
        这种「把危险操作从批量更新里摘出去」的做法，比在文档里写一句
        「请不要改 slug」可靠得多。
        """
        if title is not UNSET:
            self.title = title
        if content is not UNSET:
            self.content = content
        if summary is not UNSET:
            self.summary = normalize_summary(summary)
        if cover_url is not UNSET:
            self.cover_url = normalize_cover_url(cover_url)
        if tags is not UNSET:
            self.tags = normalize_tags(tags)
        self._touch()

    def change_slug(self, slug: Slug) -> None:
        """显式改 slug（唯一性由用例查库保证，领域只能管格式）。"""
        self.slug = slug
        self._touch()

    # ────────────── 状态流转 ──────────────

    def publish(self) -> None:
        """发布（幂等）。

        幂等很重要：编辑器上的「发布」按钮很可能被连点，
        或者前端在超时后重试。第二次调用若抛错，用户会看到
        「发布失败」但文章其实已经发布——这是最糟的一类反馈。
        """
        self.ensure_not_deleted()
        if self.status == PostStatus.PUBLISHED:
            return
        if self.status not in (PostStatus.DRAFT, PostStatus.ARCHIVED):
            raise InvalidPostStatusTransitionError(f"状态 {self.status} 不能发布")
        self.status = PostStatus.PUBLISHED
        if self.published_at is None:
            self.published_at = _utc_now()
        self._touch()

    def unpublish(self) -> None:
        """下架（published → archived）。

        语义是「归档」而不是「退回草稿」：文章已经对外存在过，
        它应当从公开列表消失、但保留全部历史信息（``published_at``、浏览量）。
        要真正不想让人看到，走软删除。
        """
        self.ensure_not_deleted()
        if self.status != PostStatus.PUBLISHED:
            raise InvalidPostStatusTransitionError("只有已发布的文章可以下架")
        self.status = PostStatus.ARCHIVED
        self._touch()

    # ────────────── 删除 / 浏览 ──────────────

    def soft_delete(self) -> None:
        """软删除（幂等）。

        不物理删除的原因：
            文章的 slug 是永久链接，物理删除后 slug 会被下一次「新建同标题的文章」占用，
            老链接会指向一篇**内容不同的新文章**——比 404 危险得多。
            软删除则让这一行继续占着 ``posts.slug`` 的唯一索引，
            老链接稳定地 404，而且误删可以恢复。
        """
        if self.deleted_at is not None:
            return
        self.deleted_at = _utc_now()
        self._touch()

    def register_view(self, view_count: int) -> None:
        """把仓储刚算出的新浏览量写回实体。

        浏览量由数据库做 ``view_count = view_count + 1`` 的原子自增，
        再由仓储回传新值，而不是在 Python 里 ``self.view_count += 1`` 后整体 update：
            后者是「读-改-写」，两个并发请求会各自读到 N、都写回 N+1，
            于是 100 次浏览只涨了 1。计数器必须让数据库来加。
        """
        self.view_count = view_count

    # ────────────── 内部 ──────────────

    def _touch(self) -> None:
        """任何字段变更后手动刷新 ``updated_at``。

        靠数据库的 ``onupdate`` 也能做，但那样 ``updated_at`` 只在事务真正
        flush 时才变，领域对象在内存里会处于「改了但时间戳还是旧的」的不一致状态。
        identity 的 ``User._touch`` 出于同样理由手工维护。
        """
        self.updated_at = _utc_now()


__all__ = ["UNSET", "Post", "PostStatus", "Unset"]
