"""标签上下文：领域实体 ↔ ORM 模型的显式翻译。

为什么不让 ``TagModel`` 自带 ``to_entity()`` / ``from_entity()``：
    与 ``mappers/post.py`` 同源的理由——模型的职责是「映射一张表」，
    让它同时懂领域规则，就变成每加一个列都要顺手改翻译逻辑，
    而翻译一长出分支就没人敢动持久化层了。
    独立模块还能被单测直接覆盖，不需要数据库。

⚠️ 本模块的 ``to_model`` / ``apply_to_model`` / ``to_entity`` **没有**被
   ``mappers/__init__.py`` 重新导出，调用方要写成
   ``from app.infrastructure.persistence.mappers.tag import to_entity``。
   这不是遗漏：``mappers/user.py`` 与 ``mappers/post.py`` 已经占用了这三个名字，
   在 ``__init__.py`` 里再导出一份，后导入的会静默覆盖先导入的，
   于是 ``from ...mappers import to_model`` 到底拿到谁的版本，
   取决于 ``__init__.py`` 里 import 语句的先后顺序——
   那是一种「改一行 import 顺序就能让整层翻译错人」的隐患。
   同一层里出现同名多实现时，让调用方显式带上模块名，是最省心的解法。
"""

from __future__ import annotations

from app.domain.tag.entities import Tag
from app.infrastructure.persistence.models.tag import TagModel

_NO_ID_MESSAGE = "持久化前实体必须已有 id（Tag.create 会生成），否则无法保证写入幂等"


def to_model(entity: Tag) -> TagModel:
    """实体 → 模型（仅用于**新建**）。

    ``id`` 取实体自己生成的标识——标识由领域决定，ORM 不再自作主张。
    这一点在 ``base.py`` 里被写死了：``UuidPk`` 用的是 ``insert_default``，
    **不会**给 dataclass 生成构造器默认值，所以这里漏传 ``id`` 会直接在
    构造时就报类型/参数错误，而不是安静地让数据库生成一个新 id。
    这是刻意设计的：一个"忘了传 id"的 bug 应该在这里炸，而不是变成一个
    "实体 A 的 id 和库里的 id 不一致"的诡异现象。

    ``created_at`` / ``updated_at`` 故意不传：
        它们由 Column 级的 ``insert_default`` 在 INSERT 时填充。
        这里传值反而会覆盖掉统一的取值口径（例如某个调用方传了本地时区的时间）。
    """
    if entity.id is None:
        # 理论上 Tag.id 是必填的 UUID、不可能为 None，
        # 但类型上留了这个口子（与 Post 一致），所以仍然显式守住。
        raise ValueError(_NO_ID_MESSAGE)
    return TagModel(
        id=entity.id,
        name=entity.name,
        slug=entity.slug,
        status=entity.status,
        type=entity.type,
        description=entity.description,
        author_id=entity.author_id,
    )


def apply_to_model(entity: Tag, model: TagModel) -> None:
    """把实体的字段刷到**已存在**的模型上（用于更新）。

    ⚠️ 这里**不刷** ``type`` 与 ``author_id``，两个都刻意：
        ``type`` 表示「这个标签为什么存在」。它从 user 变成 system
            意味着它被"收编"进产品预置标签——这是一个需要显式流程的动作，
            不该搭着「改个描述」的便车悄悄发生。
        ``author_id`` 是归属。允许它被改，就等于允许「把标签转给别人」，
            而这件事目前没有任何接口语义需要（也没有转让记录可以追溯）。
            真要支持，应该是一个独立的 ``Tag.transfer_to(new_owner)``
            领域方法 + 独立接口，让它在审计上可见。

    所以本函数只处理"内容类"字段：名字、slug、描述、状态。
    """
    model.name = entity.name
    model.slug = entity.slug
    model.description = entity.description
    model.status = entity.status


def to_entity(model: TagModel, post_count: int = 0) -> Tag:
    """模型 → 实体。

    ``post_count`` 只能由调用方从**别处**算好传进来：
        它是 ``JOIN post_tags`` 的聚合结果，不是 ``tags`` 表的列。
        ``get_by_id`` 不传（默认 0，表示"这次没统计"），
        ``list_tags`` 会传真实值（一次 GROUP BY 查完整页）。
        为什么不在这里顺手算：
            mapper 是纯函数、不碰会话；一旦它开始发查询，
            调用方就再也无法判断"翻译一个模型"这件事的代价，
            而它会被放在循环里。
    """
    return Tag(
        id=model.id,
        name=model.name,
        slug=model.slug,
        type=model.type,
        author_id=model.author_id,
        description=model.description,
        status=model.status,
        post_count=post_count,
    )
