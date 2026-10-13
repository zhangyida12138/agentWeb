"""identity 上下文的应用层：用例编排 + DTO。

依赖方向（只允许向内）：
    application → domain（实体、值对象、仓储接口、领域异常）
    application → shared（密码哈希、JWT 这类无状态工具）

**不得**出现 FastAPI / SQLAlchemy 的 import：
    事务边界归 ``core/database.py`` 的 ``get_db``，HTTP 语义归表现层与全局异常处理器。
"""

from app.application.identity.dto import (
    UNSET,
    AuthResultDTO,
    ChangePasswordCommand,
    LoginCommand,
    RegisterCommand,
    TokenDTO,
    Unset,
    UpdateProfileCommand,
    UserDTO,
)
from app.application.identity.use_cases import (
    ChangePasswordUseCase,
    GetCurrentUserUseCase,
    LoginUserUseCase,
    RegisterUserUseCase,
    TokenConfig,
    UpdateProfileUseCase,
)

__all__ = [
    "UNSET",
    "AuthResultDTO",
    "ChangePasswordCommand",
    "ChangePasswordUseCase",
    "GetCurrentUserUseCase",
    "LoginCommand",
    "LoginUserUseCase",
    "RegisterCommand",
    "RegisterUserUseCase",
    "TokenConfig",
    "TokenDTO",
    "Unset",
    "UpdateProfileCommand",
    "UpdateProfileUseCase",
    "UserDTO",
]
