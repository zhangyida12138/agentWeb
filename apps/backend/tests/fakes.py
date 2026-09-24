import copy
from uuid import UUID

from app.domain.user.entities import User
from app.domain.user.repositories import UserRepository
from app.domain.user.value_objects import Email


class InMemoryUserRepository(UserRepository):
    """测试替身：语义与 SqlAlchemyUserRepository 保持一致（写入时保存快照）。"""

    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def add(self, user: User) -> User:
        stored = copy.deepcopy(user)
        self._users[stored.id] = stored
        return copy.deepcopy(stored)

    async def update(self, user: User) -> User:
        stored = copy.deepcopy(user)
        self._users[stored.id] = stored
        return copy.deepcopy(stored)

    async def get_by_id(self, user_id: UUID) -> User | None:
        user = self._users.get(user_id)
        return copy.deepcopy(user) if user is not None else None

    async def get_by_email(self, email: Email) -> User | None:
        for user in self._users.values():
            if str(user.email) == str(email):
                return copy.deepcopy(user)
        return None

    async def list(self, *, offset: int = 0, limit: int = 20) -> list[User]:
        users = list(self._users.values())
        return [copy.deepcopy(user) for user in users[offset : offset + limit]]

    async def delete(self, user_id: UUID) -> None:
        self._users.pop(user_id, None)
