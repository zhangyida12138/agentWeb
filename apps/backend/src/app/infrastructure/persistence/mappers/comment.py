"""互动上下文：``Comment`` 实体 ↔ ``CommentModel`` 的显式翻译。

与 ``mappers/post.py`` 同一套理由：翻译集中在一处、写成**纯函数**，
这样「字段映射」可以被两个对象直接单测，不需要数据库。

``LikeModel`` 没有对应的 mapper——它没有领域实体，见
``domain/interaction/__init__.py`` 里的说明。

一个容易踩的细节：``Comment.content`` 是**普通 str**，不是 ``CommentContent``。
值对象的职责是「进来的东西合法」，收敛发生在 ``Comment.create`` 那一行；
一旦成为实体属性它就是干净的字符串了，实体不需要（也不应该）让每个读到它的
地方都再剥一层 ``.value``。

两边都必须按这个口径写，而且**向两个方向都成立**：
    ``to_model``  写 ``entity.content``（str 直接进库）；
    ``to_entity`` 写 ``content=model.content``（库里读出来就是 str）。
只要有一边写了 ``.value`` 或包了 ``CommentContent(...)``，同一个实体就会因为
「从哪来」而持有两种类型：``create()`` 造的是 str，``to_entity()`` 返回的是值对象。
那种不一致不会在类型检查阶段暴露（字段都是宽泛的 str 注解），
只会让 ``public_content`` 偶尔返回个值对象，最后在响应模型的序列化上炸掉——
这正是本文件曾经的真实 bug（集成测试 first blood）。
"""

from __future__ import annotations

from app.domain.interaction.entities import Comment
from app.infrastructure.persistence.models.comment import CommentModel

_NO_ID_MESSAGE = "持久化前实体必须已有 id（Comment.create 会生成），否则无法保证写入幂等"


def to_model(entity: Comment) -> CommentModel:
    """实体 → 模型（仅用于**新建**）。

    created_at / updated_at 故意不传：由 Column 级的 insert_default / onupdate 填充，
    这里传值会覆盖掉统一的取值口径。

    ``deleted_at`` 也不传：软删除是显式动作，新建时必然为空。
    要传就得写一句 ``deleted_at=entity.deleted_at``，那等于允许「带着删除标记新建」——
    这种状态没有意义，不如让它根本表达不出来。
    """
    if entity.id is None:
        raise ValueError(_NO_ID_MESSAGE)
    return CommentModel(
        id=entity.id,
        post_id=entity.post_id,
        author_id=entity.author_id,
        content=entity.content,
        parent_id=entity.parent_id,
    )


def apply_to_model(entity: Comment, model: CommentModel) -> None:
    """把实体的可变字段刷到**已存在**的模型上（用于更新）。

    只有 ``content`` 与 ``deleted_at`` 是真正可变的：
        ``post_id`` 不可变——评论不能搬家，那会让它的回复全部失去父节点；
        ``parent_id`` 不可变——否则「把回复挂到别处」就成了一个隐形的编辑动作，
        而领域实体里没有任何方法会去改它，这里也就同步不回写。

    注意 ``author_id`` 也没有回写：评论的作者是既成事实。
    """
    model.content = entity.content
    model.deleted_at = entity.deleted_at


def to_entity(model: CommentModel) -> Comment:
    """模型 → 实体。

    逐个字段显式搬运（不用 ``**kwargs`` 透传）：模型加了字段却忘了翻译时，
    差异会直接暴露在 diff 里，而不是被一个万能透传悄悄地「顺手带上」。

    ``content`` 保持裸 str，**不**重新包成 ``CommentContent``：
        库里的内容在写入时就已过值对象校验，这里再包一次除了让实体类型变得
        「看出处而定」之外没有任何收益（写路径不经过这里，读路径不需要再校验）。
        真要防脏数据，那是迁移或数据修复脚本的职责，不该靠 mapper 顺手拦。
    """
    return Comment(
        id=model.id,
        post_id=model.post_id,
        author_id=model.author_id,
        content=model.content,
        parent_id=model.parent_id,
        deleted_at=model.deleted_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


__all__ = ["apply_to_model", "to_entity", "to_model"]
