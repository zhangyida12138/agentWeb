"""身份上下文的仓储接口（端口）。

接口定义在 domain、实现在 infrastructure —— 依赖倒置的落点，
使 application 用例只依赖抽象，单测时可塞内存实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
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


__all__ = ["UserRepository"]
