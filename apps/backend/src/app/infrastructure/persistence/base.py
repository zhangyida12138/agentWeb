from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar

from sqlalchemy import TIMESTAMP, UUID, MetaData
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


# 公共列类型别名，减少样板
UuidPk = Annotated[
    uuid.UUID,
    mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        sort_order=-100,
    ),
]
CreatedAt = Annotated[
    datetime,
    mapped_column(
        TIMESTAMP(timezone=True),
        default=_utc_now,
        nullable=False,
        sort_order=100,
    ),
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        TIMESTAMP(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
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


class IDMixin(MappedAsDataclass):
    """给实体加 UUID 主键。"""

    id: Mapped[uuid.UUID] = UuidPk  # type: ignore[assignment]


class TimestampMixin(MappedAsDataclass):
    """给实体加创建/更新时间（UTC 时区）。"""

    created_at: Mapped[datetime] = CreatedAt  # type: ignore[assignment]
    updated_at: Mapped[datetime] = UpdatedAt  # type: ignore[assignment]


class SoftDeleteMixin(MappedAsDataclass):
    """给实体加软删除标记（posts / comments 用）。"""

    deleted_at: Mapped[datetime | None] = DeletedAt  # type: ignore[assignment]
