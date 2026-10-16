"""标签上下文的仓储实现：``SqlTagRepository``。

与 ``SqlPostRepository`` / ``SqlUserRepository`` 的关系：
    「同一个上下文内互相引用」是允许的，但这里是**跨上下文读取**——
    统计 ``post_count`` 要 JOIN ``posts`` / ``post_tags``，而这两张表属于 blog。
    这在 DDD 里叫「读模型穿透」：写路径必须走各自的聚合根（文章归 blog、标签归 tag），
    但**统计类查询**绕不过去——除非为它单独建一张汇总表（那就是另一件事了）。
    所以这里显式 import blog 的模型，而不是假装两个上下文毫无关系。

    ⚠️ 方向是 tag → blog，不能反过来。``repositories/post.py`` 会 import
       ``TagModel``（写路径按需创建标签），如果这里也去 import blog 的**仓储**，
       两个模块就会互相 import。所以这里只碰 blog 的**模型**，不碰它的仓储——
       模型是数据结构，仓储才是行为；数据的依赖不会形成环，行为的依赖会。
"""

from __future__ import annotations

import uuid
from typing import NoReturn

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.blog.entities import PostStatus
from app.domain.tag.entities import Tag
from app.domain.tag.exceptions import TagAlreadyExistsError, TagNotFoundError
from app.domain.tag.repositories import TagRepository
from app.infrastructure.persistence.mappers.tag import (
    apply_to_model,
    to_entity,
    to_model,
)
from app.infrastructure.persistence.models.post import PostModel
from app.infrastructure.persistence.models.post_tag import PostTagModel
from app.infrastructure.persistence.models.tag import TagModel

# PostgreSQL SQLSTATE
PG_UNIQUE_VIOLATION = "23505"

# LIKE 的转义字符。选反斜杠是因为它同时也是 PostgreSQL ``LIKE ... ESCAPE`` 的默认值，
# 显式传一遍只是让「我们依赖这个默认」这件事在代码里可见。
_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    """转义 LIKE 模式里的元字符。

    ``%`` 与 ``_`` 在 LIKE 里是通配符。用户搜「a_b」时如果不转义，
        ``_`` 会匹配任意一个字符，于是 ``axb`` / ``a1b`` 全都被返回——
        搜索结果"看起来有结果"，但都是错的，这种 bug 极难被用户描述清楚。

    反斜杠必须**先**替换，否则后面插入的转义符会被二次转义。
    这是转义函数最常见的顺序错误，不是风格问题。
    """
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _sqlstate(exc: IntegrityError) -> str | None:
    """从 ``IntegrityError`` 里挖出 PG 的 SQLSTATE。

    这是本仓库里**第三份**完全相同的实现（``repositories/user.py``、
    ``repositories/post.py`` 各一份）。照着现有约定复制，而不是当场抽公共模块：
        抽象是在第二次重复时被看见、第三次重复时才有足够信息做对的。
        现在做等于凭猜测定义一个只有三个调用点的"通用"工具函数，
        而抽出去的那次重构应该单独做、单独验证，不该混在新增标签功能里。
        遗留问题记在这里，不藏。
    """
    orig = exc.orig
    return getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)


def _raise_translated(exc: IntegrityError) -> NoReturn:
    """把唯一约束冲突翻译成领域异常后抛出。

    约束名去 ``constraint_name`` 里找，是因为
    ``Base.metadata`` 的命名约定把唯一索引统一叫 ``ix_tags_name`` / ``ix_tags_slug``
    （见 ``base.py::NAMING_CONVENTION``）。**靠名字里的子串判断**看起来粗糙，
    但这是这一层唯一拿得到的信息：PG 的 unique_violation 不告诉你是哪一列冲突，
    只给约束名。真要精确，只能再查一次库，而那时事务已经脏了。
    """
    if _sqlstate(exc) != PG_UNIQUE_VIOLATION:
        # 认不出的完整性错误（例如外键指向的 author 不存在，那是 23503）：
        # 不猜语义，交给全局的 IntegrityError 兜底处理器变成 500。
        # 猜错的代价远大于 500：把一个"我们代码有 bug"伪装成"你的输入有问题"，
        # 会让用户反复改一个本来就没错的输入。
        raise exc

    constraint = (getattr(exc.orig, "constraint_name", None) or "").lower()
    if "slug" in constraint:
        raise TagAlreadyExistsError("这个标签名归化后的网址（slug）已被占用，请换一个") from exc
    if "name" in constraint:
        raise TagAlreadyExistsError("这个标签名已经被使用了") from exc
    raise exc


