"""互动上下文的仓储接口（端口）。

接口定义在 domain、实现在 infrastructure —— 依赖倒置的落点，
与 ``domain/blog/repositories.py`` 同一套约定：

    · 签名里能用值对象就用值对象（``CommentContent`` 已经在实体里了）；
    · 所有查询都必须在 SQL 里排除 ``deleted_at IS NOT NULL``，
      不依赖「调用方记得过滤」；
    · 实现方只 flush 不 commit —— 事务边界只属于 ``core/database.py::get_db``。

本文件还承载了一个**重要的架构决定**：点赞数与评论数不做冗余列，一律实时聚合。
理由写在 ``LikeRepository.count_many`` / ``CommentRepository.count_by_posts`` 上，
因为那两个方法正是这个决定的具体形状。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要，避免运行时循环 import
    from app.domain.interaction.entities import Comment


class CommentRepository(ABC):
    """评论仓储接口。

    与 ``PostRepository`` 有一处显著不同：**树的组装不在仓储里**。
    仓储只提供「这一页有哪些根评论」和「这些根评论下各有哪些后代」两个
    平坦查询，把父子关系拼成树是用例的事（``ListCommentsUseCase``）。

    为什么不让仓储直接返回嵌套结构：
        嵌套结构一旦成为仓储的返回类型，它就变成了一个**跨层的业务形状**——
        表现层要照着它写 schema，用例要照着它写逻辑，谁都改不动。
        而「平坦列表 + 一次性批量取后代」在数据库侧开销完全一样
        （都是两条查询，没有 N+1），拼树在内存里是 O(n) 的字典操作。
        让仓储只管数据、形状留给上层，将来想改成「按热度排回复」
        或者「只返回前 N 层」都不必动仓储接口。

    树的深度**不设上限**（早先的版本把层级压成两层，见 ``list_descendants``）：
        任意层的父子关系在图里就是两种遍历——向上找根、向下取子树，
        两个接口各管一个方向。
    """

    # ────────────── 写入 ──────────────

    @abstractmethod
    async def add(self, comment: Comment) -> Comment:
        """插入新评论，返回落库后的实体。

        回传实体而不是 ``None``：插入会由数据库补齐 ``created_at`` / ``updated_at``，
        回传一份「真实的当前状态」能保证用例拿到的对象和库里完全一致，
        而不是「一半内存值、一半未知」。
        """

    @abstractmethod
    async def update(self, comment: Comment) -> Comment:
        """按下标 upsert 已有评论（目前唯一用途是写 ``deleted_at``）。"""

    # ────────────── 单条查询 ──────────────

    @abstractmethod
    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        """按 id 取评论，**含已删除的**。

        这是本接口唯一不排除软删除的方法，因为它服务的是「删除」这个动作本身：
            ``DELETE /comments/{id}`` 要先把实体读出来判归属，再调 ``soft_delete()``。
            若这里也过滤掉已删除的行，第二次删除就会以 404 结束——
            而删除必须是幂等的（网关重试、用户连点都会造成重复请求）。
            调用方负责在需要时自己调 ``ensure_not_deleted()``。
        """

    # ────────────── 评论树（任意深度） ──────────────

    @abstractmethod
    async def count_threads(self, post_id: UUID) -> int:
        """**可见根评论**的总数，用于分页。

        什么叫「可见根评论」（本接口三个树相关方法的过滤条件必须**逐字一致**，
        否则会出现「共 10 条」但翻了 3 页就空了）：
            ① 未被删除的根评论；
            ② 已被删除、但**子树里还有未删除的评论**的根评论 ——
               保留它是为了让那些后代有个落点，
               读者看到的是「该评论已删除」而不是一条凭空冒出来的回复；
            ③ 排除「已删除且整棵子树都被撤回」的根评论 ——
               那是一条没有任何上下文的墓碑，显示出来只是噪音。

        ②③ 里的「子树」是**任意深度**，这一点在树变深之后变得很容易错：
            一条根评论被删、它下面被回复的那条也被删、但再下面还有一条活着 ——
            只看「有没有直接子行」会把这个根评论丢掉，
            它那条还活着的后代就跟着一起从界面上消失了。
        """

    @abstractmethod
    async def list_thread_roots(
        self,
        post_id: UUID,
        offset: int,
        limit: int,
    ) -> list[Comment]:
        """一页可见根评论（定义同 ``count_threads``），按**创建时间正序**（最早的在前）。

        为什么正序而不是像文章列表那样倒序：
            文章列表是「发现新内容」，新的有价值；评论区是「对话」，
            倒序会让回复出现在被回复的内容**之前**，读起来完全错乱。
            这也是绝大多数论坛的默认顺序。
        """

    @abstractmethod
    async def list_descendants(self, root_ids: Sequence[UUID]) -> list[Comment]:
        """给定一批根评论，一次性取出它们**全部后代**（含已删除的），按创建时间正序。

        「后代」而不只是「直接回复」：树的深度不限，一条根评论下面可能有
        回复的回复的回复。这个方法必须一路走到底，否则深层的评论会从响应里消失。

        后代不分页，是一个有意的取舍：
            一条根评论下的讨论在现实里是个小集合（几条到几十条），
            分页会把「一问一答」的上下文切断——翻到第二页时读者已经看不到
            被回复的那句话了。
        但根评论必须分页：一篇热文的根评论可以上千条，
        一次全返回会让响应体和内存都失控。

        收一个**列表**而不是单条 id，是为了避免 N+1：
            「每取一条根评论就查一次它的子树」在 20 条根评论时就是 21 次往返。

        含已删除的评论同样是必要的：
            删掉的是一条叶子评论时，直接丢弃即可（调用方在拼树时过滤）。
            但它如果有下级就必须保留——否则它的下级会变成孤儿。
            接口保持「全取」的一致性，让「可见性」这条规则只由拼树处一处决定。
        """

    # ────────────── 计数（用于文章列表 / 详情） ──────────────

    @abstractmethod
    async def count_by_post(self, post_id: UUID) -> int:
        """一篇文章的可见评论数（根评论 + 回复，都只算未删除的）。"""

    @abstractmethod
    async def count_by_posts(self, post_ids: Sequence[UUID]) -> dict[UUID, int]:
        """**批量**取多篇文章的可见评论数，返回 ``{post_id: count}``。

        为什么要有批量版：
            文章列表一次展示 20 篇，逐篇调 ``count_by_post`` 就是 20 次往返（N+1）。
            这个方法对应一条 ``GROUP BY post_id`` 的聚合查询，恒定一次往返。
            缺失的文章不会出现在字典里（而不是补 0）——
            调用方用 ``.get(id, 0)`` 读取，语义是「没有评论」而无需区分
            「查过是 0」和「没查到」。
        """


class LikeRepository(ABC):
    """点赞仓储接口。

    没有对应的实体（理由见 ``__init__.py``），所以这里的每个方法都直接用
    ``(user_id, target_type, target_id)`` 三元组说话 —— 那正是点赞的身份。

    关于**计数不冗余**这个决定，见 ``count_many`` 的说明。
    """

    # ────────────── 写入 ──────────────

    @abstractmethod
    async def like(self, user_id: UUID, *, target_type: str, target_id: UUID) -> None:
        """点赞（**幂等**）。

        重复点赞必须静默成功，而且**不能**产生第二行：
            两个并发的 toggle 请求（用户连点心形按钮是最常见的操作）会各自
            读到「还没赞」，然后都去插一行。唯一约束会拦住第二行并抛
            ``IntegrityError``——如果就这么让它冒上去，用户会看到 500，
            于是他连点两下点赞，得到的是一个错误弹窗和一个已经点上的赞。
            所以实现必须用 ``INSERT ... ON CONFLICT DO NOTHING``，
            把「并发下已经是幂等的」这件事交给数据库保证，而不是靠先查后插。
        """

    @abstractmethod
    async def unlike(self, user_id: UUID, *, target_type: str, target_id: UUID) -> None:
        """取消点赞（幂等）。

        ``DELETE`` 天然幂等：删 0 行和删 1 行都是成功。
        不需要像 ``like`` 那样特殊处理并发。
        """

    # ────────────── 单条查询 ──────────────

    @abstractmethod
    async def is_liked(self, user_id: UUID, *, target_type: str, target_id: UUID) -> bool:
        """这个用户赞过这个目标吗。命中唯一索引，是一次索引查找。"""

    @abstractmethod
    async def count(self, *, target_type: str, target_id: UUID) -> int:
        """单个目标的赞数。"""

    # ────────────── 批量查询 ──────────────

    @abstractmethod
    async def count_many(
        self,
        *,
        target_type: str,
        target_ids: Sequence[UUID],
    ) -> dict[UUID, int]:
        """批量赞数，返回 ``{target_id: count}``（缺失的键表示 0）。

        **为什么赞数/评论数是实时聚合，而不是在 posts/likes 上放冗余计数列**：
            冗余计数列要求**每一条**写入路径都记得更新它——
            点赞、取消、评论、删评论、删文章（连带清掉它的赞）……
            漏掉任何一处，计数就永久地错了：它不会自愈，也没有任何测试
            会因为「赞数少了 1」而失败，除非专门去写这一条断言。
            而错掉的计数是要给所有人看的社交证据，错了比没有更糟。
            实时聚合的代价是每次列表多一次 ``GROUP BY`` ——
            在 ``ix_likes_target`` 这种 (target_type, target_id) 索引上，
            它是一次范围扫描而不是全表扫描；换来的是「计数永远等于真实行数」
            这条不可能被违反的性质。这是一笔明显划算的交易。
        """

    @abstractmethod
    async def liked_ids(
        self,
        user_id: UUID,
        *,
        target_type: str,
        target_ids: Sequence[UUID],
    ) -> set[UUID]:
        """批量判断「当前用户赞过哪些」，返回 ``target_ids`` 的子集。

        与 ``count_many`` 分开而不是合成一个方法：
            未登录时（``user_id`` 为 None）根本不该有这次查询，
            合并成一个方法就得在实现里判空，把「有没有登录」这件事
            渗进仓储。分成两个方法之后，用例用一句
            ``if viewer_id is not None`` 表达，读起来就是它的语义。
        """


__all__ = ["CommentRepository", "LikeRepository"]
