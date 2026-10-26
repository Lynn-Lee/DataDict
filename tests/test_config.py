"""配置层测试。

重点覆盖 DEV-TASKS T0.3 的验收标准：配置缺失或非法时**启动即报错**。

所有用例都传 `_env_file=None` 并清空相关环境变量，保证结果不受开发者本地
`.env` 与 conftest 注入值的影响——否则"必填项缺失"这类用例会被外部值悄悄兜住而失效。
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_VALID: dict[str, Any] = {
    "DB_URL_WEB": "postgresql+asyncpg://datadict_web:pw@localhost:5432/datadict",
    "DB_URL_COLLECTOR": "postgresql+asyncpg://datadict_collector:pw@localhost:5432/datadict",
    "REDIS_URL": "redis://localhost:6379/0",
    "CREDENTIAL_SECRET_KEY": "x" * 32,
    "JWT_SECRET_KEY": "y" * 32,
}


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空所有相关环境变量，让用例只受显式传入的参数影响。"""
    for key in _VALID:
        monkeypatch.delenv(key, raising=False)


def _build(**overrides: Any) -> Settings:
    values = {**_VALID, **overrides}
    return Settings(_env_file=None, **values)


@pytest.mark.usefixtures("isolated_env")
def test_valid_settings() -> None:
    settings = _build()
    assert settings.APP_NAME == "datadict"
    assert settings.ENV == "local"
    assert settings.is_prod is False


@pytest.mark.usefixtures("isolated_env")
def test_missing_required_field_fails_fast() -> None:
    """必填项缺失必须在实例化时抛错，而不是运行到某个分支才炸。"""
    incomplete = {k: v for k, v in _VALID.items() if k != "DB_URL_COLLECTOR"}
    with pytest.raises(ValidationError, match="DB_URL_COLLECTOR"):
        Settings(_env_file=None, **incomplete)


@pytest.mark.usefixtures("isolated_env")
def test_same_db_role_is_rejected() -> None:
    """Web 与采集配成同一角色时必须拒绝启动。

    这是 PRD §M10-8 物理隔离的前提。两者相同则采集流程可以写标注表，
    且不会有任何报错——标注被覆盖时无从察觉，属于最不该静默失败的一处配置。
    """
    with pytest.raises(ValidationError, match="相同的数据库角色"):
        _build(DB_URL_COLLECTOR="postgresql+asyncpg://datadict_web:pw@localhost:5432/datadict")


@pytest.mark.usefixtures("isolated_env")
def test_short_secret_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(CREDENTIAL_SECRET_KEY="too-short")


@pytest.mark.usefixtures("isolated_env")
def test_unknown_env_var_is_rejected() -> None:
    """拼错的配置项要报错，不能被静默忽略。"""
    with pytest.raises(ValidationError):
        _build(DB_POOL_SIZEE=20)
