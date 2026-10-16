"""标签上下文的仓储抽象（端口）。

``TagRepository`` 是**端口**：领域层只声明「我需要什么能力」，
不关心背后是 PostgreSQL、内存字典还是测试替身，也不 import 任何 SQLAlchemy 符号。

⚠️ 抽象方法签名里的 ``Tag`` 引用的是 ``domain/tag/entities.py`` 的实体，
   **不是** ``TagModel``。端口只收发领域对象；
   一旦某个抽象方法签名里出现了 ``TagModel``，这层就漏了。

这层最容易被写坏的两种方式，本文件刻意避开了：

① **把 ORM 的便利泄漏成端口能力**
   「按 slug 查」「按 name 查」这类方法，如果当初是照着 SQL 的 ``where`` 顺手加的，
   端口就会越长越像一张表。真正需要问业务的是「这个名字还能用吗」（``exists_name``），
   「这个 slug 还能用吗」（``exists_slug``）——它们回答的是**规则问题**，
   而不是"执行一次 select"。端口上多一个 ``get_by_slug``，
   就意味着多一条「谁在什么情况下会调用它」无人能答的路径。

② **在端口上做软删除的默认过滤**
   ``list_tags`` 默认只返回未被删除的标签，但 ``get_by_id`` **不会**过滤。
   理由见各自方法的说明——一句话：删除是"看不见"，不是"不存在"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.tag.entities import Tag


class TagRepository(ABC):
    """标签仓储端口。

    与 ``AccessRepository`` 的一个关键区别：**这里没有事务控制**。
    ``add`` / ``update`` 都不 ``commit``，只把变更交给当前会话，由
    ``core/database.py::get_db`` 在请求成功时统一提交、异常时统一回滚。
    仓储自己提交，就等于把一个请求内多次写入拆成了多个独立事务——
    「先改标签再改文章」这种操作一旦失败，会留下半套数据。

    ⚠️ 所有方法都只 ``flush()``，不 ``commit()``。这是全项目铁律。
    """

    # ────────────── 查询 ──────────────

    @abstractmethod
    async def get_by_id(self, tag_id: UUID) -> Tag | None:
        """按 id 取标签，不存在返回 ``None``。

        **不过滤 ``status``**（连 ``deleted`` 也查得到），这是刻意的：
            写路径（改名 / 改状态 / 软删除 / 恢复）必须能拿到已删除的标签，
            否则「把删掉的标签恢复回来」这件事从物理上就不可能实现。
            「已删除 == 不存在」是**读路径**的对外承诺，
            由用例在拿到实体后判断，而不是由仓储假装查不到。
        """

    @abstractmethod
    async def exists_name(self, name: str, *, exclude_id: UUID | None = None) -> bool:
        """标签名是否已被占用。

        ``exclude_id`` 用于「改名」场景：判断一个名字是否可用时，
            自己显然占着这个名字，必须把它排除掉，
            否则「把 Python 改成 Python」会得到 409 这种莫名其妙的结果。
        """

    @abstractmethod
    async def exists_slug(self, slug: str, *, exclude_id: UUID | None = None) -> bool:
        """slug 是否已被占用。

        单独暴露而不是只留 ``exists_name``：
            两个不同的名字可以归化出同一个 slug（``"Node.js"`` 与 ``"Node js"`` 都会变成
            ``c``）。只查 name 会发现不了这种冲突，等落到数据库唯一索引上才报错，
            错误信息对用户就只剩一句「标签已存在」——而这正是我们要避免的体验。
        """

    @abstractmethod
    async def list_tags(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        keyword: str | None = None,
        author_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Tag]:
        """分页查标签，返回的实体带 ``post_count``。

        ⚠️ 五个筛选参数**全部是 ``None`` 表示「不筛」**，而不是「筛出 NULL」。
           调用方想查「已删除的标签」就传 ``status="deleted"``，
           想查全部就一个都不传——不存在「筛 status 为 NULL」这种需求，
           因为 ``status`` 列是 NOT NULL。默认值就是最常用的那个语义。

        ``post_count`` 的统计口径由实现决定，但有一条硬约束：
            **只统计已发布且未删除的文章**。把草稿和软删除的文章算进去，
            会让一个刚建好的标签显示「3 篇文章」，点进去却什么都没有。

        ⚠️ ``status`` / ``type`` 的类型是 ``str``，不是 ``TagStatus`` / ``TagType``。
           这两个类只是常量的命名空间、不是类型，写上去类型检查会放过所有拼写错误。
            取值合法性由用例调用 ``TagStatus.parse`` / ``TagType.parse`` 保证。
        """

    @abstractmethod
    async def count_tags(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        keyword: str | None = None,
        author_id: UUID | None = None,
    ) -> int:
        """按同样条件统计总数（分页用）。

        条件参数必须与 ``list_tags`` **逐字一致**：
            只要有一个参数只在一边生效，页码就会出现「第 2 页空白」
            或「最后一页多出一页」，而且两处代码看起来都完全正常。
            这是把「筛选条件」这件事放在同一个私有方法里构造的理由。
        """

    # ────────────── 写入 ──────────────

    @abstractmethod
    async def add(self, tag: Tag) -> Tag:
        """插入一个新标签，返回落库后的实体。

        ``tag.id`` 由领域层在 ``Tag.create()`` 里生成，仓储**必须**原样使用，
            不能忽略它去依赖数据库默认值。理由见 ``entities.Tag.create`` 的说明。

        唯一性冲突（name / slug 撞车）由实现在此处翻译成
            ``TagAlreadyExistsError``。为什么放在实现里而不是用例里：
            用例已经在写之前查过一次（为了给出友好的 409），但「查过」和
            「插入成功」之间存在竞态——两个请求同时创建 ``python``，
            两边都查到"不存在"，然后一边会撞在唯一索引上。
            这一层是最后一道闸，它必须把数据库的 ``IntegrityError``
            转成同一个领域异常，让调用方只需要处理一种失败。
        """

    @abstractmethod
    async def update(self, tag: Tag) -> Tag:
        """按 ``tag.id`` 整体更新已存在的标签，返回更新后的实体。

        传的是**完整实体**而不是「字段名 → 新值」的补丁：
            补丁签名的类型是 ``dict[str, object]``，等于把类型安全丢在边界上——
            用例传 ``{"statuz": "deleted"}`` 也能通过类型检查，
            直到运行时才安静地什么都不改。

        标签不存在时抛 ``TagNotFoundError``，不返回 ``None``：
            调用方在这一步**一定**已经拿到过实体（先 ``get_by_id`` 做归属校验），
            所以"找不到"意味着并发删除，是一个异常情况，
            不该让每个调用点都写一遍 ``if result is None``。

        ⚠️ 实现中**不能**出现 ``commit()``。
        """
