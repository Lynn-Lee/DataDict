from typing import Any

import pytest

from app.core.config import Settings
from app.core.exceptions import UnauthenticatedError
from app.core.security import create_access_token, hash_password
from app.services.auth import AuthService

_SECRET = "auth_service_test_secret_key_min_32_chars"


def _settings() -> Settings:
    return Settings(
        DB_URL_WEB="postgresql+asyncpg://datadict_web:pw@localhost:5432/datadict",
        DB_URL_COLLECTOR="postgresql+asyncpg://datadict_collector:pw@localhost:5432/datadict",
        REDIS_URL="redis://localhost:6379/0",
        CREDENTIAL_SECRET_KEY="credential_secret_key_at_least_32_chars_x",
        JWT_SECRET_KEY=_SECRET,
        JWT_EXPIRE_MINUTES=60,
    )


class FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row


class FakeSession:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def execute(self, statement: object, parameters: object | None = None) -> FakeResult:
        del statement, parameters
        return FakeResult(self._row)


def _user_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 7,
        "username": "lynn",
        "real_name": "Lynn",
        "email": "lynn@example.com",
        "enabled": True,
        "password_hash": hash_password("correct-horse"),
    }
    row.update(overrides)
    return row


async def test_login_success_returns_token() -> None:
    service = AuthService(settings=_settings())
    token_response = await service.login(
        FakeSession(_user_row()), username="lynn", password="correct-horse"
    )
    assert token_response.token_type == "bearer"
    assert token_response.expires_in == 60 * 60
    assert token_response.access_token


async def test_login_wrong_password_is_unauthenticated() -> None:
    service = AuthService(settings=_settings())
    with pytest.raises(UnauthenticatedError):
        await service.login(FakeSession(_user_row()), username="lynn", password="nope")


async def test_login_unknown_user_is_unauthenticated() -> None:
    service = AuthService(settings=_settings())
    with pytest.raises(UnauthenticatedError):
        await service.login(FakeSession(None), username="ghost", password="whatever")


async def test_login_disabled_user_is_unauthenticated() -> None:
    service = AuthService(settings=_settings())
    with pytest.raises(UnauthenticatedError):
        await service.login(
            FakeSession(_user_row(enabled=False)), username="lynn", password="correct-horse"
        )


async def test_login_user_without_password_is_unauthenticated() -> None:
    service = AuthService(settings=_settings())
    with pytest.raises(UnauthenticatedError):
        await service.login(
            FakeSession(_user_row(password_hash=None)), username="lynn", password="correct-horse"
        )


async def test_current_user_from_valid_token() -> None:
    service = AuthService(settings=_settings())
    token = create_access_token("7", secret_key=_SECRET, expires_minutes=60)
    current = await service.current_user(FakeSession(_user_row()), token=token)
    assert current.id == 7
    assert current.username == "lynn"


async def test_current_user_rejects_invalid_token() -> None:
    service = AuthService(settings=_settings())
    with pytest.raises(UnauthenticatedError):
        await service.current_user(FakeSession(_user_row()), token="not-a-jwt")


async def test_current_user_rejects_disabled_user() -> None:
    service = AuthService(settings=_settings())
    token = create_access_token("7", secret_key=_SECRET, expires_minutes=60)
    with pytest.raises(UnauthenticatedError):
        await service.current_user(FakeSession(_user_row(enabled=False)), token=token)
