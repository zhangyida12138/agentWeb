"""互动上下文的 ORM 模型：``comments`` 表。

⚠️ 与 ``PostModel`` 一样：模型**不是**领域实体。
    「回复别人的评论」「撤回」这些规则住在 ``domain/interaction/entities.py``，
    这里只负责表结构、约束与索引。

字段顺序遵循 ``MappedAsDataclass`` 的硬性要求：必填在前、选填在后。
mixin 已用 sort_order 把 ``id`` 提到最前（-100）、时间戳压到最后（100/101/102）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.interaction.value_objects import COMMENT_CONTENT_MAX_LEN
from app.infrastructure.persistence.base import (
    Base,
    IDMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class CommentModel(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """comments 表（自引用，构成评论树）。"""

    __tablename__ = "comments"

    # ondelete="CASCADE"：文章被**物理删除**时评论一起消失。
    #   注意文章走的是软删除（``posts.deleted_at``），所以这条级联平时不会触发——
    #   它的意义是「万一真的物理删了一篇文章，不允许留下指向空气的评论」。
    #   考虑到评论对文章没有独立存在的意义，这里用 CASCADE 而不是 RESTRICT。
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        # 根评论的查询是 ``WHERE post_id = ? AND parent_id IS NULL ORDER BY created_at``，
        # 复合索引见 __table_args__
        index=True,
    )

    # ondelete="RESTRICT"，与 ``posts.author_id`` 保持一致：
    #   评论是**用户的创作内容**，不能因为「删掉某个用户」而连带蒸发。
    #   真要清理账号必须先显式处置内容——让这个决定被看见，而不是静默丢失。
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )

    # String 而不是 Text：评论长度上限是业务规则（``COMMENT_CONTENT_MAX_LEN``），
    # 不是一个「大概不会超」的猜测。用 String(N) 能让 PostgreSQL 在写入时就拒绝
    # 超长内容——应用层的值对象校验是第一道防线，这是第二道，
    # 也是唯一一道对「绕过 API 直接改库」仍然有效的防线。
    content: Mapped[str] = mapped_column(String(COMMENT_CONTENT_MAX_LEN))

    # 自引用外键：``parent_id`` 为空表示这是根评论，否则它挂在某条评论下面。
    # ondelete="CASCADE"：父评论被物理删除时子评论跟着走（同样是兜底，
    #   因为业务上父评论只会被**软删除**，回复要留在原地）。
    #
    # ★ 它存的是**用户真正回的那条评论**，不做任何归一：
    #   回一条回复时 parent_id 就是那条回复的 id，于是树可以任意深。
    #   曾经这里有个“归一到根”的设计（“树恒为两层”），
    #   代价是“他到底在回谁”在落库那一刻就被抹掉了，不可逆。
    #   缩进级数是展示层的事，不该由存储层替它决定。
    #
    # 为什么只存 parent_id、不额外存 root_id：
    #   任意深度的父子关系**已经是一张完整的图**，加一个 root_id
    #   存的是冗余（可由向上追父链算出来），而冗余列多一个会不一致的状态：
    #   “回一条回复”本就把 root_id 悄悄改成另一个值，维护它的人很容易漏。
    #   代价是找根要多走一次 ``WITH RECURSIVE``（见 ``SqlCommentRepository``），
    #   而这个数据量下那次递归完全不是瓶颈。
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), default=None
    )

    __table_args__ = (
        # 根评论分页：``post_id = ? AND parent_id IS NULL AND deleted_at IS NULL
        # ORDER BY created_at``。把过滤列放前面、排序列放最后，
        # 于是「定位 + 排序」在索引里一次完成，翻到第 N 页也不用排序全表。
        #
        # deleted_at 进索引的理由与 posts 相同：软删除行只增不减，
        # 把绝大多数查询都会排除掉的行挡在索引外，索引体积能小一大截。
        Index(
            "ix_comments_thread_roots",
            "post_id",
            "parent_id",
            "deleted_at",
            "created_at",
        ),
        # 递归取子树的每一步都是 ``parent_id = <上一层给出来的 id>``，
        # created_at 跟在后面是为了让“同一个父节点的孩子”天然有序，
        # 省掉应用层的排序（也省掉一次全量 sort）。
        Index("ix_comments_reply_fetch", "parent_id", "created_at"),
    )

    def __repr__(self) -> str:
        """手写 __repr__，**不打印 content**。

        理由同 ``PostModel``：用户内容不该进日志，而 dataclass 自动生成的
        ``__repr__`` 会把它一并打出来。这里额外多打一个 ``parent_id``，
        因为排查「回复挂错位置」时它是唯一有用的信息。
        """
        return (
            f"<CommentModel id={self.id!r} post_id={self.post_id!r} "
            f"parent_id={self.parent_id!r} author_id={self.author_id!r}>"
        )


__all__ = ["CommentModel"]
