"""文章 ↔ 标签 关联表。

与 ``user_role.py`` 的两个选择完全一致，理由也相同：

① **不继承** IDMixin / TimestampMixin —— 关联行没有自身标识，只有复合主键；
② **不声明 relationship()** —— 仓储一律用显式 JOIN，不依赖 ORM 关系加载，
   避免异步下的 MissingGreenlet 与 N+1。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class PostTagModel(Base):
    """post_tags 表（复合主键）。"""

    __tablename__ = "post_tags"

    # CASCADE 在这里是**必须**的，而不是可选的优化：
    #   标签是按需创建的资源，一个标签可能被 0 篇文章引用
    #   （作者删掉了唯一那篇文章）。没有 CASCADE 就会留下悬空的 (post_id, tag_id) 行，
    #   而任何按标签筛选的 JOIN 都会因此把不存在的文章也算进去。
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<PostTagModel post_id={self.post_id!r} tag_id={self.tag_id!r}>"


__all__ = ["PostTagModel"]
