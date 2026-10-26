import os
from collections.abc import Iterator

import pytest

_DEFAULT_ENV = {
    "DB_URL_WEB": "postgresql+asyncpg://datadict_web:test@localhost:15432/datadict",
    "DB_URL_COLLECTOR": "postgresql+asyncpg://datadict_collector:test@localhost:15432/datadict",
    "REDIS_URL": "redis://localhost:16379/0",
    "CREDENTIAL_SECRET_KEY": "test_only_secret_key_at_least_32_chars_x",
    "JWT_SECRET_KEY": "test_only_jwt_secret_key_at_least_32_chars",
}


@pytest.fixture(autouse=True, scope="session")
def _default_env() -> Iterator[None]:
    """为不依赖真实数据库的测试提供最小可用配置。

    只填未设置的项——CI 中已注入的环境变量优先。
    """
    injected = [key for key in _DEFAULT_ENV if key not in os.environ]
    for key in injected:
        os.environ[key] = _DEFAULT_ENV[key]
    yield
    for key in injected:
        os.environ.pop(key, None)


@pytest.fixture
def clear_settings_cache() -> Iterator[None]:
    """Settings 是 lru_cache 的，改环境变量的测试必须前后清缓存。"""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
