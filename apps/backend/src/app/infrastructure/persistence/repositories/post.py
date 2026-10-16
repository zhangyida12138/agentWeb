"""``PostRepository`` 的 SQLAlchemy 实现。

三条贯穿全文件的纪律：

① **永不 commit** —— 事务边界由 ``core/database.py::get_db`` 独占。
   仓储一 commit，「一个请求一个事务」就断了，中途失败也无法整体回滚。

② **软删除在 SQL 里过滤** —— 每条查询都带 ``deleted_at IS NULL``。
   这不是「顺手加的条件」，而是不变量：漏掉一处，已删除的文章就会重新出现在
   某个列表里，而那个入口往往是最不常被测试到的那个。
   唯一的例外是 ``exists_slug``：软删除行仍然占着唯一索引，必须把它当成「已占用」。

③ **唯一约束冲突翻译成领域异常** —— 不翻译的话，application 层就得
   ``import sqlalchemy`` 才能判断「这是什么错误」，分层立刻破功。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, NoReturn

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.blog.entities import Post, PostStatus
from app.domain.blog.exceptions import (
    InvalidTagNameError,
    PostNotFoundError,
    SlugAlreadyTakenError,
)
from app.domain.blog.repositories import PostRepository
from app.domain.tag.entities import TagStatus, TagType
from app.infrastructure.persistence.mappers.post import (
    apply_to_model,
    to_entity,
    to_model,
)
from app.infrastructure.persistence.models.post import PostModel
from app.infrastructure.persistence.models.post_tag import PostTagModel
from app.infrastructure.persistence.models.tag import TagModel

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from collections.abc import Sequence

    from app.domain.blog.value_objects import Slug, TagName

# PostgreSQL SQLSTATE：唯一约束冲突（unique_violation）
PG_UNIQUE_VIOLATION = "23505"


def _sqlstate(exc: IntegrityError) -> str | None:
    """从 ``IntegrityError`` 里挖出 PG 的 SQLSTATE（与 ``repositories/user.py`` 同一套判断）。"""
    orig = exc.orig
    return getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)


def _raise_translated(exc: IntegrityError) -> NoReturn:
    """把唯一约束冲突翻译成领域异常后抛出。"""
    if _sqlstate(exc) != PG_UNIQUE_VIOLATION:
        raise exc

    constraint = (getattr(exc.orig, "constraint_name", None) or "").lower()
    if "slug" in constraint:
        raise SlugAlreadyTakenError() from exc
    # 认不出的唯一约束（例如外键指向的 author 不存在时并不会走到这里）：
    # 不猜语义，交给全局的 IntegrityError 兜底处理器
    raise exc


class SqlPostRepository(PostRepository):
    """基于 ``AsyncSession`` 的文章仓储。

    为什么标签的**关联**也在这里完成（而不是甩给 ``SqlTagRepository``）：
        ``post_tags`` 是文章聚合的一部分——它的生命周期完全由文章决定
        （文章改标签 = 整体替换关联集合），单看它没有"增删一个关联"这种独立需求。
        把它拆到 tag 仓储去，只会让「保存文章」变成跨两个仓储的两步操作，
        而这两步必须在同一个事务里成对成功。

    ⚠️ 但标签**本身**（``tags`` 表的内容：名字、描述、状态、归属）已经独立了，
       见 ``SqlTagRepository``。
       这里的 ``_resolve_tag_ids`` 只做一件事：为文章写路径**按需创建**还不存在的标签。
       它不是标签的"增删改"入口，两者不要混。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 写入 ──────────────

    async def add(self, post: Post) -> Post:
        model = to_model(post)
        self._session.add(model)
        try:
            # flush 把唯一约束冲突从 commit 阶段提前到响应之前：
            # 否则 409 会晚到「事务提交时」，那时响应已经开始写，异常只能变成 500
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)

        tag_names = await self._sync_tags(model.id, post.tags, post.author_id)
        return to_entity(model, tags=tag_names)

    async def update(self, post: Post) -> Post:
        if post.id is None:
            raise PostNotFoundError()
        model = await self._session.get(PostModel, post.id)
        if model is None:
            # 实体带着一个库里不存在的 id：多半是被并发删掉了（物理删除），按「不存在」处理
            raise PostNotFoundError()
        apply_to_model(post, model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)

        tag_names = await self._sync_tags(model.id, post.tags, post.author_id)
        # updated_at 由 Column 的 onupdate 在 UPDATE 语句里刷新，
        # 而 ORM 会在 flush 后把新值回填到 model 上（synchronize_session 的默认行为），
        # 所以这里读到的已经是库里的新时间戳，不必再查一次
        return to_entity(model, tags=tag_names)

    # ────────────── 单条查询 ──────────────

    async def get_by_id(self, post_id: uuid.UUID) -> Post | None:
        stmt = select(PostModel).where(PostModel.id == post_id, PostModel.deleted_at.is_(None))
        return await self._one_with_tags(stmt)

    async def get_by_slug(self, slug: Slug) -> Post | None:
        stmt = select(PostModel).where(PostModel.slug == slug.value, PostModel.deleted_at.is_(None))
        return await self._one_with_tags(stmt)

    async def exists_slug(self, slug: Slug, *, exclude_id: uuid.UUID | None = None) -> bool:
        # ⚠️ 这里**刻意不**过滤 deleted_at：
        #    已软删除的文章仍然占着 ``posts.slug`` 的唯一索引。
        #    如果按「不算数」处理，创建时校验会放行，随后 INSERT 撞唯一索引抛 40930——
        #    结果一样，但报错发生在更晚、更难看懂的位置（一个 flush 失败）。
        #    在唯一性这件事上，库怎么认为的就怎么判断。
        stmt = select(func.count()).select_from(PostModel).where(PostModel.slug == slug.value)
        if exclude_id is not None:
            # 「排除自己」是必须的：改文章时 slug 没变，不排除的话它永远查得到自己，
            # 于是「只改标题不动 slug」的保存会直接报 409。
            stmt = stmt.where(PostModel.id != exclude_id)
        return (await self._session.execute(stmt)).scalar_one() > 0

    # ────────────── 列表查询 ──────────────

    async def list_published(
        self,
        offset: int,
        limit: int,
        *,
        tag: TagName | None = None,
    ) -> list[Post]:
        stmt = self._published_query()
        if tag is not None:
            stmt = self._apply_tag_filter(stmt, tag)
        stmt = (
            stmt
            # published_at 理论上对已发布文章必然非空，但「理论」不足以作为排序依据：
            # 一旦有历史数据或人工改库把它留空，默认的 ASC 会把 NULL 排到最前，
            # 首页第一条就变成一篇没有发布时间的文章。nulls_last 让异常数据沉底。
            .order_by(PostModel.published_at.desc().nulls_last(), PostModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return await self._with_tags(list(models))

    async def count_published(self, *, tag: TagName | None = None) -> int:
        # ⚠️ 过滤条件与 ``list_published`` 共用 ``_published_query()``，而不是各写一遍。
        #    两处一旦漂移，前端就会看到「共 10 条」但翻到第 3 页就空了。
        stmt = self._published_query()
        if tag is not None:
            stmt = self._apply_tag_filter(stmt, tag)
        inner = stmt.with_only_columns(PostModel.id).subquery()
        return (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()

    async def list_by_author(
        self,
        author_id: uuid.UUID,
        offset: int,
        limit: int,
        *,
        status: str | None = None,
    ) -> list[Post]:
        stmt = self._author_query(author_id, status)
        # 排序键与公开列表不同（updated_at 而非 published_at），
        # 也是唯一一处两套查询不能共用 ORDER BY 的地方——见接口注释里的理由
        stmt = stmt.order_by(PostModel.updated_at.desc(), PostModel.id.desc())
        stmt = stmt.offset(offset).limit(limit)
        models = (await self._session.execute(stmt)).scalars().all()
        return await self._with_tags(list(models))

    async def count_by_author(self, author_id: uuid.UUID, *, status: str | None = None) -> int:
        inner = self._author_query(author_id, status).with_only_columns(PostModel.id).subquery()
        stmt = select(func.count()).select_from(inner)
        return (await self._session.execute(stmt)).scalar_one()

    # ────────────── 计数 ──────────────

    async def increment_view_count(self, post_id: uuid.UUID) -> int:
        """浏览量 +1 并返回自增后的值（数据库侧原子自增）。

        ⚠️ ``updated_at=PostModel.updated_at`` 这行看着多余，其实是**必须**的：
        ``TimestampMixin.updated_at`` 上声明了 ``onupdate=_utc_now``，凡是 Core 层
        ``update()`` 没有显式列出该列的语句，SQLAlchemy 都会自动补上 ``updated_at=now()``。
        而「被读了一次」不算「内容被改过」——一旦这里放开，任何一次详情页访问都会把
        ``updated_at`` 推到当前时间，文章列表按更新时间排序、以及以 ``updated_at`` 为键的
        缓存/增量同步全部失真。显式写回自身值是关掉 ``onupdate`` 的标准做法。
        """
        stmt = (
            update(PostModel)
            .where(PostModel.id == post_id)
            .values(
                view_count=PostModel.view_count + 1,
                updated_at=PostModel.updated_at,
            )
            .returning(PostModel.view_count)
        )
        return (await self._session.execute(stmt)).scalar_one()

    # ────────────── 内部：查询构造 ──────────────

    def _published_query(self) -> Select[tuple[PostModel]]:
        """公开列表的过滤条件（唯一来源，list / count 共用）。"""
        return select(PostModel).where(
            PostModel.status == PostStatus.PUBLISHED,
            PostModel.deleted_at.is_(None),
        )

    def _apply_tag_filter(
        self, stmt: Select[tuple[PostModel]], tag: TagName
    ) -> Select[tuple[PostModel]]:
        """给查询加上「必须带有某个标签」的约束。

        按 ``tags.slug`` 而不是 ``tags.name`` 过滤：
            slug 的唯一索引保证它指向恰好一个标签；
            name 虽然也唯一，但它允许空格与大小写差异，作为过滤键会受
            「用户输入 'Python' 还是 'python'」的影响。
        """
        return (
            stmt.join(PostTagModel, PostTagModel.post_id == PostModel.id)
            .join(TagModel, TagModel.id == PostTagModel.tag_id)
            # 已删除的标签不再粘在文章上：按 ``?tag=python`` 筛选时，
            # 如果这个标签已被下架，结果应该是**空**，而不是"还是能筛出来"——
            # 后者意味着删标签这件事对读者完全无效。
            .where(TagModel.slug == tag.slug, TagModel.status != TagStatus.DELETED)
        )

    def _author_query(self, author_id: uuid.UUID, status: str | None) -> Select[tuple[PostModel]]:
        stmt = select(PostModel).where(
            PostModel.author_id == author_id,
            PostModel.deleted_at.is_(None),
        )
        if status is not None:
            stmt = stmt.where(PostModel.status == status)
        return stmt

    # ────────────── 内部：读取聚合 ──────────────

    async def _one_with_tags(self, stmt: Select[tuple[PostModel]]) -> Post | None:
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        tag_map = await self._load_tags([model.id])
        return to_entity(model, tags=tag_map.get(model.id, ()))

    async def _with_tags(self, models: list[PostModel]) -> list[Post]:
        """批量补齐标签（避免 N+1）。

        先一次性把这一页所有文章的标签查出来，再按 post_id 分发——
        而不是对每篇文章各查一次（20 篇就是 21 条 SQL）。
        """
        if not models:
            return []
        tag_map = await self._load_tags([model.id for model in models])
        return [to_entity(model, tags=tag_map.get(model.id, ())) for model in models]

    async def _load_tags(self, post_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        """一次查出若干篇文章的标签名，返回 ``{post_id: [name, ...]}``。

        排序**按标签名的字典序**，而不是「作者输入的先后」：
            ``post_tags`` 里没有顺序列，因为「标签顺序」在本期不是产品需求。
            与其让顺序取决于数据库的返回顺序（不确定），不如显式规定一个确定顺序——
            否则前端每次刷新看到的标签次序都可能不一样，看起来像在闪。

        ⚠️ 过滤 ``status != deleted``：标签被删除后不该继续粘在文章上。
           注意只排除 ``deleted``、不排除 ``abnormal``：
            ``abnormal`` 的语义是「停止新的使用，但历史文章不动」，
            （见 ``domain/tag/entities.py::TagStatus``），
           所以打上它的文章仍然要看到这个标签——否则作者会以为自己丢了一个标签。
        """
        if not post_ids:
            return {}
        stmt = (
            select(PostTagModel.post_id, TagModel.name)
            .join(TagModel, TagModel.id == PostTagModel.tag_id)
            .where(
                PostTagModel.post_id.in_(post_ids),
                TagModel.status != TagStatus.DELETED,
            )
            .order_by(TagModel.name.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        result: dict[uuid.UUID, list[str]] = {}
        for post_id, name in rows:
            result.setdefault(post_id, []).append(name)
        return result

    # ────────────── 内部：写入标签关联 ──────────────

    async def _sync_tags(
        self, post_id: uuid.UUID, tags: tuple[TagName, ...], author_id: uuid.UUID
    ) -> list[str]:
        """把文章的标签关联整体对齐到 ``tags``，返回最终生效的标签名。

        「先全删再全插」而不是「算出差集再增删」：
            一篇文章最多 10 个标签，删除+插入的代价可以忽略，
            而差集算法要处理「同一次提交里既有新增又有删除」的各种组合。
            在事务里做，出错会一起回滚，不存在「删了但没插上」的中间态。

        ``author_id`` 传下只是为了「按需创建新标签」时记录归属，
        对已有标签没有影响——详见 ``_resolve_tag_ids``。
        """
        await self._session.execute(delete(PostTagModel).where(PostTagModel.post_id == post_id))
        if not tags:
            return []

        tag_ids = await self._resolve_tag_ids(tags, author_id)
        self._session.add_all([PostTagModel(post_id=post_id, tag_id=tag_id) for tag_id in tag_ids])
        await self._session.flush()
        return sorted(str(tag) for tag in tags)

    async def _resolve_tag_ids(
        self, tags: Sequence[TagName], author_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """按名字取标签 id，不存在的**按需创建**。

        并发安全靠 ``ON CONFLICT DO NOTHING`` 而不是「先查再插」：
            后者在两个人同时第一次使用同一个新标签时会双写，
            一方撞唯一索引后整个请求失败（而用户的感受是「保存标签偶尔会失败」）。
            ``ON CONFLICT DO NOTHING`` 让「另一个请求抢先插了」变成一个可吞掉的事件。

        归属的规则很直接：**谁先把标签敲进文章，标签就归谁**。
            冲突发生时（另一个请求抢先插了），``DO NOTHING`` 意味着什么都不写，
            包括 ``author_id``——于是后到的作者用了别人的标签，但没夺走它。
            这是刻意的：改归属需要的是明确的「转让」动作，
            而不是「我恰好也用了这个词」。
        """
        names = [str(tag) for tag in tags]
        id_by_name = await self._select_tag_ids(names)
        missing = [tag for tag in tags if str(tag) not in id_by_name]
        if not missing:
            return [id_by_name[name] for name in names]

        # 显式传 id 而不是依赖列的 insert_default：
        #   TagModel.id 走的是 Column 级 insert_default，而 Core 的多行 VALUES INSERT
        #   是否渲染 Python 侧默认值取决于方言/版本，显式传更稳，也不影响正确性。
        #
        # status / type 同理显式传——它们在 TagModel 上**没有**构造器默认值，
        #   就是为了强制每一个写入方说出「这个标签什么状态、给谁用」。
        #   ⚠️ 写路径建出来的标签**永远是 user 类型**：
        #      在编辑器里敲一个新标签，不应该是「创建一个平台内置标签」的快捷方式。
        #      system 只能通过标签管理接口由管理员显式创建。
        #      否则作者只要在文章里打上「首页推荐」，就能造出一个管理员才该拥有的东西。
        await self._session.execute(
            pg_insert(TagModel)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "name": str(tag),
                        "slug": tag.slug,
                        "status": TagStatus.NORMAL,
                        "type": TagType.USER,
                        "author_id": author_id,
                    }
                    for tag in missing
                ]
            )
            .on_conflict_do_nothing()
        )
        id_by_name = await self._select_tag_ids(names)

        # 仍然查不到的，只可能是 slug 唯一索引被别人占了：
        #   slug 由 name 确定性派生，所以「不同名字派生出同一 slug」才会走到这里
        #   （例如 ``Node.js`` 与 ``Node js`` 都归化成 ``node-js``）。
        #   这时**明确报错**而不是静默丢弃——静默丢弃会让用户以为标签存上了。
        unfound = [name for name in names if name not in id_by_name]
        if unfound:
            raise InvalidTagNameError(f"标签名与已有标签冲突，请换一个：{'、'.join(unfound)}")
        return [id_by_name[name] for name in names]

    async def _select_tag_ids(self, names: Sequence[str]) -> dict[str, uuid.UUID]:
        """按名字批量查标签 id。"""
        if not names:
            return {}
        stmt = select(TagModel.name, TagModel.id).where(TagModel.name.in_(names))
        rows = (await self._session.execute(stmt)).all()
        return dict(rows)


__all__ = ["PG_UNIQUE_VIOLATION", "SqlPostRepository"]
