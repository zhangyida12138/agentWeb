"""用户管理接口：分页列表、查看 / 分配角色、重置密码。

这是本项目第一个**授权**（而不只是认证）的接口集合：
    每个端点都挂了 ``require_permission(...)``，没有权限的登录用户会拿到 403，
    未登录则仍旧是 401（认证归 ``get_current_user`` 管）。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from agent_web_shared.pagination import DEFAULT_LIMIT, MAX_LIMIT, normalize_pagination
from app.application.access.dto import AssignRolesCommand
from app.application.access.use_cases import (
    AssignRolesUseCase,
    ListUserRolesUseCase,
    ListUsersUseCase,
)
from app.application.identity.dto import ResetPasswordCommand
from app.application.identity.use_cases import ResetUserPasswordUseCase
from app.domain.access.entities import PermissionCode
from app.presentation.api.v1.schemas.access import (
    AssignRolesRequest,
    ResetPasswordRequest,
    RoleResponse,
    UserPageResponse,
    UserWithRolesResponse,
)
from app.presentation.api.v1.schemas.auth import UserResponse
from app.presentation.dependencies import (
    get_assign_roles_use_case,
    get_list_user_roles_use_case,
    get_list_users_use_case,
    get_reset_user_password_use_case,
    require_permission,
)

router = APIRouter(prefix="/users", tags=["access"])


@router.get(
    "",
    response_model=UserPageResponse,
    summary="用户列表（含角色）",
    dependencies=[Depends(require_permission(PermissionCode.USER_LIST))],
)
async def list_users(
    use_case: Annotated[ListUsersUseCase, Depends(get_list_users_use_case)],
    # 刻意不写 ge/le：越界值给 422 不如直接收敛。列表接口的调用方多半是
    # 「翻到第几页」这种拼出来的参数，为了一个 limit=1000 让整页报错，
    # 用户体验上不如返回 100 条。收敛口径统一由 shared 的 normalize_pagination 承担，
    # 前端另一处（或将来别的列表接口）也用同一个函数，行为不会漂移。
    offset: Annotated[int, Query(description="偏移量，负数按 0 处理")] = 0,
    limit: Annotated[int, Query(description=f"每页条数，上限 {MAX_LIMIT}")] = DEFAULT_LIMIT,
) -> UserPageResponse:
    """分页列出用户，并带上各自的角色码。

    ``safe_*`` 才是真正下发给用例的值；原样回填给响应，
    这样客户端能立刻看出「我传的 1000 被收敛成了 100」，而不是对着
    一个意外的总数发呆（例如用 limit 去算总页数就算错了）。
    """
    safe_offset, safe_limit = normalize_pagination(offset, limit)
    items, total = await use_case.execute(safe_offset, safe_limit)
    return UserPageResponse(
        items=[UserWithRolesResponse.model_validate(item) for item in items],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


@router.get(
    "/{user_id}/roles",
    response_model=list[RoleResponse],
    summary="查看某用户的角色",
    dependencies=[Depends(require_permission(PermissionCode.USER_LIST))],
)
async def list_user_roles(
    user_id: uuid.UUID,
    use_case: Annotated[ListUserRolesUseCase, Depends(get_list_user_roles_use_case)],
) -> list[RoleResponse]:
    """查看指定用户已分配的角色。

    ``user_id`` 声明成 ``uuid.UUID``：非法 UUID 由 FastAPI 在进入用例前拦下，
    再经全局 ``RequestValidationError`` 处理器统一转成
    ``400`` + 业务码 ``40000``（本项目所有参数校验错误都是这个组合，不是 422），
    用例里因此不必再写一遍「这个字符串像不像 UUID」。
    """
    roles = await use_case.execute(user_id)
    return [RoleResponse.model_validate(role) for role in roles]


@router.put(
    "/{user_id}/roles",
    response_model=list[RoleResponse],
    summary="分配用户角色",
    dependencies=[Depends(require_permission(PermissionCode.USER_ASSIGN_ROLES))],
)
async def assign_roles(
    user_id: uuid.UUID,
    payload: AssignRolesRequest,
    use_case: Annotated[AssignRolesUseCase, Depends(get_assign_roles_use_case)],
) -> list[RoleResponse]:
    """整体替换用户的角色集合。

    用 PUT 而不是 POST/PATCH：语义就是「把角色设成这一组」，
    幂等、可重放，重试一次不会把角色加两遍。

    返回替换后的完整角色列表（而不是 204）：管理后台保存完要立刻刷新勾选态，
    再发一次 GET 既慢又可能读到中间态（别的管理员刚改过）。
    """
    roles = await use_case.execute(
        user_id,
        AssignRolesCommand(role_codes=frozenset(payload.role_codes)),
    )
    return [RoleResponse.model_validate(role) for role in roles]


@router.put(
    "/{user_id}/password",
    response_model=UserResponse,
    summary="重置某用户的密码（管理员）",
    dependencies=[Depends(require_permission(PermissionCode.USER_RESET_PASSWORD))],
)
async def reset_user_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    use_case: Annotated[ResetUserPasswordUseCase, Depends(get_reset_user_password_use_case)],
) -> UserResponse:
    """把指定用户的密码直接改成新值，**不需要**旧密码。

    路径选 ``PUT /users/{id}/password`` 而不是复用 ``POST /auth/change-password``：
        那个接口的语义是「我改我自己的，旧密码是身份凭证」，
        它从 token 里取用户、并要求旧密码。管理员改别人的密码两个前提都不成立，
        硬塞进同一个 URL 只能靠「是不是带了 old_password」来分流，
        那就等于把权限判断藏在参数有无里——非常危险。
        分成两个端点后，各自的守卫写在各自的装饰器上，看一眼路由表就清楚谁能调。

    返回更新后的用户对象（而不是 204）：管理页刷新那一行时可以直接用返回值，
    少一次 GET，也避免读到别的管理员刚改过的中间态。

    响应体里**不含**密码相关字段（``UserResponse`` 根本没有），
    所以「重置成功」这件事无法从响应反推出密码，只能靠管理员自己记住。
    """
    user = await use_case.execute(
        user_id,
        ResetPasswordCommand(new_password=payload.new_password),
    )
    return UserResponse.model_validate(user)


__all__ = ["router"]
