"""add tag management fields

Revision ID: 8c41d2f7a930
Revises: db936358c4a8
Create Date: 2026-11-05 10:24:11.884219

把「标签」从文章的附属品升格为独立资源所需要的那几列。

背景：``tags`` 表原先只有 ``name`` / ``slug``——那时的标签只有一个用途，
就是给文章打标，而 ``slug`` 由 ``name`` 确定性地派生出来，
所以整张表是"纯粹派生的数据"，没有需要守护的规则，也就不需要领域实体。
独立成上下文之后它有了描述、状态、类型、归属，因此需要这几列。

⚠️ 这个迁移的**唯一风险点是存量数据**：

   ``status`` / ``type`` 是 ``NOT NULL``，而表里可能已经有行了。
   PostgreSQL 在 ``ADD COLUMN ... NOT NULL`` 时会用 ``server_default``
   把已有行填上，从 11 版本起还不会重写整张表（只写元数据），
   所以这里**必须**给出 ``server_default``——否则迁移会直接失败
   （"column contains null values"）。

   ``author_id`` 是**可空**的，存量行留 NULL。这是刻意接受的：
       我们无法回溯"这个标签是谁建的"——那个信息从来没被记录过。
       与其瞎猜一个用户（比如把它全挂给管理员），
       不如诚实地留空。``SET NULL`` 的语义本身也允许这种状态：
       "这个标签还在，但已经没人为它负责了"，
       此后只有管理员能改它（见 ``Tag.ensure_manageable_by``）。

   要不要写一个 data migration 把存量标签的 status 显式 UPDATE 一遍？
       不需要：``server_default`` 已经让列里是 ``'normal'`` 了，
       再跑一遍 UPDATE 只是把同一件事做第二次，还多了一次全表写。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c41d2f7a930"
down_revision: str | Sequence[str] | None = "db936358c4a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """给 tags 表补上 status / type / description / author_id 四列。"""
    # 顺序：先加「无外键依赖」的列，再加 author_id，
    # 这样万一 author_id 的外键建失败，前面的列已经落好，
    # 重跑时不用从零开始（alembic 的事务里其实会整体回滚，
    # 但这份顺序让阅读者一眼看出「哪些是独立变更、哪个引入了新依赖」）。
    op.add_column(
        "tags",
        sa.Column(
            "status",
            sa.String(length=20),
            # server_default 的字面量要**带引号**：传给 sa.text 的是一段 SQL 片段，
            # 直接写 "normal" 会渲染成 DEFAULT normal（一个列名），建表直接报错。
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tags",
        sa.Column(
            "type",
            sa.String(length=20),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
    )
    op.add_column(
        "tags",
        sa.Column("description", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "tags",
        sa.Column("author_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_tags_author_id_users"),
        "tags",
        "users",
        ["author_id"],
        ["id"],
        # SET NULL 而不是 CASCADE / RESTRICT：见 models/tag.py 里那段说明。
        # 一句话：标签可能挂在别人的已发布文章上，不能跟着创建者一起消失；
        # 但也不能反过来挡住创建者离开。保留标签、只丢掉归属，语义正好。
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_tags_author_id"), "tags", ["author_id"], unique=False)
    # 公开列表的固定筛选条件是 (status, type)，排序键是 name。
    # 前两个是常量等值条件、第三个是范围条件，所以这个列顺序是有效的：
    # 等值列必须排在范围列前面，否则索引只能用到第一列。
    op.create_index("ix_tags_public_list", "tags", ["status", "type", "name"], unique=False)


def downgrade() -> None:
    """Upgrade schema."""
    # 顺序与 upgrade 严格相反。这里不是严格必需的（PG 会自己处理依赖），
    # 但反过来写能让 diff 一眼看清「upgrade 建了什么、downgrade 就该拆什么」。
    op.drop_index("ix_tags_public_list", table_name="tags")
    op.drop_index(op.f("ix_tags_author_id"), table_name="tags")
    op.drop_constraint(op.f("fk_tags_author_id_users"), "tags", type_="foreignkey")
    op.drop_column("tags", "author_id")
    op.drop_column("tags", "description")
    op.drop_column("tags", "type")
    op.drop_column("tags", "status")
