"""身份上下文的领域异常。

只继承 domain 层的 DomainError，不引入任何框架依赖。
错误码沿用 core 规范：HTTP 状态码 × 100 + 同类序号（40910 → 409 类第 10 号）。
带 field 的异常会把出错字段放进 data，前端据此把错误定位到具体输入框。
命名遵循 ruff N818：异常类名以 Error 结尾。
"""

from __future__ import annotations

from app.domain.exceptions import DomainError

# ──────────────────────────── 400 · 入参非法 ────────────────────────────
# 值对象构造失败时抛这些，保证领域内永远不存在非法值


class InvalidEmailError(DomainError):
    """邮箱格式不合法。"""

    def __init__(self, message: str = "邮箱格式不正确") -> None:
        super().__init__(40010, message, {"field": "email"})


class InvalidUsernameError(DomainError):
    """用户名不满足规则。"""

    def __init__(self, message: str = "用户名需为 3~32 位字母、数字、下划线或连字符") -> None:
        super().__init__(40011, message, {"field": "username"})


class WeakPasswordError(DomainError):
    """密码不满足规则。

    两种触发场景：
        ① 值对象/实体收到的是明文而不是哈希（长度兜底）；
        ② bcrypt 的输入是**字节**维度上限 72——表现层只能数「字符数」，
           「30 个汉字」看着合规、实际 90 字节，hash 时直接抛 ValueError。
    """

    def __init__(self, message: str = "密码强度不足") -> None:
        super().__init__(40012, message, {"field": "password"})


# ──────────────────────────── 401 · 认证失败 ────────────────────────────


class InvalidCredentialsError(DomainError):
    """邮箱或密码错误（登录失败统一提示，防用户名枚举）。"""

    def __init__(self, message: str = "邮箱或密码错误") -> None:
        super().__init__(40110, message)


class TokenInvalidError(DomainError):
    """token 缺失、签名不符、已过期，或 token 里的用户已不存在。"""

    def __init__(self, message: str = "登录状态无效或已过期") -> None:
        super().__init__(40111, message)


# ──────────────────────────── 403 · 禁止访问 ────────────────────────────


class InactiveUserError(DomainError):
    """账号已停用。"""

    def __init__(self, message: str = "账号已被停用") -> None:
        super().__init__(40310, message)


# ──────────────────────────── 404 · 资源不存在 ────────────────────────────


class UserNotFoundError(DomainError):
    """用户不存在。"""

    def __init__(self, message: str = "用户不存在") -> None:
        super().__init__(40410, message)


# ──────────────────────────── 409 · 唯一约束冲突 ────────────────────────────
# 用例层的「先查重」只能给出友好提示，并发下仍可能双写；
# 这两个同时也是数据库唯一索引报错后的翻译目标（见 SqlUserRepository）


class EmailAlreadyRegisteredError(DomainError):
    """邮箱已被注册。"""

    def __init__(self, message: str = "该邮箱已被注册") -> None:
        super().__init__(40910, message, {"field": "email"})


class UsernameAlreadyTakenError(DomainError):
    """用户名已被占用。"""

    def __init__(self, message: str = "该用户名已被占用") -> None:
        super().__init__(40911, message, {"field": "username"})


__all__ = [
    "EmailAlreadyRegisteredError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidEmailError",
    "InvalidUsernameError",
    "TokenInvalidError",
    "UserNotFoundError",
    "UsernameAlreadyTakenError",
    "WeakPasswordError",
]
