"""数据库会话：Web 与采集使用两套独立连接池，对应两个数据库角色。

PRD §M10-8 / DEV-TASKS T8.1：
    datadict_web       —— 全表读写
    datadict_collector —— 采集层可写，知识层 **只授 SELECT**

隔离由数据库权限强制。本模块的职责是保证采集流程拿不到 web 连接：
采集路径一律用 `collector_session()`，代码评审中出现采集代码里用 `web_session()`
的一律打回（DEV-TASKS §7 红线第 6 条）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


@dataclass(slots=True)
class _Pools:
    web_engine: AsyncEngine
    collector_engine: AsyncEngine
    web_factory: async_sessionmaker[AsyncSession]
    collector_factory: async_sessionmaker[AsyncSession]


_pools: _Pools | None = None


def _make_engine(url: str, settings: Settings, *, label: str) -> AsyncEngine:
    logger.info("初始化数据库连接池 role={}", label)
    return create_async_engine(
        url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,  # 内网长连接易被中间设备掐断，取连接前先探活
    )


def init_pools(settings: Settings) -> None:
    global _pools
    if _pools is not None:
        return

    web_engine = _make_engine(str(settings.DB_URL_WEB), settings, label="web")
    collector_engine = _make_engine(str(settings.DB_URL_COLLECTOR), settings, label="collector")
    _pools = _Pools(
        web_engine=web_engine,
        collector_engine=collector_engine,
        web_factory=async_sessionmaker(web_engine, expire_on_commit=False),
        collector_factory=async_sessionmaker(collector_engine, expire_on_commit=False),
    )


async def close_pools() -> None:
    global _pools
    if _pools is None:
        return
    await _pools.web_engine.dispose()
    await _pools.collector_engine.dispose()
    _pools = None
    logger.info("数据库连接池已关闭")


def _require_pools() -> _Pools:
    if _pools is None:
        raise RuntimeError("连接池未初始化，init_pools() 应在应用启动时调用")
    return _pools


async def get_web_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：Web 请求使用的会话。"""
    async with _require_pools().web_factory() as session:
        yield session


@asynccontextmanager
async def collector_session() -> AsyncIterator[AsyncSession]:
    """采集任务专用会话。采集流程只能用这个。"""
    async with _require_pools().collector_factory() as session:
        yield session


@asynccontextmanager
async def web_session() -> AsyncIterator[AsyncSession]:
    """非请求上下文（如后台任务）中使用 web 角色的会话。"""
    async with _require_pools().web_factory() as session:
        yield session
