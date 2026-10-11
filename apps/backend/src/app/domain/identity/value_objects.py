"""身份上下文的值对象：构造即校验，保证领域内永远拿不到非法值。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.identity.exceptions import InvalidEmailError, InvalidUsernameError

# 邮箱只做「形状」校验，真正的可达性由验证邮件负责，领域层不越界
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,50}$")


@dataclass(frozen=True, slots=True)
class Email:
    """邮箱值对象：构造时归一化（去空格 + 小写）并校验。"""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise InvalidEmailError()
        # frozen=True 下必须走 object.__setattr__ 才能完成归一化
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Username:
    """用户名值对象：3~50 位字母/数字/下划线/连字符。"""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not _USERNAME_RE.match(normalized):
            raise InvalidUsernameError()
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


__all__ = ["Email", "Username"]