class SqlTagRepository(TagRepository):
    """基于 ``AsyncSession`` 的标签仓储。

    命名是 ``Sql`` 而不是 ``SQLAlchemy``：全项目的实现类都是
    ``SqlUserRepository`` / ``SqlPostRepository`` / ``SqlCommentRepository``，
    一个例外会让每一个 import 它的人停下来想「这个是不是另一套东西」。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写入 ──────────────

    async def add(self, tag: Tag) -> Tag:
        model = to_model(tag)
        self._session.add(model)
        try:
            # flush 把唯一约束冲突从 commit 阶段提前到响应之前：
            # 否则 409 会晚到「事务提交时」，那时响应已经开始往外写，异常只能变成 500。
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)

        # 不查 post_count：刚建出来的标签不可能已经被任何文章引用，
        # 一定是 0。为它多发一条 COUNT 是纯粹的无用功。
        return to_entity(model)

    async def update(self, tag: Tag) -> Tag:
        model = await self._session.get(TagModel, tag.id)
        if model is None:
            # 实体带着一个库里不存在的 id：多半是被并发物理删除（或恢复过备份）。
            # 注意这里**不**用 ``get_by_id``——那是"读路径"，会多查一次 post_count，
            # 而我们现在只需要一个能改的模型对象。
            raise TagNotFoundError()

        apply_to_model(tag, model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)

        # 这里**要**查 post_count：改标签的响应会回给前端，
        # 里面显示 ``post_count: 0`` 就是在说「这个标签没人用」——而它可能挂着 50 篇文章。
        # 一个能被用户看见的错误数字，比一条多余的 SQL 贵得多。
        #
        # 另外 ``updated_at`` 由 Column 的 onupdate 在 UPDATE 语句里刷新，
        # ORM 会在 flush 后把新值回填到 model 上，所以上面读到的已是库里的新值，不必再查。
        return to_entity(model, post_count=await self._count_posts(tag.id))

    # ────────────── 查询 ──────────────

    async def get_by_id(self, tag_id: uuid.UUID) -> Tag | None:
        """按 id 取标签。

        **不过滤 status**（连 deleted 也查得到）：写路径必须能拿到已删除的标签，
        否则「把删掉的标签恢复回来」从物理上就不可能实现。
        「已删除 == 不存在」是读路径的对外承诺，由用例在拿到实体后判断。

        ``post_count`` 恒为 0：
            这个方法只服务于**写路径**（归属校验 + 取出来改），
            那个 0 不会被任何人看见，为它多发一条 COUNT 是浪费。
            需要真实用量的地方只有 ``list_tags``，那里用一次 GROUP BY 算完整页。
        """
        model = await self._session.get(TagModel, tag_id)
        if model is None:
            return None
        return to_entity(model)

    async def exists_name(self, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        # ⚠️ 刻意**不**过滤 status：
        #    已软删除的标签仍然占着 ``ix_tags_name`` 这个唯一索引。
        #    如果按「不算数」处理，创建时校验会放行，随后 INSERT 撞唯一索引抛 40950——
        #    结果一样，但报错发生在更晚、更难懂的位置（一个 flush 失败）。
        #    在唯一性这件事上，库怎么认为的就怎么判断。
        return await self._exists(TagModel.name == name, exclude_id=exclude_id)

    async def exists_slug(self, slug: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        # 同 exists_name：slug 的唯一索引也不区分 status。
        return await self._exists(TagModel.slug == slug, exclude_id=exclude_id)

    async def list_tags(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        keyword: str | None = None,
        author_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Tag]:
        """分页查标签，带 ``post_count``。"""
        # 聚合表达式只构造一次，再借用它的 label 去排序。
        #   写成 ``func.count(PostModel.id).desc()`` 效果一样（PostgreSQL 允许
        #   ORDER BY 里出现不在 select 列表中的聚合），但那样同一个聚合在两次
        #   构造里长得一模一样、实际是两个独立对象，读代码的人得逐字比对才能确认
        #   它们确实是同一个东西。复用 ``post_count`` 把这份确认变免费。
        post_count = func.count(PostModel.id).label("post_count")
        stmt = (
            self._filtered_query(status=status, type=type, keyword=keyword, author_id=author_id)
            # add_columns 而不是改 select(TagModel, ...)——它让"查哪些列"这件事
            # 只在 _filtered_query 里决定一次，而聚合在这里追加。
            .add_columns(post_count)
            # ⚠️ 两个 outerjoin 而不是 join：
            #   一个标签可能 0 篇文章引用（作者删掉了唯一那篇），
            #   用 inner join 会让这类标签从列表里**消失**——
            #   而"没人用的标签"恰恰是标签管理页最想知道的信息。
            .outerjoin(PostTagModel, PostTagModel.tag_id == TagModel.id)
            .outerjoin(
                PostModel,
                and_(
                    PostModel.id == PostTagModel.post_id,
                    # 统计口径写进 ON 而不是 WHERE：写成 WHERE 会把外连接退化成内连接，
                    # 于是「只挂着草稿的标签」又消失了。这是 SQL 里最经典的一个坑，
                    # 条件写在 ON 里是"连接时就只要这些"，写在 WHERE 里是"连完再筛掉行"。
                    PostModel.status == PostStatus.PUBLISHED,
                    PostModel.deleted_at.is_(None),
                ),
            )
            # 按主键分组：PostgreSQL 认可「主键确定后其余列函数依赖它」，
            # 所以可以直接 select 整个 TagModel 而不必逐列写进 GROUP BY。
            .group_by(TagModel.id)
            # 「用得多」在前、「同名」其次。标签列表的第一屏应该是真正被用起来的标签，
            # 而不是按拼音排在前面的那几个。加 name 作次级键是为了让
            # post_count 相同的标签有一个**稳定**顺序——否则翻页时它们会互相换位，
            # 出现「第 1 页第 5 个和第 2 页第 3 个是同一个标签」。
            .order_by(post_count.desc(), TagModel.name.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [to_entity(model, post_count=count) for model, count in rows]

    async def count_tags(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        keyword: str | None = None,
        author_id: uuid.UUID | None = None,
    ) -> int:
        """按同样条件统计总数。

        ⚠️ **不能**复用 ``list_tags`` 的那条语句：它带 GROUP BY 与两个 outerjoin，
            ``count(*)`` 会数出「(标签 × 文章) 的行数」而不是标签数，
            于是一个 3 篇文章的标签被数成 3。
            筛选条件共用 ``_filtered_query``，聚合部分各算各的，才是正确的切分。
        """
        inner = (
            self._filtered_query(status=status, type=type, keyword=keyword, author_id=author_id)
            .with_only_columns(TagModel.id)
            .subquery()
        )
        return (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()

    # ────────────── 内部：条件与计数 ──────────────

    def _filtered_query(
        self,
        *,
        status: str | None,
        type: str | None,
        keyword: str | None,
        author_id: uuid.UUID | None,
    ) -> Select[tuple[TagModel]]:
        """筛选条件的**唯一来源**（list 与 count 共用）。

        两处各写一遍的后果不是"重复"，而是**漂移**：
            某天给 list 加了一个条件忘了给 count 加，前端就会看到
            「共 10 条」但翻到第 2 页是空白——而且两处代码看起来都完全正常。
            分页类 bug 基本都是这么来的。
        """
        stmt = select(TagModel)
        if status is not None:
            stmt = stmt.where(TagModel.status == status)
        if type is not None:
            stmt = stmt.where(TagModel.type == type)
        if author_id is not None:
            stmt = stmt.where(TagModel.author_id == author_id)
        if keyword is not None:
            normalized = keyword.strip()
            # 只有空白字符的 keyword 当作"没传"，而不是当作"匹配空字符串"：
            # 后者会返回 0 条，用户会以为标签表是空的。
            if normalized:
                # ilike 而不是 like：标签名允许大小写（``Python`` / ``python``），
                # 用 like 会让搜「python」的人找不到「Python」，看起来像没这个标签。
                stmt = stmt.where(
                    TagModel.name.ilike(f"%{_escape_like(normalized)}%", escape=_LIKE_ESCAPE)
                )
        return stmt

    async def _exists(
        self, condition: ColumnElement[bool], *, exclude_id: uuid.UUID | None
    ) -> bool:
        """``SELECT count(*) ... WHERE <condition> [AND id != exclude_id] > 0``。

        收一个**已经构造好的条件表达式**而不是「列 + 值」两个参数：
            后者要给 ``column`` 标注类型，而 SQLAlchemy 的列对象在类型系统里
            是个复杂泛型；用 ``Any`` 糊过去，就等于把「传错列」这件事
            从类型检查期推到了运行时。传表达式则天然类型良好。
        """
        stmt = select(func.count()).select_from(TagModel).where(condition)
        if exclude_id is not None:
            # 「排除自己」是必须的：改标签时名字没变，不排除的话它永远查得到自己，
            # 于是「只改描述不动名字」的保存会直接报 40950——一个谁也看不懂的错误。
            stmt = stmt.where(TagModel.id != exclude_id)
        return (await self._session.execute(stmt)).scalar_one() > 0

    async def _count_posts(self, tag_id: uuid.UUID) -> int:
        """统计一个标签下**已发布且未删除**的文章数。

        口径必须与 ``list_tags`` 的聚合完全一致，否则同一张页面上的
        「标签列表显示 3」和「点进去只看到 1 篇」会同时成立。
        两处都靠 ``PostStatus.PUBLISHED`` + ``deleted_at IS NULL`` 这两个条件，
        写法上重复，但这次**不适合抽公共函数**：
        一处是 JOIN 里的 ON 条件、一处是独立的 WHERE 条件，
        抽公共的代价是引入一个"能同时生成 ON 和 WHERE 片段"的小框架——
        为两个调用点造抽象，不划算。保持一致靠的是同一条注释，不是同一段代码。
        """
        stmt = (
            select(func.count())
            .select_from(PostTagModel)
            .join(PostModel, PostModel.id == PostTagModel.post_id)
            .where(
                PostTagModel.tag_id == tag_id,
                PostModel.status == PostStatus.PUBLISHED,
                PostModel.deleted_at.is_(None),
            )
        )
        return (await self._session.execute(stmt)).scalar_one()


__all__ = ["PG_UNIQUE_VIOLATION", "SqlTagRepository"]
