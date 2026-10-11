"""身份上下文的领域异常。

只继承 domain 层的 DomainError，不引入任何框架依赖。
错误码沿用 core 规范：HTTP 状态码 × 100 + 同类序号（40901 → 409 类）。
命名遵循 ruff N818：异常类名以 Error 结尾。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError


class InvalidEmailError(DomainError):
    """邮箱格式不合法。"""

    def __init__(self, message: str = "邮箱格式不正确") -> None:
        super().__init__(42201, message)


class InvalidUsernameError(DomainError):
    """用户名不满足规则。"""

    def __init__(self, message: str = "用户名需为 3~50 位字母、数字、下划线或连字符") -> None:
        super().__init__(42202, message)


class WeakPasswordError(DomainError):
    """密码强度不足。"""

    def __init__(self, message: str = "密码强度不足") -> None:
        super().__init__(42203, message)


class EmailAlreadyRegisteredError(DomainError):
    """邮箱已被注册。"""

    def __init__(self, message: str = "该邮箱已被注册") -> None:
        super().__init__(40901, message)


class UsernameAlreadyTakenError(DomainError):
    """用户名已被占用。"""

    def __init__(self, message: str = "该用户名已被占用") -> None:
        super().__init__(40902, message)


class InvalidCredentialsError(DomainError):
    """邮箱或密码错误（登录失败统一提示，防用户名枚举）。"""

    def __init__(self, message: str = "邮箱或密码错误") -> None:
        super().__init__(40101, message)


class UserNotFoundError(DomainError):
    """用户不存在。"""

    def __init__(self, message: str = "用户不存在") -> None:
        super().__init__(40401, message)


class InactiveUserError(DomainError):
    """账号已停用。"""

    def __init__(self, message: str = "账号已被停用") -> None:
        super().__init__(40301, message)


__all__ = [
    "EmailAlreadyRegisteredError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidEmailError",
    "InvalidUsernameError",
    "UserNotFoundError",
    "UsernameAlreadyTakenError",
    "WeakPasswordError",
]
