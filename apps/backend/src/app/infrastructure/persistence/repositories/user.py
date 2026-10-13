"""``UserRepository`` 的 SQLAlchemy 实现。"""

from __future__ import annotations

import uuid
from typing import NoReturn

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity.entities import User
from app.domain.identity.exceptions import (
    EmailAlreadyRegisteredError,
    UsernameAlreadyTakenError,
    UserNotFoundError,
)
from app.domain.identity.repositories import UserRepository
from app.domain.identity.value_objects import Email, Username
from app.infrastructure.persistence.mappers.user import (
    apply_to_model,
    to_entity,
    to_model,
)
from app.infrastructure.persistence.models.user import UserModel

# PostgreSQL SQLSTATE：唯一约束冲突（unique_violation）
PG_UNIQUE_VIOLATION = "23505"


def _sqlstate(exc: IntegrityError) -> str | None:
    """从 ``IntegrityError`` 里挖出 PG 的 SQLSTATE。

    asyncpg 方言把驱动层异常挂在 ``exc.orig`` 上，SQLSTATE 是它的 ``pgcode`` / ``sqlstate``
    属性；而它自己的 ``__cause__``（``asyncpg.exceptions.UniqueViolationError``）
    反而没有这两个属性，所以必须取 ``exc.orig``，不能顺着 ``__cause__`` 找。
    """
    orig = exc.orig
    return getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)


def _raise_translated(exc: IntegrityError) -> NoReturn:
    """把唯一约束冲突翻译成领域异常后抛出。

    不翻译的话，application 层就得 ``import sqlalchemy`` 才能判断「这是什么错误」，
    分层立刻破功。翻译之后，用例只认识 ``DomainError``，HTTP 语义交给全局处理器。
    """
    if _sqlstate(exc) != PG_UNIQUE_VIOLATION:
        # 外键 / 非空 / 长度超限等不属于这条写路径的预期，原样抛出交给全局兜底
        raise exc

    # asyncpg 把被违反的索引名放进 constraint_name（本表是 ix_users_email / ix_users_username）
    constraint = (getattr(exc.orig, "constraint_name", None) or "").lower()
    if "email" in constraint:
        raise EmailAlreadyRegisteredError() from exc
    if "username" in constraint:
        raise UsernameAlreadyTakenError() from exc
    # 认不出的唯一约束：不猜语义，交给全局的 IntegrityError 兜底处理器
    raise exc


class SqlUserRepository(UserRepository):
    """基于 ``AsyncSession`` 的仓储实现。

    只做一件事：把领域语义翻译成 SQL。因此
      - **不 commit** —— 事务边界由 ``core/database.py`` 的 ``get_db`` 独占；
      - **不吞异常** —— 技术异常翻译成领域异常后立刻抛出，绝不静默继续。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        model = to_model(user)
        self._session.add(model)
        try:
            # 见接口契约：这里的 flush 是关键，把唯一约束冲突从 commit 阶段提前到响应之前
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)
        return to_entity(model)

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return to_entity(model) if model is not None else None

    async def get_by_email(self, email: Email) -> User | None:
        # 直接取 .value：邮箱的大小写/空格归一化是值对象的职责，
        # 仓储不重复实现一遍——两处各写一遍，早晚会有一处忘记小写，
        # 表现为「注册能过、登录失败」这种只在特定输入下出现的怪 bug。
        stmt = select(UserModel).where(UserModel.email == email.value)
        return await self._one(stmt)

    async def get_by_username(self, username: Username) -> User | None:
        stmt = select(UserModel).where(UserModel.username == username.value)
        return await self._one(stmt)

    async def update(self, user: User) -> User:
        if user.id is None:
            raise UserNotFoundError()
        model = await self._session.get(UserModel, user.id)
        if model is None:
            # 实体带着一个库里不存在的 id：多半是被并发删掉了，按「不存在」处理
            raise UserNotFoundError()
        apply_to_model(user, model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            _raise_translated(exc)
        return to_entity(model)

    async def _one(self, stmt: Select[tuple[UserModel]]) -> User | None:
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_entity(model) if model is not None else None

    async def list_paged(self, offset: int, limit: int) -> list[User]:
        # 次序键里带上 id：同一批插入的行 created_at 可能完全相同，
        # 只按 created_at 排序时 PG 不保证稳定顺序，
        # 表现为「翻页时某行出现两次、另一行永远看不到」
        stmt = (
            select(UserModel)
            .order_by(UserModel.created_at.desc(), UserModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [to_entity(model) for model in models]

    async def count(self) -> int:
        # select(func.count()).select_from(...) 生成 count(*)，不必判空值列
        stmt = select(func.count()).select_from(UserModel)
        return (await self._session.execute(stmt)).scalar_one()


__all__ = ["PG_UNIQUE_VIOLATION", "SqlUserRepository"]
