"""标签上下文的 ORM 模型：``tags`` 表。

⚠️ 模型**不是**领域实体：
    它是「表结构 + 索引 + 约束」的映射；状态机、归属校验住在
    ``domain/tag/entities.py``，两者由 ``mappers/tag.py`` 显式翻译。

字段顺序遵循 ``MappedAsDataclass`` 的硬性要求：**必填在前、选填在后**。
``base.py`` 的 mixin 已用 ``sort_order`` 把 ``id`` 提到最前（-100）、
时间戳压到最后（100/101），所以本类只需按「必填 → 选填」声明。

历史取舍变了，这里留个记录：
    早期标签只是文章的附属品（``repositories/post.py`` 里
    ``INSERT ... ON CONFLICT DO NOTHING`` 顺手造出来的），没有 id、没有状态，
    所以不需要独立的实体。
    独立成上下文之后它有了描述、状态、类型、归属，也就有了需要守护的规则，
    于是「表 + 实体 + mapper」这套东西才变得必要。

    ⚠️ 写路径上的按需创建**仍然保留**——作者在编辑器里敲一个新标签就直接建出来，
       那个入口不该先要求他「去标签管理页建一个标签，再回来写文章」。
       两条创建入口共存，所以这张表必须能承载「由谁创建」这个信息。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.blog.value_objects import TAG_NAME_MAX_LEN, TAG_SLUG_MAX_LEN
from app.domain.tag.entities import TagStatus, TagType
from app.domain.tag.value_objects import (
    TAG_DESCRIPTION_MAX_LEN,
    TAG_STATUS_MAX_LEN,
    TAG_TYPE_MAX_LEN,
)
from app.infrastructure.persistence.base import Base, IDMixin, TimestampMixin


class TagModel(Base, IDMixin, TimestampMixin):
    """tags 表。

    两列唯一索引各有明确用途，缺一不可：

    ``name`` 唯一
        让「按名字找标签、没有就创建」这个动作有唯一的落点。
        没有它，并发两次提交同一个新标签会造出两行同名记录，
        之后按名字查会随机命中其中一行，关联关系就分叉了。

    ``slug`` 唯一
        查询接口用 slug 过滤（``?tag=python``），
        它必须指向恰好一个标签；否则「python」标签的筛选结果会漏掉一半文章。
        slug 由 ``name`` 经 ``slugify`` 确定性派生，正常情况下两者一一对应。

        ⚠️ 也正因为两者**不总**一一对应（``"Node.js"`` 与 ``"Node js"`` 都会归化成 ``node-js``），
           应用层写入前必须**同时**检查 name 与 slug，不能只查一个——
           只查 name 就漏掉这类冲突，等到数据库唯一索引报错时，
           用户只会看到一句无从下手的「标签已存在」。
    """

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(TAG_NAME_MAX_LEN), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(TAG_SLUG_MAX_LEN), unique=True, index=True)

    # ── 以下 4 列是「标签升格为独立资源」新增的 ──
    #
    # status / type 是 **NOT NULL 且没有构造器默认值**：
    #   不给 dataclass default 是刻意的——写入方必须显式说出「这个标签给谁用、什么状态」。
    #   一旦有默认值，``repositories/post.py`` 那条批量插入路径就会在没人注意的情况下
    #   一直沿用同一个默认；将来想改默认值，就得满仓库找还有谁依赖了旧值。
    #
    #   ``server_default`` 则只服务于**存量数据与手工 SQL**：
    #   迁移给已有行补值靠它，数据修复脚本漏写这一列时也靠它兜底。
    #   两者并存并不矛盾：前者约束应用，后者约束表。
    status: Mapped[str] = mapped_column(
        String(TAG_STATUS_MAX_LEN),
        server_default=text(f"'{TagStatus.NORMAL}'"),
    )
    type: Mapped[str] = mapped_column(
        String(TAG_TYPE_MAX_LEN),
        server_default=text(f"'{TagType.USER}'"),
    )

    description: Mapped[str | None] = mapped_column(String(TAG_DESCRIPTION_MAX_LEN), default=None)

    # ondelete="SET NULL" 而不是 RESTRICT / CASCADE：
    #   RESTRICT 会挡住用户注销（本项目目前只做 is_active 停用，但注销迟早要做）；
    #   CASCADE 会「删掉用户时顺手删掉他建的标签」——而这些标签可能已经挂在别人的
    #   已发布文章上，删了等于把别人文章的标签抹掉，是不可接受的副作用。
    #   SET NULL 保留标签、只丢失归属，语义正好：
    #   「这个标签还在，但已经没人为它负责了」，此后只有管理员能改它
    #   （见 ``Tag.ensure_manageable_by``：无主的用户标签对普通人一律 403）。
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )

    __table_args__ = (
        # 公开列表的固定条件是「正常 + 非系统标签」，还要按 name 排序。
        # 把这两个常量条件放进索引，PG 就能直接在索引上定位候选区间，
        # 而不是扫全表再逐行过滤——标签表通常不大，但它是「读多写少」的典型，
        # 索引成本极低而收益稳定。
        #
        # ⚠️ 注意排序键（post_count desc）**进不了这个索引**：
        #    它是聚合结果，只能算完再排。真要优化，得引入物化视图或缓存计数器，
        #    那属于「标签用量统计」的独立话题，不该污染这张表的结构。
        Index("ix_tags_public_list", "status", "type", "name"),
    )

    def __repr__(self) -> str:
        """手写 __repr__ 覆盖 dataclass 自动生成的那个。

        自动生成的版本会把**所有**字段打出来，包括 ``description``——
        一段用户自由输入的文本。任何一次 ``logger.debug("tag=%s", model)``
        都会把它写进日志文件，等于绕过了「日志不含用户内容」这条约束。
        ``PostModel`` 出于同样理由排除了 ``content``，
        ``UserModel`` 排除了 ``password_hash``。
        """
        return f"<TagModel id={self.id!r} name={self.name!r} status={self.status!r}>"


__all__ = ["TagModel"]
