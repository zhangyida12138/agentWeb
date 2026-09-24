import pytest

from app.domain.user.entities import User
from app.domain.user.exceptions import InvalidEmailError, InvalidUserNameError
from app.domain.user.value_objects import Email


def test_email_normalizes_case_and_whitespace() -> None:
    email = Email("  Alice@Example.COM ")

    assert email.value == "alice@example.com"
    assert email.domain == "example.com"


@pytest.mark.parametrize("raw", ["", "not-an-email", "a@b", "a b@example.com"])
def test_email_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        Email(raw)


def test_register_creates_active_user() -> None:
    user = User.register(email="alice@example.com", display_name="  Alice  ")

    assert user.display_name == "Alice"
    assert user.is_active is True
    assert str(user.email) == "alice@example.com"


def test_register_rejects_blank_name() -> None:
    with pytest.raises(InvalidUserNameError):
        User.register(email="alice@example.com", display_name="   ")


def test_deactivate_and_activate_toggle_state() -> None:
    user = User.register(email="alice@example.com", display_name="Alice")

    user.deactivate()
    assert user.is_active is False

    user.activate()
    assert user.is_active is True
