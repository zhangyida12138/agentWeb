from app.domain.user.entities import User
from app.domain.user.value_objects import Email
from app.infrastructure.persistence.models.user import UserModel


def to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        email=Email(model.email),
        display_name=model.display_name,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=str(user.email),
        display_name=user.display_name,
        is_active=user.is_active,
    )
