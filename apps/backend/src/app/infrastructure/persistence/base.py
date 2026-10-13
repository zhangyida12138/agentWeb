from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar

from sqlalchemy import TIMESTAMP, UUID, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

# SQLAlchemy 2.0 推荐：集中定义命名约定，避免索引/外键匿名
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ──────────────────────────── 公共列类型别名 ────────────────────────────
#
# ⚠️ 全部使用 insert_default 而不是 default，原因有二：
#   1. MappedAsDataclass 语境下 `default` 会**同时**成为构造器默认值。
#      而 id 是主键、必须由领域实体显式传入（标识由领域生成），不能有构造器默认值，
#      否则 dataclass 会报 "non-default argument 'email' follows default argument"；
#   2. `default` 传可调用对象（如 _utc_now）时语义是模糊的——它到底该当成
#      「构造器里调用的工厂」还是「INSERT 时的列默认值」？SQLAlchemy 明确建议
#      用 insert_default / default_factory 把这个歧义消掉。
#   insert_default 只设置 Column 级默认，完全不碰构造器签名。
UuidPk = Annotated[
    uuid.UUID,
    mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        insert_default=uuid.uuid4,
        sort_order=-100,
    ),
]
CreatedAt = Annotated[
    datetime,
    mapped_column(
        TIMESTAMP(timezone=True),
        insert_default=_utc_now,
        # 同时给一个服务端默认值：INSERT 时 ORM 用的是 _utc_now（Python 侧），
        # 但手工 SQL / 数据修复脚本若漏了这一列，NOT NULL 会直接报错。
        # 服务端默认让表结构自身完整，不必依赖应用一定在场。
        server_default=func.now(),
        nullable=False,
        sort_order=100,
    ),
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        TIMESTAMP(timezone=True),
        insert_default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
        nullable=False,
        sort_order=101,
    ),
]
DeletedAt = Annotated[
    datetime | None,
    mapped_column(
        TIMESTAMP(timezone=True),
        default=None,
        nullable=True,
        sort_order=102,
    ),
]


class Base(DeclarativeBase):
    """全局 Declarative 基类（Alembic 的 target_metadata 指向它）。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
    }


class IDMixin(MappedAsDataclass, eq=False):
    """给实体加 UUID 主键。

    两个容易踩的点：

    ① 写法是 ``Mapped[UuidPk]`` 而**不是** ``Mapped[uuid.UUID] = UuidPk``：
       后者把 Annotated 别名当成了「赋给字段的默认值」，列级选项（sort_order 等）
       并不按预期生效，实测直接抛 dataclass 的字段顺序错误。
       ``Mapped[别名]`` 才是 SQLAlchemy 文档里的复用写法。

    ② ``eq=False``：dataclass 默认会生成「逐字段比较」的 ``__eq__``，并按惯例把
       ``__hash__`` 置为 None。这对 ORM 实体是错的——实体的相等性应由主键/身份决定，
       且不可哈希会让对象无法放进 set / 当 dict 键。``eq=False`` 保留 object 的
       身份比较与哈希，与 SQLAlchemy 的 identity map 语义一致。
    """

    id: Mapped[UuidPk]


class TimestampMixin(MappedAsDataclass, eq=False):
    """给实体加创建/更新时间（UTC 时区）。

    created_at / updated_at 用 ``init=False`` 排除出构造器，理由：
      1. 它们是审计字段，业务代码不该传、也不需要传；
      2. MappedAsDataclass 硬性要求「无默认值的字段必须排在带默认值的字段之前」，
         而 mixin 的字段位置不由子类控制——只要审计字段还留在构造器里，
         任何「必填业务字段写在子类」的模型都会踩到这个顺序冲突。
    取值交给 Column 级的 insert_default / onupdate，INSERT 之后 ORM 会把
    数据库里的值回填到实例属性上，因此 flush 完仍能从模型读到 created_at。
    """

    created_at: Mapped[CreatedAt] = mapped_column(init=False)
    updated_at: Mapped[UpdatedAt] = mapped_column(init=False)


class SoftDeleteMixin(MappedAsDataclass, eq=False):
    """给实体加软删除标记（posts / comments 用）。"""

    deleted_at: Mapped[DeletedAt] = mapped_column(init=False)
