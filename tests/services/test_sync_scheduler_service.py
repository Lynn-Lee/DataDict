from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from app.models.metadata import DataSource
from app.services.sync_scheduler import MetadataSyncScheduler


class ScalarRows:
    def __init__(self, rows: list[DataSource]):
        self._rows = rows

    def all(self) -> list[DataSource]:
        return self._rows


class QueryResult:
    def __init__(self, rows: list[DataSource]):
        self._rows = rows

    def scalars(self) -> ScalarRows:
        return ScalarRows(self._rows)


class FakeSession:
    def __init__(self, rows: list[DataSource]):
        self._rows = rows

    async def execute(self, statement: object) -> QueryResult:
        del statement
        return QueryResult([row for row in self._rows if row.enabled and row.sync_cron])


class RecordingSchedulerBackend:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.started = False
        self.shutdown_called = False

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
    ) -> None:
        self.jobs.append(
            {
                "func": func,
                "trigger": trigger,
                "id": id,
                "args": args,
                "replace_existing": replace_existing,
                "coalesce": coalesce,
                "max_instances": max_instances,
            }
        )

    def start(self) -> None:
        self.started = True

    def shutdown(self, *, wait: bool) -> None:
        del wait
        self.shutdown_called = True


class RecordingSyncService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def sync_source(
        self,
        source_id: int,
        *,
        trigger_type: str,
        db_name: str | None = None,
        table_name: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "source_id": source_id,
                "trigger_type": trigger_type,
                "db_name": db_name,
                "table_name": table_name,
            }
        )


@asynccontextmanager
async def _session_factory(rows: list[DataSource]) -> AsyncIterator[FakeSession]:
    yield FakeSession(rows)


def _source(**overrides: Any) -> DataSource:
    values = {
        "id": 7,
        "code": "crm",
        "name": "CRM",
        "db_type": "mysql",
        "env": "prod",
        "host": "127.0.0.1",
        "port": 3306,
        "default_db": None,
        "username": "readonly",
        "password_cipher": "cipher-text",
        "include_rules": [],
        "exclude_rules": [],
        "sync_cron": "*/5 * * * *",
        "enabled": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return DataSource(**values)


async def test_scheduler_rebuilds_enabled_source_cron_jobs_on_startup() -> None:
    backend = RecordingSchedulerBackend()
    sync_service = RecordingSyncService()
    service = MetadataSyncScheduler(
        session_factory=lambda: _session_factory(
            [
                _source(id=7, sync_cron="*/5 * * * *", enabled=True),
                _source(id=8, sync_cron="0 2 * * *", enabled=False),
            ]
        ),
        sync_service=sync_service,
        scheduler=backend,
    )

    await service.start()

    assert backend.started is True
    # 数据源 cron job + 每日治理扫描 job（T-S8a）
    assert [job["id"] for job in backend.jobs] == ["sync-source-7", "governance-sweep"]
    assert backend.jobs[0]["args"] == [7]
    assert backend.jobs[0]["replace_existing"] is True
    assert backend.jobs[0]["coalesce"] is True
    assert backend.jobs[0]["max_instances"] == 1


async def test_scheduler_cron_job_runs_source_with_cron_trigger_type() -> None:
    backend = RecordingSchedulerBackend()
    sync_service = RecordingSyncService()
    service = MetadataSyncScheduler(
        session_factory=lambda: _session_factory([_source(id=7)]),
        sync_service=sync_service,
        scheduler=backend,
    )

    await service.run_source(7)

    assert sync_service.calls == [
        {
            "source_id": 7,
            "trigger_type": "CRON",
            "db_name": None,
            "table_name": None,
        }
    ]


async def test_scheduler_manual_trigger_supports_source_database_and_table_scope() -> None:
    backend = RecordingSchedulerBackend()
    sync_service = RecordingSyncService()
    service = MetadataSyncScheduler(
        session_factory=lambda: _session_factory([_source(id=7)]),
        sync_service=sync_service,
        scheduler=backend,
    )

    await service.trigger_manual(7, db_name="sales", table_name="orders")

    assert sync_service.calls == [
        {
            "source_id": 7,
            "trigger_type": "MANUAL",
            "db_name": "sales",
            "table_name": "orders",
        }
    ]
