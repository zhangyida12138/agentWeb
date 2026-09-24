from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.user.use_cases import UserUseCases
from app.core.database import get_session
from app.domain.user.repositories import UserRepository
from app.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_user_repository(session: SessionDep) -> UserRepository:
    return SqlAlchemyUserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_use_cases(repository: UserRepositoryDep) -> UserUseCases:
    return UserUseCases(repository)


UserUseCasesDep = Annotated[UserUseCases, Depends(get_user_use_cases)]
