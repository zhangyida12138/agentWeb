from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.application.user.dto import CreateUserCommand, ListUsersQuery, UpdateUserCommand
from app.presentation.api.v1.schemas.user import (
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.presentation.dependencies import UserUseCasesDep

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreateRequest, use_cases: UserUseCasesDep) -> UserResponse:
    dto = await use_cases.create_user(
        CreateUserCommand(email=str(payload.email), display_name=payload.display_name)
    )
    return UserResponse.model_validate(dto)


@router.get("", response_model=list[UserResponse])
async def list_users(
    use_cases: UserUseCasesDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[UserResponse]:
    dtos = await use_cases.list_users(ListUsersQuery(offset=offset, limit=limit))
    return [UserResponse.model_validate(dto) for dto in dtos]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: UUID, use_cases: UserUseCasesDep) -> UserResponse:
    return UserResponse.model_validate(await use_cases.get_user(user_id))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID, payload: UserUpdateRequest, use_cases: UserUseCasesDep
) -> UserResponse:
    dto = await use_cases.update_user(
        user_id,
        UpdateUserCommand(display_name=payload.display_name, is_active=payload.is_active),
    )
    return UserResponse.model_validate(dto)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: UUID, use_cases: UserUseCasesDep) -> None:
    await use_cases.delete_user(user_id)
