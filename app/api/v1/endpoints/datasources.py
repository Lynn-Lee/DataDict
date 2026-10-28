"""数据源管理接口（PRD M1：注册 / 编辑 / 连接测试 / 启停 / 手动同步）。

GET /datasources 列表在 metadata_queries 中（消费方只读视角）；
本模块承载管理侧写操作。密码 Fernet 加密落库，任何响应不回显。
手动同步经 BackgroundTasks 交给调度器执行（同步可能持续数分钟，不阻塞请求）。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DataDictError
from app.db.session import get_web_session
from app.schemas.datasource_admin import (
    ConnectionTestOut,
    DataSourceUpsertPayload,
    SyncTriggerOut,
)
from app.schemas.metadata_queries import DataSourceOut
from app.services import datasource_admin as service

router = APIRouter(prefix="/datasources", tags=["datasources"])


@router.post(
    "",
    response_model=DataSourceOut,
    summary="注册数据源",
    description=(
        "录入连接信息并加密存储密码（M1-1/M1-5）。code 参与 URN 生成，创建后不可修改。"
        "保存前请先用 /datasources/test-connection 做连通性校验（M1-2）。"
    ),
)
async def create_data_source(
    payload: DataSourceUpsertPayload,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> DataSourceOut:
    out = await service.create_data_source(session, payload)
    await session.commit()
    return out


@router.put(
    "/{source_id}",
    response_model=DataSourceOut,
    summary="更新数据源",
    description="更新连接信息、采集范围、同步策略与启停状态；password 留空表示不修改。",
)
async def update_data_source(
    source_id: int,
    payload: DataSourceUpsertPayload,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> DataSourceOut:
    out = await service.update_data_source(session, source_id, payload)
    await session.commit()
    return out


@router.get(
    "/{source_id}",
    response_model=DataSourceOut,
    summary="数据源详情",
    description="含采集范围与同步策略配置（不含任何密码信息），供编辑表单回填。",
)
async def get_data_source(
    source_id: int,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> DataSourceOut:
    return await service.get_data_source_detail(session, source_id)


@router.post(
    "/{source_id}/test",
    response_model=ConnectionTestOut,
    summary="连接测试",
    description=(
        "保存后强制连通性校验（M1-2）：失败按 网络不通/账号无权限/驱动缺失/超时 分类返回明确错误。"
    ),
)
async def test_data_source_connection(
    source_id: int,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> ConnectionTestOut:
    return await service.test_data_source_connection(session, source_id)


@router.post(
    "/{source_id}/sync",
    response_model=SyncTriggerOut,
    status_code=202,
    summary="手动触发同步",
    description=(
        "数据源级立即同步（M2-2），后台执行不阻塞请求；完成后自动接治理链路——"
        "按本轮新增/改类型/改注释的字段做增量聚类，再与已定版标准比对生成待办"
        "（类型冲突按字段、未挂标准缺口按表）。进度见 sync_job_log / 同步比对待办。"
    ),
)
async def trigger_data_source_sync(
    source_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> SyncTriggerOut:
    await service.get_data_source_detail(session, source_id)  # 不存在则 404
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    if scheduler is None:
        raise DataDictError("同步调度器未就绪，请稍后重试")
    background.add_task(scheduler.trigger_manual, source_id)
    return SyncTriggerOut(started=True, source_id=source_id)
