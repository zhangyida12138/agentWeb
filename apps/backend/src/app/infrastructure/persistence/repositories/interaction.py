"""``CommentRepository`` / ``LikeRepository`` 的 SQLAlchemy 实现。

与 ``repositories/post.py`` 同一套纪律：

① **永不 commit** —— 事务边界由 ``core/database.py::get_db`` 独占；
② **可见性在 SQL 里判** —— 评论的「可见」比文章复杂一点（多了一条
   「已删除但子树里还有活着的评论」的墓碑规则）。树的深度不限，
   于是「子树里还有没有活着的评论」只能靠递归 CTE 回答（见 ``_visible_root_cte``），
   而计数与列表**共用同一个 CTE**：
   分页的总数与数据必须来自同一套条件，否则就会「共 10 条但翻两页就空了」；
③ **批量查询** —— 列表页用到的计数一律提供 ``*_many`` 版本，
   恒定一两次往返，与页大小无关。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CTE, ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.interaction.exceptions import CommentNotFoundError
from app.domain.interaction.repositories import CommentRepository, LikeRepository
from app.infrastructure.persistence.mappers.comment import (
    apply_to_model,
    to_entity,
    to_model,
)
from app.infrastructure.persistence.models.comment import CommentModel
from app.infrastructure.persistence.models.like import LikeModel

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from collections.abc import Sequence

    from app.domain.interaction.entities import Comment


def _visible_root_cte(post_id: uuid.UUID) -> CTE:
    """递归找出「所有可见评论各自的根评论」，作为可见性判据的数据源。

    先想清楚要判什么。树**深度不限**，一条已删除的根评论该不该留在界面上，
    判据不是「它自己删没删」，而是「它还有没有存在的理由」——
    即**它的子树里还有没有未删除的评论**（哪怕隔了十层）。
    有，它是别人回复的落点，必须留下，否则读者看到一串没有上文的句子；
    没有，它就是纯墓碑，显示出来只是噪音。

    为什么不能沿用「有没有直接子行」这个便宜判据：
        一条根被删、它下面被回复的那条也被删、而再下面还有一条活着。
        这时「直接子行」确实存在（那条被删的回复），看起来判对了；
        但把「直接子行」写成 ``deleted_at IS NULL`` 的可见子行就会判错——
        根会被丢掉，它那条**还活着**的后代跟着一起从界面上消失。
        深度一旦超过两层，这两种写法的差别就会真的暴露出来。

    于是用一条递归 CTE 把「可见评论 → 一路向上走到它的根」走出来：

        锚：**可见且没有可见子评论**的评论（即每一条可见「叶」），
            带着当前结点 ``node_id`` 和前进游标 ``cursor = 自己的 parent_id``；
        递归：把游标往上挪一层（``node_id = 父的 id``、``cursor = 父的 parent_id``）；
        收口：``cursor IS NULL`` 的那些行，``node_id`` 就是根评论 id。

    ★ ``node_id`` 必须**随每一层一起往上走**，而不是只用锚里的 ``comment_id``：
      两列都在动，才表达得出「我从哪来、我现在在哪」。
      只把出发点带上去、最后取出发点的 id，得到的是**叶自己的 id**
      （它在结果里满足 ``cursor IS NULL``，只是因为它被走到了根——很容易看漏），
      于是「可见根评论」会变成「可见叶评论」，分页数跟着全错。
      这种错很难靠读代码发现，因为形状完全合法、改名也改得通：
      真实数据里一旦出现「回复的回复」，根就会被算重、算漏。

    为什么锚只取「可见叶」而不是全部可见评论：
        每条可见叶向上走到的根，正好就是「子树里有可见评论」的那些根
        （子树里有可见评论 ⟹ 取其中最深的那个，它没有可见子评论）。
        反之每个这样的根都至少被一条可见叶走到。
        两者是同一个集合，但只从叶出发，CTE 的行数是
        「可见叶数 × 平均深度」，而不是「全部可见评论数 × 平均深度」——
        一篇文章几百条评论、每条都从自己开始往上走，会白走一大批重复的路。

    为什么**不**把它写成相关子查询（``EXISTS`` 里放递归 CTE）：
        相关子查询要 PostgreSQL 允许 CTE 引用外层表的列。CTE 不是
        ``LATERAL``，这条路走不通。所以取另一头：
        用 ``IN (子查询)`` 只算一次，结果集是「这一页要用到的根 id」，
        规模是根评论数而不是全部评论数。

    为什么 ``UNION ALL`` 而不是 ``UNION``：
        ``UNION`` 会在环上停下来（重复行被消掉），等于免费得到一次环检测。
        但 ``parent_id`` 上出现环只能靠人工改库造出来（见 ``Comment`` 的说明），
        而 ``UNION`` 的每一次迭代都要去重，是**每次正常读取**都要付的成本。
        不为只可能由人工弄坏的状态付这笔钱，所以用 ``UNION ALL``，
        把这个前提写在文档里。

    ``post_id`` 用参数传入而不是从外层相关：
        同理（CTE 不能引用外层列）。语句本身也已经按同一篇文章过滤，
        两边是同一个值。
    """
    # 锚：可见、且底下没有可见子评论的评论（每条可见「叶」）
    visible_child = aliased(CommentModel)
    no_visible_child = ~(
        select(1)
        .where(
            visible_child.parent_id == CommentModel.id,
            visible_child.deleted_at.is_(None),
        )
        # 显式 correlate：否则 comments 会被再 JOIN 进子查询一次，
        # 那个 EXISTS 就恒为真（「没有可见子评论」永远不成立，CTE 退化成空）
        .correlate(CommentModel)
        .exists()
    )
    anchor = select(
        CommentModel.id.label("node_id"),
        CommentModel.parent_id.label("cursor"),
    ).where(
        CommentModel.post_id == post_id,
        CommentModel.deleted_at.is_(None),
        no_visible_child,
    )

    ancestors = anchor.cte("visible_ancestors", recursive=True)
    parent = aliased(CommentModel)
    upward = select(parent.id.label("node_id"), parent.parent_id.label("cursor")).where(
        parent.id == ancestors.c.cursor
    )
    return ancestors.union_all(upward)


def _visible_root_criteria(post_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    """「可见根评论」的过滤条件（``count_threads`` 与 ``list_thread_roots`` 共用）。

    两条规则：

    ① ``parent_id IS NULL`` —— 只取根评论。分页的单位是「一段对话」，
       把回复也算进分页单位会让一页里混进半截对话。
    ② 它的 id 出现在 ``_visible_root_cte`` 的结果里 ——
       即「它自己没被删」或「它的子树里还有活着的评论」。

    写成一条子查询而不是 Python 过滤：
       后者要先取出全部根评论（可能上千条）才能算出一页，分页就失效了。

    ★ 计数与列表**必须**用同一套条件，所以这里返回的元组是两个方法的唯一来源。
    上一次改动之所以只动一处就能保证一致，靠的就是这条纪律。
    """
    ancestors = _visible_root_cte(post_id)
    return (
        CommentModel.parent_id.is_(None),
        CommentModel.id.in_(select(ancestors.c.node_id).where(ancestors.c.cursor.is_(None))),
    )


class SqlCommentRepository(CommentRepository):
    """基于 ``AsyncSession`` 的评论仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写入 ──────────────

    async def add(self, comment: Comment) -> Comment:
        model = to_model(comment)
        self._session.add(model)
        # flush 而不是 commit：把 INSERT 发出去（从而让外键、长度、非空约束
        # 在这里就报错），但事务的归属权仍然在 ``get_db``。
        # 顺带这也是让 ``created_at`` / ``updated_at`` 被回填的时机。
        await self._session.flush()
        return to_entity(model)

    async def update(self, comment: Comment) -> Comment:
        if comment.id is None:
            raise CommentNotFoundError()
        model = await self._session.get(CommentModel, comment.id)
        if model is None:
            # 实体带着一个库里不存在的 id：按「不存在」处理，
            # 而不是让 UPDATE 静默影响 0 行后返回一个看起来成功的响应
            raise CommentNotFoundError()
        apply_to_model(comment, model)
        await self._session.flush()
        return to_entity(model)

    # ────────────── 单条查询 ──────────────

    async def get_by_id(self, comment_id: uuid.UUID) -> Comment | None:
        """按 id 取评论，**含已删除的**。

        ``session.get`` 直接走主键，是最便宜的读法；
        也正因为是「按主键取一条」而不是「查列表」，这里才敢不过滤
        ``deleted_at``——它是删除流程自己的一环，过滤掉会让重复删除变成 404。
        可见性由调用方（用例）判。
        """
        model = await self._session.get(CommentModel, comment_id)
        return None if model is None else to_entity(model)

    # ────────────── 评论树（任意深度） ──────────────

    async def count_threads(self, post_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(CommentModel)
            .where(
                CommentModel.post_id == post_id,
                *_visible_root_criteria(post_id),
            )
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def list_thread_roots(
        self,
        post_id: uuid.UUID,
        offset: int,
        limit: int,
    ) -> list[Comment]:
        stmt = (
            select(CommentModel)
            # ★ 与 count_threads 同一套条件，一字不差（都来自 _visible_root_criteria）
            .where(CommentModel.post_id == post_id, *_visible_root_criteria(post_id))
            # 创建时间正序（对话按阅读顺序展开），见接口注释里的理由。
            # id 作为第二排序键**不是装饰**：created_at 有可能相同
            # （批量导入、或者同一毫秒内的两次写入），
            # 而没有全序的排序在 OFFSET 分页下会重复或漏掉行——
            # 第二页出现第一页看过的那条，就是这里少写了一个键。
            .order_by(CommentModel.created_at.asc(), CommentModel.id.asc())
            .offset(offset)
            .limit(limit)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [to_entity(model) for model in models]

    async def list_descendants(self, root_ids: Sequence[uuid.UUID]) -> list[Comment]:
        """一条递归 CTE 取出这些根评论下的**全部后代**（任意深度）。

        上一版是 ``parent_id IN (root_ids)``——只取一层。
        那在「树恒为两层」时是对的，改成无限深度之后就会静默丢数据：
        第三层往后的评论根本不在结果里，前端的树上什么都不显示，
        而接口返回 200，没有任何迹象表明少了一截。

        写法与 ``_visible_root_cte`` 同构，只是方向相反：
            锚：``parent_id IN (root_ids)``（一层，走 ``ix_comments_reply_fetch``）；
            递归：把 ``parent_id`` 挂到上一层的结果上，一路向下。

        ``aliased(CommentModel, subtree)`` 是关键的一步：
        递归 CTE 默认只能选出 ``Row``，而整个持久化层（``to_entity``）
        都建立在「拿到的是 ``CommentModel`` 实例」这个前提上。
        把 CTE 当可映射的 selectable 再 alias 一次，就既走完了递归、
        又拿回了 ORM 实体——不必为这一处特例写一个平行的映射函数。

        排序在 SQL 里给定（``created_at`` 正序 + id 兜底）：
            拼树时子评论的相对顺序直接沿用这个顺序，
            而 PostgreSQL 不保证没有 ``ORDER BY`` 时的返回顺序，
            换个执行计划（或换个索引）就可能变。
        """
        if not root_ids:
            # ``IN ()`` 在某些驱动下是语法错误，而「这一页没有根评论」
            # 或「根评论都还没人回」都是极常见的正常情况，必须提前返回
            return []
        anchor = select(CommentModel).where(CommentModel.parent_id.in_(root_ids))
        subtree = anchor.cte("comment_subtree", recursive=True)
        child = aliased(CommentModel)
        downward = select(child).where(child.parent_id == subtree.c.id)
        subtree = subtree.union_all(downward)

        entity = aliased(CommentModel, subtree)
        stmt = select(entity).order_by(subtree.c.created_at.asc(), subtree.c.id.asc())
        models = (await self._session.execute(stmt)).scalars().all()
        return [to_entity(model) for model in models]

    # ────────────── 计数（用于文章列表 / 详情） ──────────────

    async def count_by_post(self, post_id: uuid.UUID) -> int:
        return (await self._count_by_posts([post_id])).get(post_id, 0)

    async def count_by_posts(self, post_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        return await self._count_by_posts(post_ids)

    # ────────────── 内部 ──────────────

    async def _count_by_posts(self, post_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """一条 ``GROUP BY post_id`` 查出多篇文章的可见评论数。

        只算未删除的：文章卡片上的「N 条评论」是给读者看的热度，
        把墓碑算进去等于告诉读者「这里有 3 条讨论」而点开只有一句
        「该评论已删除」。

        **不补 0**（缺失的 key 就是 0 条）：
            补 0 需要在 SQL 里 LEFT JOIN 一遍文章表，只为了让字典里多几个
            值为 0 的键；而调用方用 ``.get(post_id, 0)`` 一行就表达了同一件事。
            顺带还保住了「零评论的文章根本不出现在聚合结果里」这个更省的形状。
        """
        if not post_ids:
            return {}
        stmt = (
            select(CommentModel.post_id, func.count().label("visible_count"))
            .where(
                CommentModel.post_id.in_(post_ids),
                CommentModel.deleted_at.is_(None),
            )
            .group_by(CommentModel.post_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {post_id: int(count) for post_id, count in rows}


class SqlLikeRepository(LikeRepository):
    """基于 ``AsyncSession`` 的点赞仓储。

    没有任何一处 ``commit``，也没有一处「先查后写」——
    唯一约束 + ON CONFLICT 已经表达了「每人每目标最多一行」，
    再叠一层应用层判断只会造出「检查与写入之间」的竞态窗口。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写入 ──────────────

    async def like(self, user_id: uuid.UUID, *, target_type: str, target_id: uuid.UUID) -> None:
        """点赞，**幂等**。

        ``ON CONFLICT DO NOTHING`` 是这里唯一正确的写法：

        · 不用它 → 并发双击的第二条 INSERT 撞唯一约束，抛 ``IntegrityError``，
          最终是一个 500。用户看到「操作失败」，但实际上赞已经点上了——
          界面和事实不一致，是最难被报告也最难复现的那类 bug。
        · 不用它、改成「先 ``is_liked`` 再插」→ 两个请求可能都读到 False，
          然后各插一行（其中一行会被约束拦住，于是又回到 500），
          或者更糟：如果约束被谁去掉了，就真的写出两行。
          「先查后写」在这里不是解决方案，它就是问题本身。

        ``index_elements`` 用列名而不是约束名 ``uq_likes_user_target``：
            约束名是一个字符串常量，改个名字（或换个库）它就悄悄失配，
            而这行代码不会报错——只会退化成「不再幂等」。
            列名是 schema 本身的一部分，改不掉。

        ``id`` / ``created_at`` 不显式传：它们有 Column 级 ``insert_default``，
        Core INSERT 会自动填充。这里**不**走 ``to_model`` 那条路，
        因为点赞没有领域实体——它是纯粹的行为记录。
        """
        stmt = (
            pg_insert(LikeModel)
            .values(
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "target_type", "target_id"])
        )
        await self._session.execute(stmt)

    async def unlike(self, user_id: uuid.UUID, *, target_type: str, target_id: uuid.UUID) -> None:
        """取消点赞。``DELETE`` 影响 0 行或 1 行都是成功，天然幂等。"""
        await self._session.execute(
            delete(LikeModel).where(
                LikeModel.user_id == user_id,
                LikeModel.target_type == target_type,
                LikeModel.target_id == target_id,
            )
        )

    # ────────────── 单条查询 ──────────────

    async def is_liked(self, user_id: uuid.UUID, *, target_type: str, target_id: uuid.UUID) -> bool:
        # 用 ``LIMIT 1`` + first() 而不是 COUNT(*)：
        # 唯一约束保证最多一行，但我们不需要知道有几行，只需要知道有没有。
        # COUNT 要走完整个索引区间，LIMIT 1 命中一条就返回。
        stmt = (
            select(LikeModel.id)
            .where(
                LikeModel.user_id == user_id,
                LikeModel.target_type == target_type,
                LikeModel.target_id == target_id,
            )
            .limit(1)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def count(self, *, target_type: str, target_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(LikeModel)
            .where(
                LikeModel.target_type == target_type,
                LikeModel.target_id == target_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one()

    # ────────────── 批量查询 ──────────────

    async def count_many(
        self,
        *,
        target_type: str,
        target_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        if not target_ids:
            return {}
        # (target_type, target_id) 复合索引让这条 GROUP BY 变成
        # 「按目标定点取一段连续区间」而不是全表扫描，
        # 代价与目标数量成正比，与点赞总量无关。
        stmt = (
            select(LikeModel.target_id, func.count().label("like_count"))
            .where(
                LikeModel.target_type == target_type,
                LikeModel.target_id.in_(target_ids),
            )
            .group_by(LikeModel.target_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {target_id: int(count) for target_id, count in rows}

    async def liked_ids(
        self,
        user_id: uuid.UUID,
        *,
        target_type: str,
        target_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not target_ids:
            return set()
        stmt = select(LikeModel.target_id).where(
            LikeModel.user_id == user_id,
            LikeModel.target_type == target_type,
            LikeModel.target_id.in_(target_ids),
        )
        # ``scalars().all()`` 而不是 ``scalar_one()``：这里期望的是**多行**
        return set((await self._session.execute(stmt)).scalars().all())


__all__ = ["SqlCommentRepository", "SqlLikeRepository"]
