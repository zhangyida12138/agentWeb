"""身份上下文的值对象：构造即校验，保证领域内永远拿不到非法值。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.identity.exceptions import InvalidEmailError, InvalidUsernameError

# 长度上限是「领域校验 / 数据库列宽 / 表现层限制」的唯一来源。
# 三处共用同一组常量：否则改了域名规则却忘了改列宽，就会出现
# 「值对象放行、数据库截断」这类只在生产才暴露的错位。
EMAIL_MAX_LEN = 254  # RFC 5321 对邮箱 forward-path 的长度限制
USERNAME_MIN_LEN = 3
USERNAME_MAX_LEN = 32

# 邮箱只做「形状」校验，真正的可达性由验证邮件负责，领域层不越界
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(rf"^[A-Za-z0-9_-]{{{USERNAME_MIN_LEN},{USERNAME_MAX_LEN}}}$")


@dataclass(frozen=True, slots=True)
class Email:
    """邮箱值对象：构造时归一化（去空格 + 小写）并校验。"""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized:
            raise InvalidEmailError("邮箱不能为空")
        if len(normalized) > EMAIL_MAX_LEN:
            raise InvalidEmailError(f"邮箱长度不能超过 {EMAIL_MAX_LEN} 个字符")
        if not _EMAIL_RE.match(normalized):
            raise InvalidEmailError()
        # frozen=True 下必须走 object.__setattr__ 才能完成归一化
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Username:
    """用户名值对象：3~32 位字母/数字/下划线/连字符。

    不做大小写归一化——用户名要保留展示时的原始大小写，
    唯一性交给数据库上按原值建的唯一索引（``users.username``）。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not _USERNAME_RE.match(normalized):
            raise InvalidUsernameError(
                f"用户名需为 {USERNAME_MIN_LEN}~{USERNAME_MAX_LEN} 位字母、数字、下划线或连字符"
            )
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


__all__ = [
    "EMAIL_MAX_LEN",
    "USERNAME_MAX_LEN",
    "USERNAME_MIN_LEN",
    "Email",
    "Username",
]
