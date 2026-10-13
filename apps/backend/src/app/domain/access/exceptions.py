"""权限上下文的领域异常。

错误码沿用 core 规范：HTTP 状态码 × 100 + 同类序号。
identity 已占用 40010~40012 / 40110~40111 / 40310 / 40410 / 40910~40911，
这里从 40320 / 40420 / 40920 起编号，避免撞码。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError


class PermissionDeniedError(DomainError):
    """当前用户缺少执行该操作所需的权限。

    把缺失的权限码放进 data.permission：前端可以据此提示
    「需要 xxx 权限」，而不用把后端的权限矩阵抄一份到前端。
    """

    def __init__(
        self,
        permission: str | None = None,
        message: str = "没有执行该操作的权限",
    ) -> None:
        super().__init__(40320, message, {"permission": permission} if permission else None)


class RoleNotFoundError(DomainError):
    """角色不存在。"""

    def __init__(self, message: str = "角色不存在") -> None:
        super().__init__(40420, message)


class RoleCodeTakenError(DomainError):
    """角色编码已被占用。"""

    def __init__(self, message: str = "该角色编码已存在") -> None:
        super().__init__(40920, message)


__all__ = ["PermissionDeniedError", "RoleCodeTakenError", "RoleNotFoundError"]
