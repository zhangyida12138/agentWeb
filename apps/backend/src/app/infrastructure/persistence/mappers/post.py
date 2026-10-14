"""博客上下文：领域实体 ↔ ORM 模型的显式翻译。

为什么不让 ``PostModel`` 自带 ``to_entity()``：
    那会让「表结构」和「领域规则」缠在一起——模型每加一个字段都要顺手改翻译逻辑，
    而且翻译一旦出错会污染整个持久化层。集中在这个模块，翻译规则一眼可见，也能单测。

为什么不把 ``tags`` 做成 ``relationship()``：
    标签要通过 ``(name, slug)`` 两个唯一键去 upsert，而且更新时的语义是
    「整体替换关联集合」。用 relationship 表达会让「一次 SQL 同步完成」
    变成「ORM 逐条 diff 再各自发出语句」，在异步会话下既慢又容易踩懒加载的坑。
    这里选择显式传参、由仓储负责同步。
"""

from __future__ import annotations

from collections.abc import Collection

from app.domain.blog.entities import Post
from app.domain.blog.value_objects import PostContent, PostTitle, Slug, TagName
from app.infrastructure.persistence.models.post import PostModel

_NO_ID_MESSAGE = "持久化前实体必须已有 id（Post.create 会生成），否则无法保证写入幂等"


def to_model(entity: Post) -> PostModel:
    """实体 → 模型（仅用于**新建**）。

    id 取实体自己生成的标识——标识由领域决定，ORM 不再自作主张。
    created_at / updated_at 故意不传：它们由 Column 级的 insert_default 在 INSERT 时填充，
    这里传值反而会覆盖掉统一的取值口径。
    """
    if entity.id is None:
        raise ValueError(_NO_ID_MESSAGE)
    return PostModel(
        id=entity.id,
        author_id=entity.author_id,
        title=entity.title.value,
        slug=entity.slug.value,
        content=entity.content.value,
        summary=entity.summary,
        cover_url=entity.cover_url,
        status=entity.status,
        published_at=entity.published_at,
        view_count=entity.view_count,
        # deleted_at 不传：软删除是显式动作（SoftDeleteMixin 的 Column 默认 None），
        # 新建时它必然为空。要传反而要在这里写一句 `deleted_at=entity.deleted_at`，
        # 那就等于允许「带删除标记的新建」——这种状态没有意义。
    )


def apply_to_model(entity: Post, model: PostModel) -> None:
    """把实体的可变字段刷到**已存在**的模型上（用于更新）。

    不碰 id / created_at / updated_at：
        id 是身份标识，后两个是审计信息，都不在领域实体能改动的范围内。
        updated_at 由 Column 的 onupdate 在 UPDATE 语句里自动刷新，
        而实体自己的 ``_touch()`` 负责让「内存里的对象」也有正确时间戳——
        两者不冲突：内存值用于即时响应，库值用于审计。

    ``view_count`` 故意**不在**这里：
        它由仓储用 ``SET view_count = view_count + 1`` 原子自增。
        如果每次 update 都把实体里的值写回去，一个「编辑文章」的请求
        就会把并发期间累积的浏览量覆盖掉（典型的丢失更新）。
        实体里的 ``view_count`` 只读不写回。
    """
    model.author_id = entity.author_id
    model.title = entity.title.value
    model.slug = entity.slug.value
    model.content = entity.content.value
    model.summary = entity.summary
    model.cover_url = entity.cover_url
    model.status = entity.status
    model.published_at = entity.published_at
    model.deleted_at = entity.deleted_at


def to_entity(model: PostModel, *, tags: Collection[str] = ()) -> Post:
    """模型 → 实体。

    逐个字段显式搬运，不用 ``**kwargs`` 透传：
    显式列出才能让「模型加了字段但忘了翻译」在 code review 里一眼看出来。

    ``tags`` 由调用方（仓储）单独查出来传进来，而不是在这个函数里查库：
        翻译函数必须是**纯函数**——它要能被单测直接用两个对象调起来。
        一旦它开始访问数据库，「测一个字段映射」就变成了「搭一整套数据库夹具」。
    """
    return Post(
        id=model.id,
        author_id=model.author_id,
        title=PostTitle(model.title),
        slug=Slug(model.slug),
        content=PostContent(model.content),
        summary=model.summary,
        cover_url=model.cover_url,
        status=model.status,
        published_at=model.published_at,
        view_count=model.view_count,
        deleted_at=model.deleted_at,
        tags=tuple(TagName(name) for name in tags),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


__all__ = ["apply_to_model", "to_entity", "to_model"]
