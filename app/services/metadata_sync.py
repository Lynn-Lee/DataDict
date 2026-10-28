"""元数据同步主流程（DEV-TASKS T3.1）。

本模块只负责 T3.1 的同步骨架：凭证解密、同源互斥、白/黑名单过滤、
批量采集层 upsert 与幂等提交。T3.2+ 在此基础上接入变更 diff、软删除、
执行日志、告警和手动范围触发。
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.collectors import BaseCollector, DataSourceConfig, get_collector
from app.core.config import get_settings
from app.core.credentials import decrypt_credential
from app.db.session import collector_session
from app.models.metadata import ColumnMeta, DataSource, IndexMeta, TableMeta
from app.services.schema_diff import SchemaChangeSet, SQLAlchemySchemaChangeLogger
from app.services.sync_run import (
    SQLAlchemySyncRunRecorder,
    SyncFailure,
    calculate_comment_fill_rate,
)


class SyncSession(Protocol):
    async def get(self, entity: type[DataSource], ident: int) -> DataSource | None: ...

    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Any: ...

    async def scalar(self, statement: object, parameters: dict[str, Any] | None = None) -> Any: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SourceLock(Protocol):
    async def acquire(self, session: SyncSession, source_id: int) -> bool: ...

    async def release(self, session: SyncSession, source_id: int) -> None: ...


class MetadataWriter(Protocol):
    async def write_snapshot(
        self,
        session: SyncSession,
        *,
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
    ) -> None: ...


class SchemaChangeLogger(Protocol):
    async def detect_and_log(
        self,
        session: SyncSession,
        *,
        source_id: int,
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
        detected_at: datetime,
    ) -> SchemaChangeSet: ...


class SyncRunRecorder(Protocol):
    async def record_run(
        self,
        session: SyncSession,
        *,
        source_id: int,
        trigger_type: str,
        status: str,
        scanned_tables: int,
        changed_count: int,
        comment_fill_rate: Decimal,
        started_at: datetime,
        finished_at: datetime,
        failures: list[SyncFailure],
    ) -> None: ...


class RedisClient(Protocol):
    async def set(self, name: str, value: str, *, ex: int, nx: bool) -> Any: ...

    async def get(self, name: str) -> Any: ...

    async def delete(self, name: str) -> Any: ...


CollectorFactory = Callable[[str, DataSourceConfig], BaseCollector]
CredentialDecrypter = Callable[[str], str]
SessionFactory = Callable[[], AbstractAsyncContextManager[SyncSession]]


@dataclass(frozen=True, slots=True)
class SyncResult:
    source_id: int
    status: str
    scanned_databases: int = 0
    scanned_tables: int = 0
    scanned_columns: int = 0
    scanned_indexes: int = 0
    changed_count: int = 0
    fail_count: int = 0
    comment_fill_rate: Decimal = Decimal("0.00")
    # 本轮新增/改类型/改注释的字段 URN：同步后治理据此只做增量聚类，不全量重算
    governed_column_urns: tuple[str, ...] = ()


class InMemorySourceLock:
    """测试和单进程开发用锁；生产路径使用 RedisPostgresSourceLock。"""

    def __init__(self) -> None:
        self._locked: set[int] = set()

    async def acquire(self, session: SyncSession, source_id: int) -> bool:
        del session
        if source_id in self._locked:
            return False
        self._locked.add(source_id)
        return True

    async def release(self, session: SyncSession, source_id: int) -> None:
        del session
        self._locked.discard(source_id)


class RedisPostgresSourceLock:
    """Redis 分布式锁 + PostgreSQL advisory lock 双保险。"""

    def __init__(self, *, redis_client: RedisClient | None = None, ttl_seconds: int = 3600):
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[int, str] = {}

    async def acquire(self, session: SyncSession, source_id: int) -> bool:
        token = uuid4().hex
        redis_key = _redis_key(source_id)
        if self._redis is not None:
            acquired = await self._redis.set(redis_key, token, ex=self._ttl_seconds, nx=True)
            if not bool(acquired):
                return False
            self._tokens[source_id] = token

        lock_key = _advisory_lock_key(source_id)
        pg_acquired = await session.scalar(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        if bool(pg_acquired):
            return True

        await self._release_redis_if_owned(source_id)
        return False

    async def release(self, session: SyncSession, source_id: int) -> None:
        await session.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": _advisory_lock_key(source_id)},
        )
        await self._release_redis_if_owned(source_id)

    async def _release_redis_if_owned(self, source_id: int) -> None:
        if self._redis is None:
            return
        token = self._tokens.pop(source_id, None)
        if token is None:
            return
        current = await self._redis.get(_redis_key(source_id))
        if _decode_redis_value(current) == token:
            await self._redis.delete(_redis_key(source_id))


class SQLAlchemyMetadataWriter:
    def __init__(self, *, batch_size: int):
        self._batch_size = max(1, batch_size)

    async def write_snapshot(
        self,
        session: SyncSession,
        *,
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
    ) -> None:
        await self._upsert_batches(
            session,
            TableMeta,
            rows=tables,
            conflict_columns=("urn",),
            update_columns=(
                "source_id",
                "db_name",
                "table_name",
                "table_type",
                "table_comment",
                "engine",
                "row_count",
                "data_size",
                "db_created_at",
                "is_deleted",
                "deleted_at",
                "synced_at",
            ),
        )
        await self._upsert_batches(
            session,
            ColumnMeta,
            rows=columns,
            conflict_columns=("urn",),
            update_columns=(
                "table_urn",
                "column_name",
                "ordinal",
                "raw_type",
                "logical_type",
                "data_length",
                "num_precision",
                "num_scale",
                "is_nullable",
                "default_value",
                "raw_comment",
                "is_primary_key",
                "is_auto_incr",
                "is_unique",
                "is_partition_key",
                "is_deleted",
                "deleted_at",
                "synced_at",
            ),
        )
        await self._upsert_batches(
            session,
            IndexMeta,
            rows=indexes,
            conflict_columns=("table_urn", "index_name"),
            update_columns=("index_type", "columns", "synced_at"),
        )

    async def _upsert_batches(
        self,
        session: SyncSession,
        model: type[TableMeta] | type[ColumnMeta] | type[IndexMeta],
        *,
        rows: list[dict[str, Any]],
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> None:
        for batch in _chunked(rows, self._batch_size):
            statement = insert(model).values(batch)
            update_values = {
                column: getattr(statement.excluded, column) for column in update_columns
            }
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=list(conflict_columns),
                    set_=update_values,
                )
            )


class MetadataSyncService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        collector_factory: CollectorFactory = get_collector,
        credential_decrypter: CredentialDecrypter | None = None,
        lock: SourceLock | None = None,
        writer: MetadataWriter | None = None,
        change_logger: SchemaChangeLogger | None = None,
        run_recorder: SyncRunRecorder | None = None,
        batch_size: int | None = None,
    ):
        settings = get_settings()
        effective_batch_size = batch_size or settings.SYNC_BATCH_SIZE
        self._session_factory = session_factory or cast(SessionFactory, collector_session)
        self._collector_factory = collector_factory
        self._credential_decrypter = credential_decrypter or decrypt_credential
        self._lock = lock or RedisPostgresSourceLock(ttl_seconds=settings.SYNC_LOCK_TTL_SECONDS)
        self._writer = writer or SQLAlchemyMetadataWriter(batch_size=effective_batch_size)
        self._change_logger = change_logger or SQLAlchemySchemaChangeLogger(
            batch_size=effective_batch_size
        )
        self._run_recorder = run_recorder or SQLAlchemySyncRunRecorder()
        self._batch_size = effective_batch_size

    async def sync_source(
        self,
        source_id: int,
        *,
        trigger_type: str = "MANUAL",
        db_name: str | None = None,
        table_name: str | None = None,
    ) -> SyncResult:
        async with self._session_factory() as session:
            source = await session.get(DataSource, source_id)
            if source is None or not source.enabled:
                return SyncResult(source_id=source_id, status="SKIPPED")

            acquired = await self._lock.acquire(session, source.id)
            if not acquired:
                return SyncResult(source_id=source_id, status="SKIPPED_LOCKED")

            # rollback 会过期 ORM 实例，失败路径中再访问 source.* 会触发同步 IO 加载，
            # 因此提前取出纯量值。
            source_pk = source.id
            source_default_db = source.default_db or ""
            started_at = datetime.now(UTC)

            try:
                result = await self._collect_and_write(
                    session,
                    source,
                    trigger_type=trigger_type,
                    db_name=db_name,
                    table_name=table_name,
                )
                await session.commit()
                return result
            except Exception as exc:
                await session.rollback()
                # 连接级失败也必须落 sync_job_log/sync_fail_detail，否则失败不可见（M2-5/M12-1）
                try:
                    await self._run_recorder.record_run(
                        session,
                        source_id=source_pk,
                        trigger_type=trigger_type,
                        status="FAILED",
                        scanned_tables=0,
                        changed_count=0,
                        comment_fill_rate=Decimal("0"),
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        failures=[_sync_failure(source_pk, source_default_db, "CONNECT", exc)],
                    )
                    await session.commit()
                except Exception:  # noqa: BLE001 - 记录失败不能掩盖原始异常
                    await session.rollback()
                raise
            finally:
                await self._lock.release(session, source_pk)

    async def _collect_and_write(
        self,
        session: SyncSession,
        source: DataSource,
        *,
        trigger_type: str,
        db_name: str | None,
        table_name: str | None,
    ) -> SyncResult:
        started_at = datetime.now(UTC)
        manual_scope = _manual_scope_rule(db_name, table_name)
        collector = self._collector_factory(
            source.db_type,
            DataSourceConfig(
                source_id=source.id,
                code=source.code,
                db_type=source.db_type,
                host=source.host,
                port=source.port,
                username=source.username,
                password=self._credential_decrypter(source.password_cipher),
                default_db=source.default_db,
                include_rules=source.include_rules or [],
                exclude_rules=source.exclude_rules or [],
            ),
        )
        now = datetime.now(UTC)
        databases = [
            database
            for database in await collector.list_databases()
            if _matches_scope(
                database.name,
                None,
                source.include_rules or [],
                source.exclude_rules or [],
            )
            and _matches_manual_scope(database.name, None, manual_scope)
        ]
        table_rows: list[dict[str, Any]] = []
        column_rows: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        failures: list[SyncFailure] = []

        for database in databases:
            try:
                raw_tables = await collector.list_tables(database.name)
            except Exception as exc:  # noqa: BLE001 - 单库采集失败需记录明细并继续其他库
                failures.append(_sync_failure(source.id, database.name, "tables", exc))
                continue
            table_infos = [
                table
                for table in raw_tables
                if _matches_scope(
                    table.db_name,
                    table.table_name,
                    source.include_rules or [],
                    source.exclude_rules or [],
                )
                and _matches_manual_scope(table.db_name, table.table_name, manual_scope)
            ]
            table_urns = {
                (table.db_name, table.table_name): _table_urn(
                    source,
                    table.db_name,
                    table.table_name,
                )
                for table in table_infos
            }
            table_rows.extend(
                {
                    "urn": table_urns[(table.db_name, table.table_name)],
                    "source_id": source.id,
                    "db_name": table.db_name,
                    "table_name": table.table_name,
                    "table_type": table.table_type,
                    "table_comment": table.table_comment,
                    "engine": table.engine,
                    "row_count": table.row_count,
                    "data_size": table.data_size,
                    "db_created_at": table.db_created_at,
                    "is_deleted": False,
                    "deleted_at": None,
                    "synced_at": now,
                }
                for table in table_infos
            )

            try:
                raw_columns = await collector.list_columns(database.name)
                for column in raw_columns:
                    if (column.db_name, column.table_name) not in table_urns:
                        continue
                    try:
                        column_rows.append(
                            _column_row(
                                column,
                                table_urns[(column.db_name, column.table_name)],
                                now,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - 单表字段元数据异常需记录并继续
                        failures.append(
                            _sync_failure(
                                source.id,
                                database.name,
                                "columns",
                                exc,
                                table_name=column.table_name,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - 单库字段采集失败需记录明细并继续其他库
                failures.append(_sync_failure(source.id, database.name, "columns", exc))

            try:
                raw_indexes = await collector.list_indexes(database.name)
                for index in raw_indexes:
                    if (index.db_name, index.table_name) not in table_urns:
                        continue
                    try:
                        index_rows.append(
                            _index_row(index, table_urns[(index.db_name, index.table_name)], now)
                        )
                    except Exception as exc:  # noqa: BLE001 - 单表索引元数据异常需记录并继续
                        failures.append(
                            _sync_failure(
                                source.id,
                                database.name,
                                "indexes",
                                exc,
                                table_name=index.table_name,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - 单库索引采集失败需记录明细并继续其他库
                failures.append(_sync_failure(source.id, database.name, "indexes", exc))

        change_set = await self._change_logger.detect_and_log(
            session,
            source_id=source.id,
            tables=table_rows,
            columns=column_rows,
            indexes=index_rows,
            detected_at=now,
        )
        await self._writer.write_snapshot(
            session,
            tables=table_rows,
            columns=column_rows,
            indexes=index_rows,
        )
        status = "PARTIAL" if failures else "SUCCESS"
        comment_fill_rate = calculate_comment_fill_rate(column_rows)
        finished_at = datetime.now(UTC)
        await self._run_recorder.record_run(
            session,
            source_id=source.id,
            trigger_type=trigger_type,
            status=status,
            scanned_tables=len(table_rows),
            changed_count=change_set.count,
            comment_fill_rate=comment_fill_rate,
            started_at=started_at,
            finished_at=finished_at,
            failures=failures,
        )
        return SyncResult(
            source_id=source.id,
            status=status,
            scanned_databases=len(databases),
            scanned_tables=len(table_rows),
            scanned_columns=len(column_rows),
            scanned_indexes=len(index_rows),
            changed_count=change_set.count,
            fail_count=len(failures),
            comment_fill_rate=comment_fill_rate,
            governed_column_urns=tuple(sorted(change_set.governed_column_urns)),
        )


def _column_row(
    column: Any,
    table_urn: str,
    synced_at: datetime,
) -> dict[str, Any]:
    return {
        "urn": f"{table_urn}:{_urn_part(column.column_name)}",
        "table_urn": table_urn,
        "column_name": column.column_name,
        "ordinal": column.ordinal,
        "raw_type": column.raw_type,
        "logical_type": column.logical_type,
        "data_length": column.data_length,
        "num_precision": column.num_precision,
        "num_scale": column.num_scale,
        "is_nullable": column.is_nullable,
        "default_value": column.default_value,
        "raw_comment": column.raw_comment,
        "is_primary_key": column.is_primary_key,
        "is_auto_incr": column.is_auto_incr,
        "is_unique": column.is_unique,
        "is_partition_key": False,
        "is_deleted": False,
        "deleted_at": None,
        "synced_at": synced_at,
    }


def _index_row(index: Any, table_urn: str, synced_at: datetime) -> dict[str, Any]:
    return {
        "table_urn": table_urn,
        "index_name": index.index_name,
        "index_type": index.index_type,
        "columns": [
            {"name": column_name, "ordinal": ordinal}
            for ordinal, column_name in enumerate(index.columns, start=1)
        ],
        "synced_at": synced_at,
    }


def _sync_failure(
    source_id: int,
    db_name: str,
    stage: str,
    exc: Exception,
    *,
    table_name: str | None = None,
) -> SyncFailure:
    return SyncFailure(
        source_id=source_id,
        db_name=db_name,
        table_name=table_name,
        stage=stage,
        error_type=type(exc).__name__,
        error_msg=str(exc),
    )


def _table_urn(source: DataSource, db_name: str, table_name: str) -> str:
    return ":".join(
        (
            _urn_part(source.db_type),
            _urn_part(source.code),
            _urn_part(db_name),
            _urn_part(table_name),
        )
    )


def _urn_part(value: str) -> str:
    return value.strip().lower().replace(":", r"\:")


def _matches_scope(
    db_name: str,
    table_name: str | None,
    include_rules: Iterable[dict[str, Any]],
    exclude_rules: Iterable[dict[str, Any]],
) -> bool:
    include_rules_list = list(include_rules)
    exclude_rules_list = list(exclude_rules)
    if table_name is None:
        included = not include_rules_list or any(
            _matches_database_rule(rule, db_name) for rule in include_rules_list
        )
        if not included:
            return False
        return not any(
            _matches_database_rule(rule, db_name)
            for rule in exclude_rules_list
            if "table" not in rule
        )

    included = not include_rules_list or any(
        _matches_rule(rule, db_name, table_name) for rule in include_rules_list
    )
    if not included:
        return False
    return not any(_matches_rule(rule, db_name, table_name) for rule in exclude_rules_list)


def _matches_database_rule(rule: dict[str, Any], db_name: str) -> bool:
    db_pattern = str(rule.get("db") or rule.get("database") or rule.get("schema") or "*")
    return fnmatch.fnmatchcase(db_name, db_pattern)


def _matches_rule(rule: dict[str, Any], db_name: str, table_name: str | None) -> bool:
    db_pattern = str(rule.get("db") or rule.get("database") or rule.get("schema") or "*")
    table_pattern_value = rule.get("table")
    if not fnmatch.fnmatchcase(db_name, db_pattern):
        return False
    if table_pattern_value is None:
        return table_name is None or "table" not in rule
    return table_name is not None and fnmatch.fnmatchcase(table_name, str(table_pattern_value))


def _manual_scope_rule(db_name: str | None, table_name: str | None) -> dict[str, str] | None:
    if db_name is None and table_name is None:
        return None
    rule = {"db": db_name or "*"}
    if table_name is not None:
        rule["table"] = table_name
    return rule


def _matches_manual_scope(
    db_name: str,
    table_name: str | None,
    manual_scope: dict[str, str] | None,
) -> bool:
    if manual_scope is None:
        return True
    if table_name is None and "table" in manual_scope:
        return _matches_database_rule(manual_scope, db_name)
    return _matches_rule(manual_scope, db_name, table_name)


def _chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _advisory_lock_key(source_id: int) -> int:
    digest = hashlib.blake2b(f"datadict-sync:{source_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _redis_key(source_id: int) -> str:
    return f"datadict:sync:source:{source_id}"


def _decode_redis_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)
