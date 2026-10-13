"""权限上下文的仓储接口（端口）。

接口定义在 domain、实现在 infrastructure —— 依赖倒置的落点。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from uuid import UUID

from app.domain.access.entities import Permission, PermissionSpec, Role, RoleSpec


class AccessRepository(ABC):
    """角色 / 权限仓储接口。

    读多写少：除了种子同步与「分配角色」，其余都是查询。
    """

    # ────────────── 查询 ──────────────

    @abstractmethod
    async def list_roles(self) -> list[Role]:
        """列出全部角色（含各自权限码），按 code 排序。"""

    @abstractmethod
    async def list_permissions(self) -> list[Permission]:
        """列出全部权限点，按 code 排序。"""

    @abstractmethod
    async def get_role_by_code(self, code: str) -> Role | None:
        """按编码取角色。"""

    @abstractmethod
    async def get_roles_by_user(self, user_id: UUID) -> list[Role]:
        """取某个用户已分配的角色（含各自权限码）。"""

    @abstractmethod
    async def get_permission_codes(self, user_id: UUID) -> set[str]:
        """取某个用户的**权限码并集**（其所有角色权限的合并）。

        返回 set 而不是 list：守卫只关心「有没有」，
        集合的 ``in`` 是 O(1)，且天然去重（多个角色可能含同一权限）。
        """

    @abstractmethod
    async def get_role_codes_by_users(self, user_ids: Collection[UUID]) -> dict[UUID, set[str]]:
        """批量取若干用户的角色码（用户列表页用）。

        为什么不循环调 ``get_roles_by_user``：一页 20 个用户就是 20 次查询，
        典型的 N+1。列表接口必须一次查完。

        返回的映射**保证包含全部入参 user_id**（没有角色 → 空集合），
        调用方不必再写一段「缺失就补空」的兜底逻辑。
        """

    # ────────────── 写入 ──────────────

    @abstractmethod
    async def assign_roles(self, user_id: UUID, role_codes: Collection[str]) -> list[Role]:
        """**整体替换**某用户的角色集合，返回替换后的角色列表。

        语义定为「替换」而非「追加」：管理后台的交互是勾选一组角色后保存，
        替换语义与界面一一对应，并且天然幂等。
        任一编码不存在则整体失败（先校验后写入），绝不部分写入。
        """

    @abstractmethod
    async def sync_catalog(
        self,
        role_specs: Sequence[RoleSpec],
        permission_specs: Sequence[PermissionSpec],
    ) -> dict[str, int]:
        """按代码里的声明幂等地对齐角色与权限（供启动时的种子数据调用）。

        契约：**可反复执行**，第二次执行不得产生任何新行。
        """


__all__ = ["AccessRepository"]
