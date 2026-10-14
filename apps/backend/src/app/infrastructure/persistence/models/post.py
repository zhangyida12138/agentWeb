"""博客上下文的 ORM 模型：``posts`` 表。

⚠️ 模型**不是**领域实体：
    它是「表结构 + 索引 + 约束」的映射，状态机、归属校验一律住在
    ``domain/blog/entities.py``；两者由 ``mappers/post.py`` 显式翻译。

字段顺序遵循 ``MappedAsDataclass`` 的硬性要求：必填在前、选填在后。
``base.py`` 的 mixin 已用 sort_order 把 ``id`` 提到最前（-100）、
时间戳压到最后（100/101/102），所以本类只需按「必填 → 选填」声明。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.blog.value_objects import (
    POST_COVER_URL_MAX_LEN,
    POST_SLUG_MAX_LEN,
    POST_SUMMARY_MAX_LEN,
    POST_TITLE_MAX_LEN,
)
from app.infrastructure.persistence.base import (
    Base,
    IDMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

# 状态列的宽度。取值本身住在 ``domain/blog/entities.py::PostStatus``
# （领域是唯一来源），这里只需要一个「放得下最长取值」的宽度：
# ``published`` 9 个字符，给到 20 留出将来加状态的余地而不用改列类型。
STATUS_MAX_LEN = 20


class PostModel(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """posts 表。"""

    __tablename__ = "posts"

    # ondelete="RESTRICT"：有文章的用户**不能被物理删除**。
    #   选 RESTRICT 而不是 CASCADE，是因为「删掉用户顺手删掉他所有文章」
    #   在博客场景里是灾难性的默认值——那些文章可能已经有很多外链与阅读量。
    #   真要清理账号，必须先显式转移或删除文章，让这个决定被看见。
    #   （本项目目前对用户只做 is_active 停用、不做物理删除，这条约束是兜底。）
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )

    title: Mapped[str] = mapped_column(String(POST_TITLE_MAX_LEN))
    # slug 的唯一索引是「永久链接」这个承诺的技术保障：
    #   没有它，两篇文章可能同址，读哪篇取决于数据库的返回顺序。
    slug: Mapped[str] = mapped_column(String(POST_SLUG_MAX_LEN), unique=True, index=True)
    # Text 而不是 String(N)：正文长度不可预期，而 PostgreSQL 的 text 与 varchar 性能相同，
    # 用 text 省掉一个无意义的长度约束（真正的上限在值对象里）
    content: Mapped[str] = mapped_column(Text)

    summary: Mapped[str | None] = mapped_column(String(POST_SUMMARY_MAX_LEN), default=None)
    cover_url: Mapped[str | None] = mapped_column(String(POST_COVER_URL_MAX_LEN), default=None)

    # server_default 让「直接 INSERT 不带 status」也能落到 draft；
    # default 让 ORM 构造出来的对象在 flush 之前就已经是 draft（读起来一致）
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX_LEN),
        default="draft",
        server_default=text("'draft'"),
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), default=None, index=True
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    __table_args__ = (
        # 公开列表的排序是「published_at 倒序 + id 倒序」，
        # 而查询还要先过滤 status 与 deleted_at。单列索引 (status) / (published_at)
        # 都只能命中一半条件，PG 还得回表过滤剩下的一半。
        # 复合索引把「定位候选行」这一步一次做完，列表页的代价与表大小脱钩。
        #
        # 注意 deleted_at 也放进来了：绝大多数查询都带 ``deleted_at IS NULL``，
        # 而软删除行会长期堆积（只增不减），把它们排除在索引之外收益很大。
        Index("ix_posts_public_feed", "status", "deleted_at", "published_at"),
        # 「我的文章」按 (author_id, updated_at desc) 翻页，同理
        Index("ix_posts_author_updated", "author_id", "updated_at"),
    )

    def __repr__(self) -> str:
        """手写 __repr__ 覆盖 dataclass 自动生成的那个。

        自动生成的版本会把**所有**字段打出来，包括 ``content``——
        而正文可能有几万字。任何一次 ``logger.debug("post=%s", model)``
        都会把日志炸掉，更糟的是它会把用户内容写进日志文件（等于绕过了
        「出参不含敏感内容」那条 DoD）。
        ``UserModel`` 出于同样理由排除了 ``password_hash``。
        """
        return (
            f"<PostModel id={self.id!r} slug={self.slug!r} "
            f"status={self.status!r} author_id={self.author_id!r}>"
        )


__all__ = ["STATUS_MAX_LEN", "PostModel"]
