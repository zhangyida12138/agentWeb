"""博客上下文的 ORM 模型：``tags`` 表。

标签在**写入路径**上按需创建（见 ``repositories/post.py``），
所以这里没有独立的领域实体——它的一切都从 ``name`` 派生（``slug`` 亦然），
没有需要实体去守护的状态机。
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.blog.value_objects import TAG_NAME_MAX_LEN, TAG_SLUG_MAX_LEN
from app.infrastructure.persistence.base import Base, IDMixin, TimestampMixin


class TagModel(Base, IDMixin, TimestampMixin):
    """tags 表。

    两列都加唯一索引，各有明确用途，缺一不可：

    ``name`` 唯一
        让「按名字找标签、没有就创建」这个动作有唯一的落点。
        没有它，并发两次提交同一个新标签会造出两行同名记录，
        之后按名字查会随机命中其中一行，关联关系就分叉了。

    ``slug`` 唯一
        查询接口用 slug 过滤（``?tag=python``），
        它必须指向恰好一个标签；否则「python」标签的筛选结果会漏掉一半文章。
        slug 由 ``name`` 经 ``slugify`` 确定性派生，正常情况下两者一一对应。
    """

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(TAG_NAME_MAX_LEN), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(TAG_SLUG_MAX_LEN), unique=True, index=True)

    def __repr__(self) -> str:
        return f"<TagModel id={self.id!r} name={self.name!r}>"


__all__ = ["TagModel"]
