from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from app.collectors import DataSourceConfig, get_collector
from app.collectors.postgresql import PostgreSQLCollector

_active_rows: list[dict[str, Any]] = []


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]], calls: list[tuple[str, tuple[Any, ...]]]):
        self._rows = rows
        self._calls = calls
        self.closed = False

    async def fetch(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        self._calls.append((sql, params))
        return self._rows

    async def fetchrow(self, sql: str, *params: Any) -> dict[str, Any] | None:
        self._calls.append((sql, params))
        return self._rows[0] if self._rows else None

    async def close(self) -> None:
        self.closed = True


def _config() -> DataSourceConfig:
    return DataSourceConfig(
        source_id=1,
        code="postgresql_source",
        db_type="postgresql",
        host="127.0.0.1",
        port=5432,
        username="readonly",
        password="secret",
        default_db="datadict_source",
    )


@pytest.fixture
def pg_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, tuple[Any, ...]]]]:
    calls: list[tuple[str, tuple[Any, ...]]] = []
    _active_rows.clear()

    async def fake_connect(**_kwargs: Any) -> FakeConnection:
        return FakeConnection(_active_rows, calls)

    monkeypatch.setattr("app.collectors.postgresql.asyncpg.connect", fake_connect)
    yield calls
    _active_rows.clear()


def _set_rows(rows: list[dict[str, Any]]) -> None:
    _active_rows.clear()
    _active_rows.extend(rows)


def test_postgresql_collector_is_registered() -> None:
    collector = get_collector("postgresql", _config())

    assert isinstance(collector, PostgreSQLCollector)


async def test_list_tables_reads_pg_class_comments_with_one_batch_query(
    pg_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    created_at = datetime(2026, 8, 6, 10, 0, 0)
    _set_rows(
        [
            {
                "db_name": "public",
                "table_name": "orders",
                "table_type": "TABLE",
                "table_comment": "订单表",
                "row_count": 500,
                "data_size": 4096,
                "db_created_at": created_at,
            }
        ]
    )

    tables = await PostgreSQLCollector(_config()).list_tables("public")

    assert len(tables) == 1
    assert tables[0].table_name == "orders"
    assert tables[0].table_type == "TABLE"
    assert tables[0].table_comment == "订单表"
    assert tables[0].row_count == 500
    assert tables[0].data_size == 4096
    assert tables[0].db_created_at == created_at
    assert len(pg_calls) == 1
    sql, params = pg_calls[0]
    assert "pg_class" in sql.lower()
    assert "obj_description(c.oid, 'pg_class')" in sql.lower()
    assert "information_schema" not in sql.lower()
    assert params == ("public",)


async def test_list_columns_reads_col_description_and_normalizes_types(
    pg_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    _set_rows(
        [
            {
                "db_name": "public",
                "table_name": "orders",
                "column_name": "pay_amount",
                "ordinal": 2,
                "raw_type": "numeric(12,2)",
                "data_length": None,
                "num_precision": 12,
                "num_scale": 2,
                "is_nullable": False,
                "default_value": None,
                "raw_comment": "支付金额",
                "is_primary_key": False,
                "is_unique": False,
            },
            {
                "db_name": "public",
                "table_name": "orders",
                "column_name": "created_at",
                "ordinal": 3,
                "raw_type": "timestamp without time zone",
                "data_length": None,
                "num_precision": None,
                "num_scale": None,
                "is_nullable": True,
                "default_value": "now()",
                "raw_comment": "创建时间",
                "is_primary_key": False,
                "is_unique": False,
            },
        ]
    )

    columns = await PostgreSQLCollector(_config()).list_columns("public")

    assert [column.column_name for column in columns] == ["pay_amount", "created_at"]
    assert columns[0].raw_comment == "支付金额"
    assert columns[0].logical_type == "DECIMAL"
    assert columns[0].is_nullable is False
    assert columns[1].logical_type == "DATETIME"
    assert columns[1].is_nullable is True
    assert len(pg_calls) == 1
    sql, params = pg_calls[0]
    assert "pg_attribute" in sql.lower()
    assert "format_type(a.atttypid, a.atttypmod)" in sql.lower()
    assert "col_description(c.oid, a.attnum)" in sql.lower()
    assert "information_schema" not in sql.lower()
    assert params == ("public",)


async def test_list_indexes_reads_pg_index_columns_with_one_batch_query(
    pg_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    _set_rows(
        [
            {
                "db_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_user_pay",
                "index_type": "btree",
                "columns": ["user_id", "pay_amount"],
                "is_unique": True,
            }
        ]
    )

    indexes = await PostgreSQLCollector(_config()).list_indexes("public")

    assert len(indexes) == 1
    assert indexes[0].index_name == "idx_orders_user_pay"
    assert indexes[0].columns == ["user_id", "pay_amount"]
    assert indexes[0].index_type == "btree"
    assert indexes[0].is_unique is True
    assert len(pg_calls) == 1
    sql, params = pg_calls[0]
    assert "pg_index" in sql.lower()
    assert "pg_attribute" in sql.lower()
    assert "information_schema" not in sql.lower()
    assert params == ("public",)
