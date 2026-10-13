"""access 上下文的应用用例。

同时依赖两个上下文的**抽象**：
    ``AccessRepository``（角色 / 权限）与 ``UserRepository``（用户是否存在）。

「分配角色前先确认用户存在」为什么写在这里而不是仓储里：
    仓储只认识「角色表 / 用户角色表」，它没有立场替业务决定
    「给一个不存在的用户分配角色算不算错」。那是业务规则，属于应用层。
"""

from __future__ import annotations

from uuid import UUID

from app.application.access.dto import (
    AccessSummaryDTO,
    AssignRolesCommand,
    PermissionDTO,
    RoleDTO,
    UserWithRolesDTO,
)
from app.domain.access.repositories import AccessRepository
from app.domain.identity.exceptions import UserNotFoundError
from app.domain.identity.repositories import UserRepository


class GetMyAccessUseCase:
    """读取当前登录用户的角色码与权限码并集。"""

    def __init__(self, access: AccessRepository) -> None:
        self._access = access

    async def execute(self, user_id: UUID) -> AccessSummaryDTO:
        """两次查询，各司其职。

        ``permission_codes`` **刻意复用** ``get_permission_codes``，
        而不是把 ``get_roles_by_user`` 拿到的角色权限码在内存里求并集——
        后者能省一次查询，但会把「权限从哪来」这件事复制出第二份实现：
        将来若加入「直接授予单个用户某项权限」，内存里那份求并集的代码
        就会漏掉这条来源，前端于是拿着偏小的权限集把按钮藏起来，
        而接口其实是放行的。用与守卫同一个方法，两边**不可能**不一致。
        """
        roles = await self._access.get_roles_by_user(user_id)
        permissions = await self._access.get_permission_codes(user_id)
        return AccessSummaryDTO(
            role_codes=frozenset(role.code for role in roles),
            permission_codes=frozenset(permissions),
        )


class ListRolesUseCase:
    """列出全部角色及其权限码。"""

    def __init__(self, access: AccessRepository) -> None:
        self._access = access

    async def execute(self) -> list[RoleDTO]:
        roles = await self._access.list_roles()
        return [RoleDTO.from_entity(role) for role in roles]


class ListPermissionsUseCase:
    """列出全部权限点（前端渲染权限矩阵的其中一根坐标轴）。"""

    def __init__(self, access: AccessRepository) -> None:
        self._access = access

    async def execute(self) -> list[PermissionDTO]:
        permissions = await self._access.list_permissions()
        return [PermissionDTO.from_entity(permission) for permission in permissions]


class ListUserRolesUseCase:
    """查看某个用户已分配的角色。"""

    def __init__(self, users: UserRepository, access: AccessRepository) -> None:
        self._users = users
        self._access = access

    async def execute(self, user_id: UUID) -> list[RoleDTO]:
        # 先判用户存在，再查角色：用户不存在时返回空列表会被前端理解成
        # 「这个人没有角色」，这和「这个人根本不存在」是两件事，
        # 处理方式也完全不同（前者画空态，后者应该跳走）
        if await self._users.get_by_id(user_id) is None:
            raise UserNotFoundError()
        roles = await self._access.get_roles_by_user(user_id)
        return [RoleDTO.from_entity(role) for role in roles]


class ListUsersUseCase:
    """用户列表（含各自角色码），供管理后台。"""

    def __init__(self, users: UserRepository, access: AccessRepository) -> None:
        self._users = users
        self._access = access

    async def execute(self, offset: int, limit: int) -> tuple[list[UserWithRolesDTO], int]:
        """返回 ``(当页数据, 总数)``。

        查询数是固定的 3 条（count + 用户页 + 角色映射），与页大小无关——
        这是「批量取角色」存在的全部理由。
        """
        total = await self._users.count()
        page = await self._users.list_paged(offset, limit)
        if not page:
            # 没有数据就不必再查角色表；total 照样要回，前端靠它算总页数
            return [], total

        role_codes = await self._access.get_role_codes_by_users(
            [user.id for user in page if user.id is not None]
        )
        items: list[UserWithRolesDTO] = []
        for user in page:
            codes = role_codes.get(user.id, ()) if user.id is not None else ()
            items.append(UserWithRolesDTO.from_entity(user, codes))
        return items, total


class AssignRolesUseCase:
    """整体替换某用户的角色集合。"""

    def __init__(self, users: UserRepository, access: AccessRepository) -> None:
        self._users = users
        self._access = access

    async def execute(self, user_id: UUID, command: AssignRolesCommand) -> list[RoleDTO]:
        if await self._users.get_by_id(user_id) is None:
            raise UserNotFoundError()
        # 「编码是否存在」由仓储先校验后写入（见 AccessRepository.assign_roles 契约）。
        # 应用层不再查一遍角色表——同一条规则写两遍，早晚有一遍会漏
        roles = await self._access.assign_roles(user_id, command.role_codes)
        return [RoleDTO.from_entity(role) for role in roles]


__all__ = [
    "AssignRolesUseCase",
    "GetMyAccessUseCase",
    "ListPermissionsUseCase",
    "ListRolesUseCase",
    "ListUserRolesUseCase",
    "ListUsersUseCase",
]
