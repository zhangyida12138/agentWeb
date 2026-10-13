"""领域实体 ↔ ORM 模型的显式翻译。

为什么不让 ``UserModel`` 自带 ``to_entity()``：
    那会让「表结构」和「领域规则」缠在一起——模型每加一个字段都要顺手改翻译逻辑，
    而且翻译一旦出错会污染整个持久化层。集中在这个模块，翻译规则一眼可见，也能单测。
"""

from __future__ import annotations

from app.domain.identity.entities import User
from app.domain.identity.value_objects import Email, Username
from app.infrastructure.persistence.models.user import UserModel

_NO_ID_MESSAGE = "持久化前实体必须已有 id（User.register 会生成），否则无法保证写入幂等"


def to_model(entity: User) -> UserModel:
    """实体 → 模型（仅用于**新建**）。

    id 取实体自己生成的标识——标识由领域决定，ORM 不再自作主张。
    created_at / updated_at 故意不传：它们由 Column 级的 insert_default 在 INSERT 时填充，
    这里传值反而会覆盖掉统一的取值口径。
    """
    if entity.id is None:
        raise ValueError(_NO_ID_MESSAGE)
    return UserModel(
        id=entity.id,
        email=entity.email.value,
        username=entity.username.value,
        password_hash=entity.password_hash,
        display_name=entity.display_name or entity.username.value,
        avatar_url=entity.avatar_url,
        bio=entity.bio,
        is_active=entity.is_active,
    )


def apply_to_model(entity: User, model: UserModel) -> None:
    """把实体的可变字段刷到**已存在**的模型上（用于更新）。

    不碰 id / created_at / updated_at：
        id 是身份标识，后两个是审计信息，都不在领域实体能改动的范围内。
        updated_at 由 Column 的 onupdate 在 UPDATE 语句里自动刷新。
    """
    model.email = entity.email.value
    model.username = entity.username.value
    model.password_hash = entity.password_hash
    model.display_name = entity.display_name or entity.username.value
    model.avatar_url = entity.avatar_url
    model.bio = entity.bio
    model.is_active = entity.is_active


def to_entity(model: UserModel) -> User:
    """模型 → 实体。

    逐个字段显式搬运，不用 ``**kwargs`` 透传：
    显式列出才能让「模型加了字段但忘了翻译」在 code review 里一眼看出来。
    """
    return User(
        id=model.id,
        email=Email(model.email),
        username=Username(model.username),
        password_hash=model.password_hash,
        display_name=model.display_name,
        avatar_url=model.avatar_url,
        bio=model.bio,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


__all__ = ["apply_to_model", "to_entity", "to_model"]
