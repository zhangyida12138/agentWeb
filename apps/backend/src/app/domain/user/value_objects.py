import re
from dataclasses import dataclass

from app.domain.user.exceptions import InvalidEmailError

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_LENGTH = 320


@dataclass(frozen=True, slots=True)
class Email:
    """邮箱值对象：在构造时完成归一化与校验，保证实体中始终是合法的邮箱。"""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if len(normalized) > _MAX_LENGTH or not _EMAIL_PATTERN.match(normalized):
            raise InvalidEmailError(self.value)
        object.__setattr__(self, "value", normalized)

    @property
    def domain(self) -> str:
        return self.value.split("@", 1)[1]

    def __str__(self) -> str:
        return self.value
