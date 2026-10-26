"""数据源管理服务（PRD M1：注册 / 编辑 / 连接测试 / 启停）。

密码经 Fernet 加密落库（app.core.credentials），任何响应不回显密文与明文。
连接测试复用采集器注册表的 test_connection，错误按 PRD M1-2 分类。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import DataSourceConfig
from app.collectors.registry import get_collector
from app.core.credentials import decrypt_credential, encrypt_credential
from app.core.exceptions import ConflictError, DataDictError, NotFoundError
from app.models.metadata import DataSource
from app.schemas.datasource_admin import ConnectionTestOut, DataSourceUpsertPayload
from app.schemas.metadata_queries import DataSourceOut

TEST_CONNECTION_TIMEOUT_SECONDS = 15.0


def data_source_out(ds: DataSource) -> DataSourceOut:
    return DataSourceOut(
        id=ds.id,
        code=ds.code,
        name=ds.name,
        db_type=ds.db_type,
        env=ds.env,
        host=ds.host,
        port=ds.port,
        default_db=ds.default_db,
        group_name=ds.group_name,
        enabled=ds.enabled,
        username=ds.username,
        sync_cron=ds.sync_cron,
        last_sync_at=ds.last_sync_at,
        include_rules=ds.include_rules or [],
        exclude_rules=ds.exclude_rules or [],
    )


async def create_data_source(
    session: AsyncSession, payload: DataSourceUpsertPayload
) -> DataSourceOut:
    if not payload.password:
        raise DataDictError("创建数据源必须提供连接密码")
    exists = (
        await session.execute(select(DataSource.id).where(DataSource.code == payload.code))
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("数据源编码已存在", detail={"code": payload.code})

    ds = DataSource(
        code=payload.code,
        name=payload.name,
        db_type=payload.db_type,
        env=payload.env,
        host=payload.host,
        port=payload.port,
        default_db=payload.default_db,
        username=payload.username,
        password_cipher=encrypt_credential(payload.password),
        include_rules=payload.include_rules,
        exclude_rules=payload.exclude_rules,
        sync_cron=payload.sync_cron,
        group_name=payload.group_name,
        enabled=payload.enabled,
    )
    session.add(ds)
    await session.flush()
    return data_source_out(ds)


async def update_data_source(
    session: AsyncSession, source_id: int, payload: DataSourceUpsertPayload
) -> DataSourceOut:
    ds = await session.get(DataSource, source_id)
    if ds is None:
        raise NotFoundError("数据源不存在", detail={"id": source_id})
    if payload.code != ds.code:
        raise DataDictError("数据源编码参与 URN 生成，创建后不可修改", detail={"code": ds.code})

    ds.name = payload.name
    ds.db_type = payload.db_type
    ds.env = payload.env
    ds.host = payload.host
    ds.port = payload.port
    ds.default_db = payload.default_db
    ds.username = payload.username
    ds.include_rules = payload.include_rules
    ds.exclude_rules = payload.exclude_rules
    ds.sync_cron = payload.sync_cron
    ds.group_name = payload.group_name
    ds.enabled = payload.enabled
    if payload.password:
        ds.password_cipher = encrypt_credential(payload.password)
    await session.flush()
    return data_source_out(ds)


async def get_data_source_detail(session: AsyncSession, source_id: int) -> DataSourceOut:
    ds = await session.get(DataSource, source_id)
    if ds is None:
        raise NotFoundError("数据源不存在", detail={"id": source_id})
    return data_source_out(ds)


def _classify_connection_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, asyncio.TimeoutError):
        return "连接超时：主机不可达或端口未放行（检查网络连通性申请 P-4）"
    if isinstance(exc, KeyError):
        return f"驱动缺失：{exc}"
    if "access denied" in text or "password authentication failed" in text:
        return "账号无权限：用户名或密码错误"
    if "unknown database" in text or "does not exist" in text:
        return "默认库不存在：检查 default_db 配置"
    return f"网络不通或连接失败：{exc}"[:300]


async def test_data_source_connection(session: AsyncSession, source_id: int) -> ConnectionTestOut:
    ds = await session.get(DataSource, source_id)
    if ds is None:
        raise NotFoundError("数据源不存在", detail={"id": source_id})

    try:
        collector = get_collector(
            ds.db_type,
            DataSourceConfig(
                source_id=ds.id,
                code=ds.code,
                db_type=ds.db_type,
                host=ds.host,
                port=ds.port,
                username=ds.username,
                password=decrypt_credential(ds.password_cipher),
                default_db=ds.default_db,
                include_rules=ds.include_rules or [],
                exclude_rules=ds.exclude_rules or [],
                query_timeout_seconds=TEST_CONNECTION_TIMEOUT_SECONDS,
            ),
        )
        ok = await asyncio.wait_for(
            collector.test_connection(), timeout=TEST_CONNECTION_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - 连接测试需把任意驱动异常归类为用户可读信息
        return ConnectionTestOut(ok=False, message=_classify_connection_error(exc))
    if not ok:
        return ConnectionTestOut(ok=False, message="连接失败：采集器 test_connection 返回否")
    return ConnectionTestOut(ok=True, message="连接成功")
