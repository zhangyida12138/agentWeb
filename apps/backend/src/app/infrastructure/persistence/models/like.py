"""互动上下文的 ORM 模型：``likes`` 表（多态点赞）。

⚠️ 这个模型**没有对应的领域实体**，这是有意的决定，理由写在
``domain/interaction/__init__.py`` 里：一张「行为记录表」没有状态机、
没有跨字段不变量（唯一的规则「同一人同一目标只能有一行」由唯一约束表达），
硬造一个三字段的实体只会变成表结构的镜像，还要额外写一份映射与一套测试。

**多态外键**（``target_type`` + ``target_id``）是这张表最需要解释的设计。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.interaction.value_objects import LIKE_TARGET_TYPE_MAX_LEN
from app.infrastructure.persistence.base import Base, CreatedAt, IDMixin


class LikeModel(Base, IDMixin):
    """likes 表。"""

    __tablename__ = "likes"

    # ondelete="CASCADE"：用户被物理删除时他的点赞记录一起消失。
    #   这里与 ``posts.author_id`` 的 RESTRICT 是**相反**的选择，因为两者性质不同：
    #   文章是创作内容（不能连带蒸发），点赞只是一条行为记录——
    #   保留一个已不存在用户的赞，既没有价值也没有出处。
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    # ── 多态目标 ───────────────────────────────────────────────
    # ``target_id`` **故意不建外键**，因为它指向哪张表取决于 ``target_type``：
    #   PostgreSQL 不支持「按另一列的值决定引用哪张表」的外键
    #   （那是多态外键的固有限制，不是这里的疏忽）。
    #
    # 那么「指向不存在的目标」怎么办？由**应用层**在写入前校验（``ToggleLikeUseCase``）。
    # 这看起来比数据库约束弱，但它是这个业务唯一站得住的方案：
    #   ① 拆成 post_likes / comment_likes 两张表 —— 表结构翻倍，
    #      而所有「统计一个目标有多少赞」的查询都要写两遍 UNION，
    #      唯一约束的收益换不来这份持续成本；
    #   ② 加触发器 —— 逻辑从 Python 跑到数据库里，从此调试要连数据库一起看，
    #      而且迁移到别的库（测试用 SQLite 的团队）会直接失效。
    # 代价是可能残留脏行（指向已删除的目标）。这个代价可以接受，因为：
    #   · 读路径是**按目标反查**（``WHERE target_type=? AND target_id=?``），
    #     永远不会遍历到脏行，所以它不会污染任何一个计数；
    #   · 目标是软删除的（评论、文章都是），行本来就还在表里；
    #   · 即使真出现脏行，也不影响任何功能的正确性，只占一点空间。
    target_type: Mapped[str] = mapped_column(String(LIKE_TARGET_TYPE_MAX_LEN))
    target_id: Mapped[uuid.UUID] = mapped_column()

    # created_at 只声明一列，**不带 updated_at**：
    #   点赞是不可变的行为记录，它没有「被修改」这个概念。
    #   给一张只读表配一个永远不会变化的 updated_at 列，只会让读者
    #   以为「这里可能被改过」，从而多花时间去追一条不存在的线索。
    #   （删除采取物理删除，不是软删除——同理：取消点赞之后这条记录
    #   没有任何需要保留的审计价值，留着它只会让唯一约束变复杂。）
    created_at: Mapped[CreatedAt] = mapped_column(init=False)

    __table_args__ = (
        # ★ 重复点赞不重复计数，靠的就是这条**数据库级**唯一约束。
        #   不能只靠应用层「先查后写」：两个并发的双击请求会各查一次、
        #   都发现没赞过、然后各插一行，于是计数变 2。
        #   这条约束让第二次插入必然失败，而仓储用
        #   ``INSERT ... ON CONFLICT DO NOTHING`` 把这次失败变成一个无害的 no-op——
        #   既保证了不重复，又不会把并发冲突变成 500。
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_likes_user_target"),
        # 统计与查询都按目标走：``WHERE target_type=? AND target_id=?``。
        # 索引顺序是 (target_type, target_id) 而不是反的——
        # 低基数的列（只有两种取值）放前面，让同一个目标的所有赞在索引里连续，
        # 聚合就是一次范围扫描而不是全表扫描。
        Index("ix_likes_target", "target_type", "target_id"),
        # user_id 上的索引由上面的唯一约束顺带提供（唯一约束的最左前缀就是 user_id），
        # 所以「我赞过哪些」这类查询也能命中索引，不必再建一条。
    )

    def __repr__(self) -> str:
        """点赞行没有敏感内容，直接把定位信息打全。"""
        return (
            f"<LikeModel id={self.id!r} user_id={self.user_id!r} "
            f"{self.target_type}={self.target_id!r}>"
        )


__all__ = ["LikeModel"]
