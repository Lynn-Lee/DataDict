from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from app.collectors import DataSourceConfig, get_collector
from app.collectors.mysql import MySQLCollector

_active_rows: list[dict[str, Any]] = []


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], calls: list[tuple[str, tuple[Any, ...]]]):
        self._rows = rows
        self._calls = calls

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._calls.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]], calls: list[tuple[str, tuple[Any, ...]]]):
        self._rows = rows
        self._calls = calls

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows, self._calls)


def _config() -> DataSourceConfig:
    return DataSourceConfig(
        source_id=1,
        code="mysql_source",
        db_type="mysql",
        host="127.0.0.1",
        port=3306,
        username="readonly",
        password="secret",
        default_db="meta_test_db",
    )


@pytest.fixture
def mysql_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, tuple[Any, ...]]]]:
    calls: list[tuple[str, tuple[Any, ...]]] = []
    _active_rows.clear()

    def fake_connect(**_kwargs: Any) -> FakeConnection:
        return FakeConnection(_active_rows, calls)

    monkeypatch.setattr("app.collectors.mysql.pymysql.connect", fake_connect)
    yield calls
    _active_rows.clear()


def _set_rows(rows: list[dict[str, Any]]) -> None:
    _active_rows.clear()
    _active_rows.extend(rows)


def test_mysql_collector_is_registered() -> None:
    collector = get_collector("mysql", _config())

    assert isinstance(collector, MySQLCollector)


async def test_list_tables_reads_table_comments_with_one_batch_query(
    mysql_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    created_at = datetime(2026, 8, 6, 10, 0, 0)
    _set_rows(
        [
            {
                "db_name": "meta_test_db",
                "table_name": "orders",
                "table_type": "BASE TABLE",
                "table_comment": "订单表",
                "engine": "InnoDB",
                "row_count": 500,
                "data_size": 4096,
                "db_created_at": created_at,
            }
        ]
    )

    tables = await MySQLCollector(_config()).list_tables("meta_test_db")

    assert len(tables) == 1
    assert tables[0].table_name == "orders"
    assert tables[0].table_type == "TABLE"
    assert tables[0].table_comment == "订单表"
    assert tables[0].engine == "InnoDB"
    assert tables[0].row_count == 500
    assert tables[0].data_size == 4096
    assert tables[0].db_created_at == created_at
    assert len(mysql_calls) == 1
    sql, params = mysql_calls[0]
    assert "information_schema.tables" in sql.lower()
    assert "table_comment" in sql.lower()
    assert params == ("meta_test_db",)


async def test_list_columns_reads_column_comments_and_normalizes_types(
    mysql_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    _set_rows(
        [
            {
                "db_name": "meta_test_db",
                "table_name": "orders",
                "column_name": "pay_amount",
                "ordinal": 2,
                "raw_type": "decimal(12,2)",
                "data_length": 12,
                "num_precision": 12,
                "num_scale": 2,
                "is_nullable": "NO",
                "default_value": None,
                "raw_comment": "支付金额",
                "column_key": "",
                "extra": "",
            },
            {
                "db_name": "meta_test_db",
                "table_name": "orders",
                "column_name": "is_deleted",
                "ordinal": 3,
                "raw_type": "tinyint(1)",
                "data_length": 1,
                "num_precision": 3,
                "num_scale": 0,
                "is_nullable": "YES",
                "default_value": "0",
                "raw_comment": "是否删除",
                "column_key": "UNI",
                "extra": "auto_increment",
            },
        ]
    )

    columns = await MySQLCollector(_config()).list_columns("meta_test_db")

    assert [column.column_name for column in columns] == ["pay_amount", "is_deleted"]
    assert columns[0].raw_comment == "支付金额"
    assert columns[0].logical_type == "DECIMAL"
    assert columns[0].is_nullable is False
    assert columns[1].logical_type == "BOOL"
    assert columns[1].is_nullable is True
    assert columns[1].is_unique is True
    assert columns[1].is_auto_incr is True
    assert len(mysql_calls) == 1
    sql, params = mysql_calls[0]
    assert "information_schema.columns" in sql.lower()
    assert "column_comment" in sql.lower()
    assert params == ("meta_test_db",)


async def test_list_columns_clamps_longtext_length_to_int32(
    mysql_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    # MySQL/TiDB 对 longtext 报 CHARACTER_MAXIMUM_LENGTH=4294967295，超出 PG INTEGER 列范围
    _set_rows(
        [
            {
                "db_name": "meta_test_db",
                "table_name": "orders",
                "column_name": "remark",
                "ordinal": 1,
                "raw_type": "longtext",
                "data_length": 4294967295,
                "num_precision": None,
                "num_scale": None,
                "is_nullable": "YES",
                "default_value": None,
                "raw_comment": "备注",
                "column_key": "",
                "extra": "",
            }
        ]
    )

    columns = await MySQLCollector(_config()).list_columns("meta_test_db")

    assert columns[0].data_length == 2147483647
    assert columns[0].raw_type == "longtext"


async def test_list_indexes_reads_ordered_index_columns_with_one_batch_query(
    mysql_calls: list[tuple[str, tuple[Any, ...]]],
) -> None:
    _set_rows(
        [
            {
                "db_name": "meta_test_db",
                "table_name": "orders",
                "index_name": "idx_orders_user_pay",
                "index_type": "BTREE",
                "columns": "user_id,pay_amount",
                "non_unique": 0,
            }
        ]
    )

    indexes = await MySQLCollector(_config()).list_indexes("meta_test_db")

    assert len(indexes) == 1
    assert indexes[0].index_name == "idx_orders_user_pay"
    assert indexes[0].columns == ["user_id", "pay_amount"]
    assert indexes[0].index_type == "BTREE"
    assert indexes[0].is_unique is True
    assert len(mysql_calls) == 1
    sql, params = mysql_calls[0]
    assert "information_schema.statistics" in sql.lower()
    assert "group_concat" in sql.lower()
    assert params == ("meta_test_db",)
