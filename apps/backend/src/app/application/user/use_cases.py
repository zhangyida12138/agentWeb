from uuid import UUID

from app.application.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from app.application.user.dto import (
    CreateUserCommand,
    ListUsersQuery,
    UpdateUserCommand,
    UserDTO,
)
from app.domain.user.entities import User
from app.domain.user.repositories import UserRepository
from app.domain.user.value_objects import Email


class UserUseCases:
    """用户应用服务：编排领域对象与仓储，不包含框架相关代码。"""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def create_user(self, command: CreateUserCommand) -> UserDTO:
        email = Email(command.email)
        if await self._users.get_by_email(email) is not None:
            raise EntityAlreadyExistsError("用户", str(email))

        user = User.register(email=email, display_name=command.display_name)
        return UserDTO.from_entity(await self._users.add(user))

    async def get_user(self, user_id: UUID) -> UserDTO:
        return UserDTO.from_entity(await self._get_or_raise(user_id))

    async def list_users(self, query: ListUsersQuery) -> list[UserDTO]:
        users = await self._users.list(offset=query.offset, limit=query.limit)
        return [UserDTO.from_entity(user) for user in users]

    async def update_user(self, user_id: UUID, command: UpdateUserCommand) -> UserDTO:
        user = await self._get_or_raise(user_id)

        if command.display_name is not None:
            user.rename(command.display_name)
        if command.is_active is not None:
            if command.is_active:
                user.activate()
            else:
                user.deactivate()

        return UserDTO.from_entity(await self._users.update(user))

    async def delete_user(self, user_id: UUID) -> None:
        await self._get_or_raise(user_id)
        await self._users.delete(user_id)

    async def _get_or_raise(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("用户", user_id)
        return user
