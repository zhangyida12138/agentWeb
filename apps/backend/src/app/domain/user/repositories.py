from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.user.entities import User
from app.domain.user.value_objects import Email


class UserRepository(ABC):
    """用户仓储接口：由领域层定义，基础设施层负责实现。

    返回值一律是领域实体，绝不泄漏 ORM 模型。
    """

    @abstractmethod
    async def add(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: Email) -> User | None: ...

    @abstractmethod
    async def list(self, *, offset: int = 0, limit: int = 20) -> list[User]: ...

    @abstractmethod
    async def delete(self, user_id: UUID) -> None: ...
