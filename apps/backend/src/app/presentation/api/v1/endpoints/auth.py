"""认证接口：注册 / 登录 / 当前用户 / 改资料 / 改密码。

表现层只做三件事，多一件都不该做：
    ① 收参数（schema 校验）、② 转调用例、③ 把 DTO 转成响应模型。
任何 if/else 形式的业务判断出现在这里，都是分层漏了。

响应信封由 ``ResponseWrapperMiddleware`` 统一加，所以这些 handler 直接返回
业务对象即可，不要去手包 ``{code,data,message}``。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.application.access.use_cases import GetMyAccessUseCase
from app.application.identity.dto import (
    ChangePasswordCommand,
    LoginCommand,
    RegisterCommand,
    UpdateProfileCommand,
)
from app.application.identity.use_cases import (
    ChangePasswordUseCase,
    GetCurrentUserUseCase,
    LoginUserUseCase,
    RegisterUserUseCase,
    UpdateProfileUseCase,
)
from app.core.exceptions import success_response
from app.presentation.api.v1.schemas.access import AccessSummaryResponse
from app.presentation.api.v1.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.presentation.dependencies import (
    CurrentUser,
    get_change_password_use_case,
    get_current_user_use_case,
    get_login_use_case,
    get_my_access_use_case,
    get_register_use_case,
    get_update_profile_use_case,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册",
)
async def register(
    payload: RegisterRequest,
    use_case: Annotated[RegisterUserUseCase, Depends(get_register_use_case)],
) -> UserResponse:
    """注册新用户。

    注册**不**直接签发 token：注册与登录是两件事，让客户端显式走一次登录，
    「拿到 token」这件事就永远只有一个来源，前端登录态的实现也少一条分支。
    """
    user = await use_case.execute(
        RegisterCommand(
            email=payload.email,
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=AuthResponse, summary="登录")
async def login(
    payload: LoginRequest,
    use_case: Annotated[LoginUserUseCase, Depends(get_login_use_case)],
) -> AuthResponse:
    """登录并签发 access token。

    邮箱不存在、密码错误、账号被禁用，都会以领域异常返回（401/403），
    由全局处理器翻译成带业务码的信封。
    """
    result = await use_case.execute(LoginCommand(email=payload.email, password=payload.password))
    return AuthResponse.model_validate(result)


@router.get("/me", response_model=UserResponse, summary="当前用户")
async def get_me(
    current_user: CurrentUser,
    use_case: Annotated[GetCurrentUserUseCase, Depends(get_current_user_use_case)],
) -> UserResponse:
    """读取当前登录用户。

    ``current_user`` 看起来只是被「用了一下 id」，但它承担的是守卫职责：
    它已经完成了解 token、查用户、查禁用三件事。去掉它这个接口就变成公开接口了。
    """
    return UserResponse.model_validate(await use_case.execute(current_user.id))


@router.get(
    "/me/access",
    response_model=AccessSummaryResponse,
    summary="当前用户的角色与权限",
)
async def get_my_access(
    current_user: CurrentUser,
    use_case: Annotated[GetMyAccessUseCase, Depends(get_my_access_use_case)],
) -> AccessSummaryResponse:
    """读取当前登录用户的角色码与权限码并集，供前端渲染管理入口。

    为什么把角色/权限**单独**开一个端点，而不是并进 ``/auth/me``：
        ① ``UserResponse`` 是注册、登录、改资料三处共用的用户视图。往里加角色，
           identity 上下文就被迫去依赖 access 上下文的角色表——而 access 本来
           是依赖 identity 的（要查用户），两个方向一串就成了循环依赖。
        ② 登录页根本不需要权限，让它白拿一份角色数据没有意义。
        ③ 权限会变（管理员刚给你加了角色）。独立端点能被单独失效/重取，
           而 ``auth/me`` 的缓存有效期通常更长。

    前端拿它做「显不显示按钮」的判断，用它跟后端守卫对齐：
        判断依据是 ``permission_codes`` 里有没有某个权限码，
        不是「role_codes 里有没有 admin」。角色名是给人看的，
        权限码才是接口真正校验的东西。
    """
    return AccessSummaryResponse.model_validate(await use_case.execute(current_user.id))


@router.patch("/me", response_model=UserResponse, summary="修改资料")
async def update_me(
    payload: UpdateProfileRequest,
    current_user: CurrentUser,
    use_case: Annotated[UpdateProfileUseCase, Depends(get_update_profile_use_case)],
) -> UserResponse:
    """按 PATCH 语义修改资料。

    ``exclude_unset=True`` 是这里的关键：
        它让「没传的字段」在 command 里保持 UNSET，用例据此跳过；
        若换成 ``exclude_none=True``，客户端就无法表达「把签名清空」——
        ``null`` 会被当成「没传」丢掉。
    """
    command = UpdateProfileCommand(**payload.model_dump(exclude_unset=True))
    return UserResponse.model_validate(await use_case.execute(current_user.id, command))


@router.post("/change-password", summary="修改密码")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    use_case: Annotated[ChangePasswordUseCase, Depends(get_change_password_use_case)],
) -> dict:
    """修改密码。

    返回 200 + 空 data 而不是 204：204 按规范不能带响应体，
    而本项目的响应信封中间件会把空 body 也包成 ``{code,data,message}``，
    两者凑在一起就是一个字段齐全但没有 body 的非法 204。
    """
    await use_case.execute(
        current_user.id,
        ChangePasswordCommand(
            old_password=payload.old_password,
            new_password=payload.new_password,
        ),
    )
    # 显式构造信封：中间件识别到已是信封就原样返回，顺带把提示语换成有意义的文案
    return success_response(message="密码修改成功")


__all__ = ["router"]
