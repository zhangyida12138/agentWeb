from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user.entities import User
from app.domain.user.repositories import UserRepository
from app.domain.user.value_objects import Email
from app.infrastructure.persistence.mappers.user import to_entity, to_model
from app.infrastructure.persistence.models.user import UserModel


class SqlAlchemyUserRepository(UserRepository):
    """基于 SQLAlchemy 的用户仓储实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        model = to_model(user)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return to_entity(model)

    async def update(self, user: User) -> User:
        model = await self._session.get(UserModel, user.id)
        if model is None:
            return await self.add(user)

        model.email = str(user.email)
        model.display_name = user.display_name
        model.is_active = user.is_active
        await self._session.flush()
        await self._session.refresh(model)
        return to_entity(model)

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return to_entity(model) if model is not None else None

    async def get_by_email(self, email: Email) -> User | None:
        stmt = select(UserModel).where(func.lower(UserModel.email) == str(email))
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_entity(model) if model is not None else None

    async def list(self, *, offset: int = 0, limit: int = 20) -> list[User]:
        stmt = (
            select(UserModel)
            .order_by(UserModel.created_at.desc(), UserModel.id)
            .offset(offset)
            .limit(limit)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [to_entity(model) for model in models]

    async def delete(self, user_id: UUID) -> None:
        await self._session.execute(delete(UserModel).where(UserModel.id == user_id))
        await self._session.flush()
