"""角色与权限点查询接口（只读）。

放在一个文件里：两个端点共用同一个授权要求（``role:list``）、同一份种子数据，
拆开只会让人以为它们的可见性规则不一样。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.access.use_cases import ListPermissionsUseCase, ListRolesUseCase
from app.domain.access.entities import PermissionCode
from app.presentation.api.v1.schemas.access import PermissionResponse, RoleResponse
from app.presentation.dependencies import (
    get_list_permissions_use_case,
    get_list_roles_use_case,
    require_permission,
)

router = APIRouter(prefix="/roles", tags=["access"])


# 路径写 "" 而不是 "/"：后者会生成 "/api/v1/roles/"，客户端访问 "/api/v1/roles"
# 时先吃一个 307 跳转。虽然浏览器会跟，但 curl / httpx 默认不跟，白白多一次往返。
@router.get(
    "",
    response_model=list[RoleResponse],
    summary="角色列表",
    dependencies=[Depends(require_permission(PermissionCode.ROLE_LIST))],
)
async def list_roles(
    use_case: Annotated[ListRolesUseCase, Depends(get_list_roles_use_case)],
) -> list[RoleResponse]:
    """列出全部角色及其权限码。

    权限通过 ``dependencies=[...]`` 挂载而不是写成参数：这个接口不需要当前用户是谁，
    挂了守卫就够了。写成参数反而要在函数体里凭空写一行 ``_ = current_user`` 应付 linter。
    """
    roles = await use_case.execute()
    return [RoleResponse.model_validate(role) for role in roles]


@router.get(
    "/permissions",
    response_model=list[PermissionResponse],
    summary="权限点列表",
    dependencies=[Depends(require_permission(PermissionCode.ROLE_LIST))],
)
async def list_permissions(
    use_case: Annotated[ListPermissionsUseCase, Depends(get_list_permissions_use_case)],
) -> list[PermissionResponse]:
    """列出全部权限点。

    权限矩阵 = 「角色列表」×「权限点列表」，前端分别取这两份数据做叉乘；
    后端不返回拼好的矩阵，因为矩阵随角色增删而变，缓存和失效只会更麻烦。
    """
    permissions = await use_case.execute()
    return [PermissionResponse.model_validate(permission) for permission in permissions]


__all__ = ["router"]
