"""``AccessRepository`` 的 SQLAlchemy 实现。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import Permission, PermissionSpec, Role, RoleSpec
from app.domain.access.exceptions import RoleNotFoundError
from app.domain.access.repositories import AccessRepository
from app.infrastructure.persistence.mappers.access import (
    permission_to_entity,
    role_to_entity,
)
from app.infrastructure.persistence.models.permission import PermissionModel
from app.infrastructure.persistence.models.role import RoleModel
from app.infrastructure.persistence.models.role_permission import RolePermissionModel
from app.infrastructure.persistence.models.user_role import UserRoleModel


class SqlAccessRepository(AccessRepository):
    """基于 ``AsyncSession`` 的仓储实现。

    同样遵守两条铁律：**不 commit**（事务归 ``get_db``）、**不吞异常**。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────── 查询 ──────────────

    async def list_roles(self) -> list[Role]:
        models = (
            (await self._session.execute(select(RoleModel).order_by(RoleModel.code)))
            .scalars()
            .all()
        )
        codes_by_role = await self._permission_codes_of_roles(None)
        return [role_to_entity(m, codes_by_role.get(m.id, ())) for m in models]

    async def list_permissions(self) -> list[Permission]:
        models = (
            (await self._session.execute(select(PermissionModel).order_by(PermissionModel.code)))
            .scalars()
            .all()
        )
        return [permission_to_entity(m) for m in models]

    async def get_role_by_code(self, code: str) -> Role | None:
        model = (
            await self._session.execute(select(RoleModel).where(RoleModel.code == code))
        ).scalar_one_or_none()
        if model is None:
            return None
        codes_by_role = await self._permission_codes_of_roles([model.id])
        return role_to_entity(model, codes_by_role.get(model.id, ()))

    async def get_roles_by_user(self, user_id: UUID) -> list[Role]:
        models = (
            (
                await self._session.execute(
                    select(RoleModel)
                    .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
                    .where(UserRoleModel.user_id == user_id)
                    .order_by(RoleModel.code)
                )
            )
            .scalars()
            .all()
        )
        codes_by_role = await self._permission_codes_of_roles([m.id for m in models])
        return [role_to_entity(m, codes_by_role.get(m.id, ())) for m in models]

    async def get_permission_codes(self, user_id: UUID) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(PermissionModel.code)
                    .join(
                        RolePermissionModel,
                        RolePermissionModel.permission_id == PermissionModel.id,
                    )
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RolePermissionModel.role_id,
                    )
                    .where(UserRoleModel.user_id == user_id)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    async def get_role_codes_by_users(self, user_ids: Collection[UUID]) -> dict[UUID, set[str]]:
        if not user_ids:
            # 空 in_ 在 PG 上是合法的，但没必要白跑一次查询
            return {}
        # 预置全部 key 为空集合：见接口契约，调用方拿到的一定是完整映射
        result: dict[UUID, set[str]] = {user_id: set() for user_id in set(user_ids)}
        rows = (
            await self._session.execute(
                select(UserRoleModel.user_id, RoleModel.code)
                .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                .where(UserRoleModel.user_id.in_(result.keys()))
            )
        ).all()
        for user_id, code in rows:
            result[user_id].add(code)
        return result

    # ────────────── 写入 ──────────────

    async def assign_roles(self, user_id: UUID, role_codes: Collection[str]) -> list[Role]:
        wanted = set(role_codes)
        if wanted:
            found = (
                (await self._session.execute(select(RoleModel).where(RoleModel.code.in_(wanted))))
                .scalars()
                .all()
            )
            missing = wanted - {m.code for m in found}
            if missing:
                # 先校验后写入：不认识的编码直接整体失败，绝不写一半
                raise RoleNotFoundError(f"角色不存在：{', '.join(sorted(missing))}")
        else:
            found = []

        # 先清后插 = 替换语义，且天然幂等
        await self._session.execute(delete(UserRoleModel).where(UserRoleModel.user_id == user_id))
        for model in found:
            self._session.add(UserRoleModel(user_id=user_id, role_id=model.id))
        await self._session.flush()

        ordered = sorted(found, key=lambda m: m.code)
        codes_by_role = await self._permission_codes_of_roles([m.id for m in ordered])
        return [role_to_entity(m, codes_by_role.get(m.id, ())) for m in ordered]

    async def sync_catalog(
        self,
        role_specs: Sequence[RoleSpec],
        permission_specs: Sequence[PermissionSpec],
    ) -> dict[str, int]:
        created_permissions = await self._sync_permissions(permission_specs)
        created_roles = await self._sync_roles(role_specs)
        relinked = await self._sync_role_permissions(role_specs)
        await self._session.flush()
        return {
            "permissions_created": created_permissions,
            "roles_created": created_roles,
            "role_permissions_relinked": relinked,
        }

    # ────────────── 内部辅助 ──────────────

    async def _sync_permissions(self, specs: Sequence[PermissionSpec]) -> int:
        """补建缺失的权限点，并刷新已存在权限点的展示信息。"""
        existing = {
            m.code: m
            for m in (await self._session.execute(select(PermissionModel))).scalars().all()
        }
        created = 0
        for spec in specs:
            model = existing.get(spec.code)
            if model is None:
                # id 必须显式传：IDMixin 是 MappedAsDataclass，而 id 的 uuid4 只挂在
                # Column 的 insert_default 上——insert_default 不参与 dataclass 的构造器
                # 签名（这正是 base.py 里「用 insert_default 而不是 default」那条注释的
                # 另一半代价：换来了「id 无默认值」，因此这里必须自己生成标识）。
                self._session.add(
                    PermissionModel(
                        id=uuid4(),
                        code=spec.code,
                        name=spec.name,
                        description=spec.description,
                    )
                )
                created += 1
            else:
                # 只刷新展示信息，不动 code —— code 是身份，改了就等于换了个权限点
                model.name = spec.name
                model.description = spec.description
        # 必须先 flush：后面 _sync_role_permissions 要靠新权限点的 id 建关联
        await self._session.flush()
        return created

    async def _sync_roles(self, specs: Sequence[RoleSpec]) -> int:
        existing = {
            m.code: m for m in (await self._session.execute(select(RoleModel))).scalars().all()
        }
        created = 0
        for spec in specs:
            model = existing.get(spec.code)
            if model is None:
                # 同 _sync_permissions：id 由调用方生成，见那里的说明
                self._session.add(
                    RoleModel(
                        id=uuid4(),
                        code=spec.code,
                        name=spec.name,
                        description=spec.description,
                    )
                )
                created += 1
            else:
                model.name = spec.name
                model.description = spec.description
        # 同样先 flush：下一步要靠新角色的 id
        await self._session.flush()
        return created

    async def _sync_role_permissions(self, specs: Sequence[RoleSpec]) -> int:
        """对齐「角色 → 权限」绑定。

        刻意**不删除**声明之外的旧角色：那会把运维手工建的角色连同用户的角色绑定
        一起抹掉。这里只保证「声明里有的都对」，不做减法。
        """
        role_ids = {
            m.code: m.id for m in (await self._session.execute(select(RoleModel))).scalars().all()
        }
        permission_ids = {
            m.code: m.id
            for m in (await self._session.execute(select(PermissionModel))).scalars().all()
        }

        # 一次查出全部既有绑定，避免「逐角色查一次」的 N+1
        current: dict[UUID, set[UUID]] = defaultdict(set)
        for role_id, permission_id in (
            await self._session.execute(
                select(RolePermissionModel.role_id, RolePermissionModel.permission_id)
            )
        ).all():
            current[role_id].add(permission_id)

        changed = 0
        for spec in specs:
            role_id = role_ids.get(spec.code)
            if role_id is None:  # pragma: no cover - 上面的 _sync_roles 已保证存在
                continue
            desired = {permission_ids[c] for c in spec.permissions if c in permission_ids}
            if current.get(role_id, set()) == desired:
                # 已对齐 → 一条写入都不发。这是「重复执行无副作用」的关键
                continue
            await self._session.execute(
                delete(RolePermissionModel).where(RolePermissionModel.role_id == role_id)
            )
            for permission_id in desired:
                self._session.add(RolePermissionModel(role_id=role_id, permission_id=permission_id))
            changed += 1
        return changed

    async def _permission_codes_of_roles(
        self, role_ids: Collection[UUID] | None
    ) -> dict[UUID, set[str]]:
        """取若干角色的权限码。``None`` 表示取全部。"""
        if role_ids is not None and not role_ids:
            return {}
        stmt = select(RolePermissionModel.role_id, PermissionModel.code).join(
            PermissionModel, PermissionModel.id == RolePermissionModel.permission_id
        )
        if role_ids is not None:
            stmt = stmt.where(RolePermissionModel.role_id.in_(role_ids))
        result: dict[UUID, set[str]] = defaultdict(set)
        for role_id, code in (await self._session.execute(stmt)).all():
            result[role_id].add(code)
        return result


__all__ = ["SqlAccessRepository"]
