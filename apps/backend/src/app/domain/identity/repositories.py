"""身份上下文的仓储接口（端口）。

接口定义在 domain、实现在 infrastructure —— 依赖倒置的落点，
使 application 用例只依赖抽象，单测时可塞内存实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.identity.entities import User
from app.domain.identity.value_objects import Email, Username


class UserRepository(ABC):
    """用户仓储接口：只声明「需要什么能力」，不关心怎么实现。"""

    @abstractmethod
    async def add(self, user: User) -> User:
        """新增用户并返回带 id 的实体。"""

    @abstractmethod
    async def update(self, user: User) -> User:
        """更新已存在的用户（资料 / 密码 / 状态）。"""

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None:
        """按主键查询。"""

    @abstractmethod
    async def get_by_email(self, email: Email) -> User | None:
        """按邮箱查询（登录用）。"""

    @abstractmethod
    async def get_by_username(self, username: Username) -> User | None:
        """按用户名查询（注册查重用）。"""

    @abstractmethod
    async def get_by_ids(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """**批量**按主键取用户，返回 ``{user_id: User}``。

        为 ``get_by_id`` 的批量版而存在，理由与 ``LikeRepository.count_many``
        完全一样：**消灭 N+1**。

        第一个真正需要它的场景是评论树：接口要把「谁写的」渲染成人名，
        而一页评论树有几十个作者。逐条 ``get_by_id`` 就是几十次往返，
        且随页大小线性增长；批量版恒定一次，与页大小无关。
        （这也是为什么不让前端拿着 ``author_id`` 回查
        ``GET /users/{id}``：那只是把 N+1 从后端搬到浏览器，
        顺带还把「谁能看到谁的用户名」这个授权问题弄得更乱。）

        **查不到就查不到**：缺失的 id 不会出现在返回值里，也不补任何占位值。
        调用方用 ``.get(id)`` 读，语义是「这个人取不到了」而不是「这个人叫 None」——
        用户是物理删除的（不是软删除），于是「作者已经不在库里」
        是个真实存在的情况，而它应该由调用方决定怎么展示，
        不该在这里被静默替换成一个假名字。
        """

    @abstractmethod
    async def list_paged(self, offset: int, limit: int) -> list[User]:
        """按创建时间倒序取一段用户。

        刻意**不设默认值**：一次取多少条是表现层策略
        （见 ``agent_web_shared.pagination`` 的 DEFAULT_LIMIT / MAX_LIMIT），
        domain 只声明「能按偏移取一段」，不规定取多少。
        """

    @abstractmethod
    async def count(self) -> int:
        """用户总数（与 ``list_paged`` 配套，供分页响应回传 total）。"""


__all__ = ["UserRepository"]
