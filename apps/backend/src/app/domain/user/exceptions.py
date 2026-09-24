from app.domain.exceptions import DomainError


class InvalidEmailError(DomainError):
    def __init__(self, value: str) -> None:
        super().__init__(f"无效的邮箱地址: {value!r}")
        self.value = value


class InvalidUserNameError(DomainError):
    pass
