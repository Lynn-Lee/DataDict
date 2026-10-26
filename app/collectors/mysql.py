import asyncio
from typing import Any, cast

import pymysql
from pymysql.cursors import DictCursor

from app.collectors.base import (
    BaseCollector,
    ColumnInfo,
    DatabaseInfo,
    IndexInfo,
    TableInfo,
)
from app.collectors.registry import register_collector

Row = dict[str, Any]


class MySQLCollector(BaseCollector):
    async def test_connection(self) -> bool:
        row = await self._fetch_one("SELECT 1 AS ok")
        return row is not None and row.get("ok") == 1

    async def list_databases(self) -> list[DatabaseInfo]:
        rows = await self._fetch_all(
            """
            SELECT schema_name AS name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            ORDER BY schema_name
            """
        )
        return [DatabaseInfo(name=str(row["name"])) for row in rows]

    async def list_tables(self, db_name: str) -> list[TableInfo]:
        rows = await self._fetch_all(
            """
            SELECT
                table_schema AS db_name,
                table_name,
                table_type,
                table_comment,
                engine,
                table_rows AS row_count,
                data_length AS data_size,
                create_time AS db_created_at
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            """,
            (db_name,),
        )
        return [
            TableInfo(
                db_name=str(row["db_name"]),
                table_name=str(row["table_name"]),
                table_type=_normalize_table_type(row["table_type"]),
                table_comment=_optional_str(row["table_comment"]),
                engine=_optional_str(row["engine"]),
                row_count=_optional_int(row["row_count"]),
                data_size=_optional_int(row["data_size"]),
                db_created_at=row["db_created_at"],
            )
            for row in rows
        ]

    async def list_columns(self, db_name: str) -> list[ColumnInfo]:
        rows = await self._fetch_all(
            """
            SELECT
                table_schema AS db_name,
                table_name,
                column_name,
                ordinal_position AS ordinal,
                column_type AS raw_type,
                character_maximum_length AS data_length,
                numeric_precision AS num_precision,
                numeric_scale AS num_scale,
                is_nullable,
                column_default AS default_value,
                column_comment AS raw_comment,
                column_key,
                extra
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (db_name,),
        )
        return [
            ColumnInfo(
                db_name=str(row["db_name"]),
                table_name=str(row["table_name"]),
                column_name=str(row["column_name"]),
                ordinal=int(row["ordinal"]),
                raw_type=str(row["raw_type"]),
                logical_type=self.normalize_type(str(row["raw_type"])),
                data_length=_optional_length(row["data_length"]),
                num_precision=_optional_int(row["num_precision"]),
                num_scale=_optional_int(row["num_scale"]),
                is_nullable=str(row["is_nullable"]).upper() == "YES",
                default_value=_optional_str(row["default_value"]),
                raw_comment=_optional_str(row["raw_comment"]),
                is_primary_key=str(row["column_key"]).upper() == "PRI",
                is_auto_incr="auto_increment" in str(row["extra"]).lower(),
                is_unique=str(row["column_key"]).upper() in {"PRI", "UNI"},
            )
            for row in rows
        ]

    async def list_indexes(self, db_name: str) -> list[IndexInfo]:
        rows = await self._fetch_all(
            """
            SELECT
                table_schema AS db_name,
                table_name,
                index_name,
                index_type,
                GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') AS columns,
                MIN(non_unique) AS non_unique
            FROM information_schema.statistics
            WHERE table_schema = %s
            GROUP BY table_schema, table_name, index_name, index_type
            ORDER BY table_name, index_name
            """,
            (db_name,),
        )
        return [
            IndexInfo(
                db_name=str(row["db_name"]),
                table_name=str(row["table_name"]),
                index_name=str(row["index_name"]),
                index_type=_optional_str(row["index_type"]),
                columns=_split_columns(row["columns"]),
                is_unique=int(row["non_unique"]) == 0,
            )
            for row in rows
        ]

    async def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[Row]:
        return await self._run_limited_query(
            lambda: asyncio.to_thread(self._fetch_all_sync, sql, params)
        )

    async def _fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> Row | None:
        return await self._run_limited_query(
            lambda: asyncio.to_thread(self._fetch_one_sync, sql, params)
        )

    def _fetch_all_sync(self, sql: str, params: tuple[Any, ...]) -> list[Row]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def _fetch_one_sync(self, sql: str, params: tuple[Any, ...]) -> Row | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cast(Row | None, cursor.fetchone())

    def _connect(self) -> Any:
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.username,
            password=self.config.password,
            database=self.config.default_db,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
        )


def _normalize_table_type(table_type: Any) -> str:
    value = str(table_type).upper()
    if value == "BASE TABLE":
        return "TABLE"
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


_INT32_MAX = 2**31 - 1


def _optional_length(value: Any) -> int | None:
    # longtext 报 4294967295，而 column_meta.data_length 是 INTEGER，钳到 int32
    number = _optional_int(value)
    return None if number is None else min(number, _INT32_MAX)


def _split_columns(value: Any) -> list[str]:
    if value is None:
        return []
    return [column for column in str(value).split(",") if column]


register_collector("mysql", MySQLCollector)
