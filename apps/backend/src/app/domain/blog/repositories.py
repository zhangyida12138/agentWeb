"""博客上下文的仓储接口（端口）。

接口定义在 domain、实现在 infrastructure —— 依赖倒置的落点。
用例只认识这里的抽象方法，于是「换 ORM」「换数据库」「单测塞一个内存实现」
都不需要动用例一行代码。

关于方法的**入参类型**：能用值对象就用值对象（``Slug`` / ``TagName``）。
    裸 ``str`` 的签名对调用方是零约束的：「传个空串进去」编译器不会拦、
    类型检查器也不会拦，只有运行到 SQL 才可能出问题。
    收 ``Slug`` 则意味着「这个字符串已经被校验过」，把约束前移到类型上。

关于**软删除**：所有查询都必须在 SQL 里就排除 ``deleted_at IS NOT NULL`` 的行。
    不依赖「调用方记得过滤」——那种约定迟早会被某条新加的查询忘掉，
    而忘记的后果是「已删除的文章出现在公开列表里」。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要，避免运行时循环 import
    from app.domain.blog.entities import Post
    from app.domain.blog.value_objects import Slug, TagName


class PostRepository(ABC):
    """文章仓储接口。

    读写都走「聚合根」：``Post`` 连同它的 ``tags`` 一起进出。
    这里说的 ``tags`` 是**文章身上的标签名集合**（``tuple[TagName, ...]``），
    不是一个独立的标签资源。

    ⚠️ 标签已经单独成上下文了（``domain/tag``），两者的边界是：

    ``PostRepository``（这里）
        文章 ↔ 标签的**关联**。保存文章时标签集合被整体替换；
        遇到不认识的标签名时按需创建（这是唯一"文章侧会写 tags 表"的地方）。

    ``TagRepository``（``domain/tag``）
        标签**自身**：名字、描述、状态、类型、归属。改名 / 下架 / 删除走那边。

    为什么没有把标签一起搬过去：
        那会让「保存一篇文章」变成跨两个仓储的两步写入，
        而这两步必须在同一个事务里成对成功——把一个原子动作拆成两个正好相反，
        是比"职责不够纯净"严重得多的问题。
    """

    # ────────────── 写入 ──────────────

    @abstractmethod
    async def add(self, post: Post) -> Post:
        """插入新文章（连同标签关联），返回落库后的实体。

        为什么回传实体而不是 ``None``：
            插入会补齐 ``created_at`` / ``updated_at`` 等由数据库/映射决定的值，
            回传一份「真实的当前状态」能保证用例拿到的对象和库里完全一致，
            而不是「一半内存值、一半未知」。

        实现方**只 flush 不 commit**：
            事务边界只属于 ``core/database.py::get_db``，
            仓储一 commit 就会把「一个请求一个事务」拆成多个，
            中途失败时前面的写入已经落地，回滚无从谈起。
        """

    @abstractmethod
    async def update(self, post: Post) -> Post:
        """按下标 upsert 已有文章（含标签关联的整体对齐）。"""

    # ────────────── 单条查询 ──────────────

    @abstractmethod
    async def get_by_id(self, post_id: UUID) -> Post | None:
        """按 id 取文章（不含已软删除的）。"""

    @abstractmethod
    async def get_by_slug(self, slug: Slug) -> Post | None:
        """按 slug 取文章（不含已软删除的）——公开阅读的主入口。"""

    @abstractmethod
    async def exists_slug(self, slug: Slug, *, exclude_id: UUID | None = None) -> bool:
        """slug 是否已被占用。

        ``exclude_id`` 用来排除「自己」：改文章时 slug 没变，
        但要校验的话它永远查得到自己，于是「不改 slug 的保存」会直接报 409。
        这种参数必须显式存在，而不是靠调用方「记得先比对一下」。
        """

    # ────────────── 列表查询 ──────────────

    @abstractmethod
    async def list_published(
        self,
        offset: int,
        limit: int,
        *,
        tag: TagName | None = None,
    ) -> list[Post]:
        """公开列表：只含 ``status = published`` 的文章，按发布时间倒序。

        ``tag`` 不为空时按标签过滤（走 ``post_tags`` 关联，不是全文搜索）。
        """

    @abstractmethod
    async def count_published(self, *, tag: TagName | None = None) -> int:
        """公开列表总数。必须与 ``list_published`` 的过滤条件**逐字一致**，
        否则前端会看到「共 10 条」但翻了 3 页就空了。"""

    @abstractmethod
    async def list_by_author(
        self,
        author_id: UUID,
        offset: int,
        limit: int,
        *,
        status: str | None = None,
    ) -> list[Post]:
        """我的文章：该作者的**全部**状态（含草稿与归档），按更新时间倒序。

        与公开列表的排序不同是刻意的：
            公开列表关心「读者按什么顺序看到新内容」（发布时间），
            我的文章关心「我最近动过哪一篇」（更新时间）。
            作者刚改过的草稿应该浮到最上面。
        """

    @abstractmethod
    async def count_by_author(self, author_id: UUID, *, status: str | None = None) -> int:
        """我的文章总数（过滤条件需与 ``list_by_author`` 一致）。"""

    # ────────────── 计数 ──────────────

    @abstractmethod
    async def increment_view_count(self, post_id: UUID) -> int:
        """浏览量 +1 并返回**自增后**的值。

        必须是数据库侧的原子自增（``SET view_count = view_count + 1 RETURNING ...``）：
            应用侧「读出来 +1 再写回去」在并发下会丢更新。
        """


__all__ = ["PostRepository"]
