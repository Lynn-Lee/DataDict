"""同步快照 diff 与 `schema_change_log` 落库（DEV-TASKS T3.2）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.metadata import ColumnMeta, IndexMeta, TableMeta
from app.models.support import SchemaChangeLog


class DiffSession(Protocol):
    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Any: ...


# 需要同步后治理复核的字段变更：新增、改类型、改注释（注释变了意味着释义组可能变了）
GOVERNED_COLUMN_CHANGES = frozenset(
    {"COLUMN_ADDED", "COLUMN_TYPE_CHANGED", "COLUMN_COMMENT_CHANGED"}
)


@dataclass(frozen=True, slots=True)
class SchemaChangeSet:
    """一轮 diff 的变更明细，供落库计数与同步后治理定位受影响字段。"""

    changes: list[dict[str, Any]]

    @property
    def count(self) -> int:
        return len(self.changes)

    @property
    def governed_column_urns(self) -> set[str]:
        """本轮需要重聚/重挂的字段 URN（不含被删除的字段）。"""
        return {
            str(change["urn"])
            for change in self.changes
            if change.get("asset_type") == "COLUMN"
            and change.get("change_type") in GOVERNED_COLUMN_CHANGES
        }


class SQLAlchemySchemaChangeLogger:
    def __init__(self, *, batch_size: int):
        self._batch_size = max(1, batch_size)

    async def detect_and_log(
        self,
        session: DiffSession,
        *,
        source_id: int,
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
        detected_at: datetime,
    ) -> SchemaChangeSet:
        scanned_databases = {str(row["db_name"]) for row in tables}
        existing_tables = await _load_existing_tables(session, source_id, scanned_databases)
        table_urns = {str(row["urn"]) for row in tables}
        existing_columns = await _load_existing_columns(session, table_urns)
        existing_indexes = await _load_existing_indexes(session, table_urns)
        changes = detect_schema_changes(
            existing_tables=existing_tables,
            existing_columns=existing_columns,
            existing_indexes=existing_indexes,
            new_tables=tables,
            new_columns=columns,
            new_indexes=indexes,
            detected_at=detected_at,
        )
        await self.log_changes(session, changes)
        await self.mark_soft_deletes(session, changes, deleted_at=detected_at)
        return SchemaChangeSet(changes=changes)

    async def log_changes(
        self,
        session: DiffSession,
        changes: list[dict[str, Any]],
    ) -> None:
        for batch in _chunked(changes, self._batch_size):
            await session.execute(insert(SchemaChangeLog).values(batch))

    async def mark_soft_deletes(
        self,
        session: DiffSession,
        changes: list[dict[str, Any]],
        *,
        deleted_at: datetime,
    ) -> None:
        dropped_table_urns = {
            str(change["urn"]) for change in changes if change["change_type"] == "TABLE_DROPPED"
        }
        dropped_column_urns = {
            str(change["urn"]) for change in changes if change["change_type"] == "COLUMN_DROPPED"
        }

        if dropped_table_urns:
            await session.execute(
                update(TableMeta)
                .where(
                    TableMeta.urn.in_(dropped_table_urns),
                    TableMeta.is_deleted.is_(False),
                )
                .values(is_deleted=True, deleted_at=deleted_at)
            )

        column_delete_predicates = []
        if dropped_table_urns:
            column_delete_predicates.append(ColumnMeta.table_urn.in_(dropped_table_urns))
        if dropped_column_urns:
            column_delete_predicates.append(ColumnMeta.urn.in_(dropped_column_urns))
        if column_delete_predicates:
            await session.execute(
                update(ColumnMeta)
                .where(
                    or_(*column_delete_predicates),
                    ColumnMeta.is_deleted.is_(False),
                )
                .values(is_deleted=True, deleted_at=deleted_at)
            )


def detect_schema_changes(
    *,
    existing_tables: list[dict[str, Any]],
    existing_columns: list[dict[str, Any]],
    existing_indexes: list[dict[str, Any]],
    new_tables: list[dict[str, Any]],
    new_columns: list[dict[str, Any]],
    new_indexes: list[dict[str, Any]],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    changes.extend(
        _detect_added_and_dropped(
            asset_type="TABLE",
            key_field="urn",
            added_type="TABLE_ADDED",
            dropped_type="TABLE_DROPPED",
            existing=existing_tables,
            new=new_tables,
            detected_at=detected_at,
        )
    )
    changes.extend(
        _detect_added_and_dropped(
            asset_type="COLUMN",
            key_field="urn",
            added_type="COLUMN_ADDED",
            dropped_type="COLUMN_DROPPED",
            existing=existing_columns,
            new=new_columns,
            detected_at=detected_at,
        )
    )
    changes.extend(_detect_column_updates(existing_columns, new_columns, detected_at))
    changes.extend(_detect_index_changes(existing_indexes, new_indexes, detected_at))
    return changes


def _detect_added_and_dropped(
    *,
    asset_type: str,
    key_field: str,
    added_type: str,
    dropped_type: str,
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    existing_by_key = {str(row[key_field]): row for row in existing}
    new_by_key = {str(row[key_field]): row for row in new}
    changes: list[dict[str, Any]] = []
    for key in sorted(new_by_key.keys() - existing_by_key.keys()):
        changes.append(
            _change(
                asset_type=asset_type,
                change_type=added_type,
                urn=key,
                row=new_by_key[key],
                before_value=None,
                after_value=_snapshot(new_by_key[key]),
                detected_at=detected_at,
            )
        )
    for key in sorted(existing_by_key.keys() - new_by_key.keys()):
        changes.append(
            _change(
                asset_type=asset_type,
                change_type=dropped_type,
                urn=key,
                row=existing_by_key[key],
                before_value=_snapshot(existing_by_key[key]),
                after_value=None,
                detected_at=detected_at,
            )
        )
    return changes


def _detect_column_updates(
    existing_columns: list[dict[str, Any]],
    new_columns: list[dict[str, Any]],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    existing_by_urn = {str(row["urn"]): row for row in existing_columns}
    new_by_urn = {str(row["urn"]): row for row in new_columns}
    changes: list[dict[str, Any]] = []
    for urn in sorted(existing_by_urn.keys() & new_by_urn.keys()):
        before = existing_by_urn[urn]
        after = new_by_urn[urn]
        before_type = _column_type_snapshot(before)
        after_type = _column_type_snapshot(after)
        if before_type != after_type:
            changes.append(
                _change(
                    asset_type="COLUMN",
                    change_type="COLUMN_TYPE_CHANGED",
                    urn=urn,
                    row=after,
                    before_value=before_type,
                    after_value=after_type,
                    detected_at=detected_at,
                )
            )
        if _normalize_nullable(before.get("raw_comment")) != _normalize_nullable(
            after.get("raw_comment")
        ):
            changes.append(
                _change(
                    asset_type="COLUMN",
                    change_type="COLUMN_COMMENT_CHANGED",
                    urn=urn,
                    row=after,
                    before_value={"raw_comment": before.get("raw_comment")},
                    after_value={"raw_comment": after.get("raw_comment")},
                    detected_at=detected_at,
                )
            )
    return changes


def _detect_index_changes(
    existing_indexes: list[dict[str, Any]],
    new_indexes: list[dict[str, Any]],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    existing_by_key = {_index_key(row): row for row in existing_indexes}
    new_by_key = {_index_key(row): row for row in new_indexes}
    changes: list[dict[str, Any]] = []
    for key in sorted(new_by_key.keys() - existing_by_key.keys()):
        row = new_by_key[key]
        changes.append(
            _change(
                asset_type="INDEX",
                change_type="INDEX_ADDED",
                urn=key,
                row=row,
                before_value=None,
                after_value=_index_snapshot(row),
                detected_at=detected_at,
            )
        )
    for key in sorted(existing_by_key.keys() - new_by_key.keys()):
        row = existing_by_key[key]
        changes.append(
            _change(
                asset_type="INDEX",
                change_type="INDEX_DROPPED",
                urn=key,
                row=row,
                before_value=_index_snapshot(row),
                after_value=None,
                detected_at=detected_at,
            )
        )
    for key in sorted(existing_by_key.keys() & new_by_key.keys()):
        before = _index_snapshot(existing_by_key[key])
        after = _index_snapshot(new_by_key[key])
        if before != after:
            changes.append(
                _change(
                    asset_type="INDEX",
                    change_type="INDEX_CHANGED",
                    urn=key,
                    row=new_by_key[key],
                    before_value=before,
                    after_value=after,
                    detected_at=detected_at,
                )
            )
    return changes


def _change(
    *,
    asset_type: str,
    change_type: str,
    urn: str,
    row: dict[str, Any],
    before_value: dict[str, Any] | None,
    after_value: dict[str, Any] | None,
    detected_at: datetime,
) -> dict[str, Any]:
    return {
        "urn": urn,
        "table_urn": row.get("table_urn") if asset_type != "TABLE" else row.get("urn"),
        "asset_type": asset_type,
        "change_type": change_type,
        "before_value": before_value,
        "after_value": after_value,
        "rename_candidate": None,
        "rename_status": None,
        "detected_at": detected_at,
    }


def _column_type_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_type": row.get("raw_type"),
        "logical_type": row.get("logical_type"),
        "data_length": row.get("data_length"),
        "num_precision": row.get("num_precision"),
        "num_scale": row.get("num_scale"),
        "is_nullable": row.get("is_nullable"),
    }


def _index_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "index_type": row.get("index_type"),
        "columns": row.get("columns") or [],
    }


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {"synced_at", "deleted_at"}
    # 写入 JSONB：真库返回的 datetime（db_created_at）、Decimal 不能直接序列化
    return {key: _json_safe(value) for key, value in row.items() if key not in ignored}


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _index_key(row: dict[str, Any]) -> str:
    return f"{row['table_urn']}::{row['index_name']}"


def _normalize_nullable(value: object) -> object:
    return None if value == "" else value


async def _load_existing_tables(
    session: DiffSession,
    source_id: int,
    scanned_databases: set[str],
) -> list[dict[str, Any]]:
    if not scanned_databases:
        return []
    result = await session.execute(
        select(
            TableMeta.urn,
            TableMeta.source_id,
            TableMeta.db_name,
            TableMeta.table_name,
            TableMeta.table_type,
            TableMeta.table_comment,
            TableMeta.engine,
            TableMeta.row_count,
            TableMeta.data_size,
            TableMeta.db_created_at,
        ).where(
            TableMeta.source_id == source_id,
            TableMeta.db_name.in_(scanned_databases),
            TableMeta.is_deleted.is_(False),
        )
    )
    return [_row_to_dict(row) for row in result.mappings().all()]


async def _load_existing_columns(
    session: DiffSession,
    table_urns: set[str],
) -> list[dict[str, Any]]:
    if not table_urns:
        return []
    result = await session.execute(
        select(
            ColumnMeta.urn,
            ColumnMeta.table_urn,
            ColumnMeta.column_name,
            ColumnMeta.ordinal,
            ColumnMeta.raw_type,
            ColumnMeta.logical_type,
            ColumnMeta.data_length,
            ColumnMeta.num_precision,
            ColumnMeta.num_scale,
            ColumnMeta.is_nullable,
            ColumnMeta.default_value,
            ColumnMeta.raw_comment,
            ColumnMeta.is_primary_key,
            ColumnMeta.is_auto_incr,
            ColumnMeta.is_unique,
            ColumnMeta.is_partition_key,
        ).where(
            ColumnMeta.table_urn.in_(table_urns),
            ColumnMeta.is_deleted.is_(False),
        )
    )
    return [_row_to_dict(row) for row in result.mappings().all()]


async def _load_existing_indexes(
    session: DiffSession,
    table_urns: set[str],
) -> list[dict[str, Any]]:
    if not table_urns:
        return []
    result = await session.execute(
        select(
            IndexMeta.table_urn,
            IndexMeta.index_name,
            IndexMeta.index_type,
            IndexMeta.columns,
        ).where(IndexMeta.table_urn.in_(table_urns))
    )
    return [_row_to_dict(row) for row in result.mappings().all()]


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
