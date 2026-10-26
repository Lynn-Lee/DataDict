import importlib
from typing import Any


class RecordingScheduler:
    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False

    async def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.shutdown_called = True


async def test_lifespan_starts_and_stops_sync_scheduler(monkeypatch: Any) -> None:
    monkeypatch.setenv("DB_URL_WEB", "postgresql+asyncpg://datadict_web:test@localhost/datadict")
    monkeypatch.setenv(
        "DB_URL_COLLECTOR",
        "postgresql+asyncpg://datadict_collector:test@localhost/datadict",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CREDENTIAL_SECRET_KEY", "test_only_secret_key_at_least_32_chars_x")
    monkeypatch.setenv("JWT_SECRET_KEY", "test_only_jwt_secret_key_at_least_32_chars")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app import main

    importlib.reload(main)
    scheduler = RecordingScheduler()
    calls: list[str] = []

    def init_pools(settings: object) -> None:
        del settings
        calls.append("init_pools")

    async def close_pools() -> None:
        calls.append("close_pools")

    monkeypatch.setattr(main, "init_pools", init_pools)
    monkeypatch.setattr(main, "close_pools", close_pools)
    monkeypatch.setattr(main, "MetadataSyncScheduler", lambda: scheduler)

    async with main.lifespan(object()):
        assert scheduler.started is True
        assert calls == ["init_pools"]

    assert scheduler.shutdown_called is True
    assert calls == ["init_pools", "close_pools"]
    get_settings.cache_clear()
