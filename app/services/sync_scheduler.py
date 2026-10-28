"""同步调度服务（DEV-TASKS T3.5 / T-S12）。

同步本身走采集层会话，采集完成后按本轮变更字段做增量聚类 + 治理扫描
（写知识层必须用 web 会话，见 DEV-TASKS §7 红线第 6 条）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, cast

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import select

from app.db.session import collector_session
from app.models.metadata import DataSource
from app.services.governance import run_post_sync_governance
from app.services.metadata_sync import MetadataSyncService, SyncSession


class SyncService(Protocol):
    async def sync_source(
        self,
        source_id: int,
        *,
        trigger_type: str,
        db_name: str | None = None,
        table_name: str | None = None,
    ) -> object: ...


class SchedulerBackend(Protocol):
    def add_job(
        self,
        func: Callable[..., object],
        trigger: object,
        *,
        id: str,
        args: list[object],
        replace_existing: bool,
        coalesce: bool,
        max_instances: int,
    ) -> None: ...

    def start(self) -> None: ...

    def shutdown(self, *, wait: bool) -> None: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[SyncSession]]
# 治理链路入口：None=全量重聚，序列=按本轮变更字段增量；测试可注入替身
GovernanceRunner = Callable[..., Awaitable[object]]


class MetadataSyncScheduler:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        sync_service: SyncService | None = None,
        scheduler: SchedulerBackend | None = None,
        governance_runner: GovernanceRunner | None = None,
    ) -> None:
        self._session_factory = session_factory or cast(SessionFactory, collector_session)
        self._sync_service = sync_service or MetadataSyncService()
        self._scheduler = scheduler or cast(SchedulerBackend, AsyncIOScheduler(timezone="UTC"))
        self._governance_runner = governance_runner or run_post_sync_governance

    async def start(self) -> None:
        await self.refresh_jobs()
        # 每日兜底：全量重聚 + 治理扫描（T-S8a/T-S12）。增量链路已接在每次同步之后，
        # 这一条兜住「Excel 新导入」「标准新定版」等没有同步事件触发的变化。
        # 与各数据源 cron 错开（默认同步多在凌晨 2 点），用 web 会话写知识层，
        # 不在采集事务内——采集角色对知识层无写权限（红线第 6 条）。
        self._scheduler.add_job(
            self._governance_runner,
            CronTrigger(hour=3, minute=30, timezone="UTC"),
            id="governance-sweep",
            args=[],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def refresh_jobs(self) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DataSource).where(
                    DataSource.enabled.is_(True),
                    DataSource.sync_cron.is_not(None),
                )
            )
            sources = result.scalars().all()

        for source in sources:
            self._scheduler.add_job(
                self.run_source,
                CronTrigger.from_crontab(source.sync_cron, timezone="UTC"),
                id=_job_id(source.id),
                args=[source.id],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )

    async def run_source(self, source_id: int) -> object:
        result = await self._sync_service.sync_source(source_id, trigger_type="CRON")
        await self._follow_up_governance(result)
        return result

    async def trigger_manual(
        self,
        source_id: int,
        *,
        db_name: str | None = None,
        table_name: str | None = None,
    ) -> object:
        result = await self._sync_service.sync_source(
            source_id,
            trigger_type="MANUAL",
            db_name=db_name,
            table_name=table_name,
        )
        await self._follow_up_governance(result)
        return result

    async def _follow_up_governance(self, result: object) -> None:
        """同步成功后立即按变更字段做增量聚类 + 治理扫描；失败只记录，每日全量 job 兜底。"""
        if getattr(result, "status", None) not in {"SUCCESS", "PARTIAL"}:
            return
        changed_urns = list(getattr(result, "governed_column_urns", ()) or ())
        try:
            await self._governance_runner(changed_urns)
        except Exception:  # noqa: BLE001 - 治理失败不能改写成同步失败（采集与治理是分开的写权限）
            logger.exception(
                "同步后治理链路失败 source_id={} 变更字段={}",
                getattr(result, "source_id", None),
                len(changed_urns),
            )


def _job_id(source_id: int) -> str:
    return f"sync-source-{source_id}"
