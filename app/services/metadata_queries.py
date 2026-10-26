"""基础查询服务（DEV-TASKS T6.2）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from sqlalchemy import Select, func, or_, select

from app.core.exceptions import NotFoundError
from app.models.metadata import ColumnMeta, DataSource, TableMeta
from app.models.support import SchemaChangeLog
from app.schemas.metadata_queries import (
    ChangeOut,
    ColumnOut,
    DataSourceOut,
    FieldSearchGroupOut,
    MetadataPage,
    SearchOut,
    TableDdlOut,
    TableOut,
)
from app.services.search import (
    build_column_search_statement,
    build_table_search_statement,
    v_column_effective,
)


class MetadataQuerySession(Protocol):
    async def execute(self, statement: object, parameters: dict[str, Any] | None = None) -> Any: ...


class SQLAlchemyMetadataQueryService:
    async def list_data_sources(
        self,
        session: MetadataQuerySession,
        *,
        page: int,
        page_size: int,
    ) -> MetadataPage[DataSourceOut]:
        statement = (
            select(
                DataSource.id,
                DataSource.code,
                DataSource.name,
                DataSource.db_type,
                DataSource.env,
                DataSource.host,
                DataSource.port,
                DataSource.default_db,
                DataSource.group_name,
                DataSource.enabled,
                DataSource.username,
                DataSource.sync_cron,
                DataSource.last_sync_at,
                DataSource.include_rules,
                DataSource.exclude_rules,
            )
            .order_by(DataSource.id.asc())
            .limit(page_size)
            .offset(_offset(page, page_size))
        )
        rows = await _mapping_rows(session, statement)
        total = await _scalar_int(session, select(func.count()).select_from(DataSource))
        return MetadataPage(
            total=total,
            page=page,
            page_size=page_size,
            items=[_data_source_out(row) for row in rows],
        )

    async def list_changes(
        self,
        session: MetadataQuerySession,
        *,
        table_urn: str | None,
        urn: str | None,
        page: int,
        page_size: int,
    ) -> MetadataPage[ChangeOut]:
        """结构变更流水（PRD M3）：按表或按对象 URN 过滤，时间倒序。"""
        stmt = select(SchemaChangeLog)
        if table_urn:
            stmt = stmt.where(SchemaChangeLog.table_urn == table_urn)
        if urn:
            stmt = stmt.where(SchemaChangeLog.urn == urn)
        total = int(
            (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = await session.execute(
            stmt.order_by(SchemaChangeLog.detected_at.desc(), SchemaChangeLog.id.desc())
            .limit(page_size)
            .offset(_offset(page, page_size))
        )
        items = [
            ChangeOut(
                id=log.id,
                urn=log.urn,
                table_urn=log.table_urn,
                asset_type=log.asset_type,
                change_type=log.change_type,
                before_value=log.before_value,
                after_value=log.after_value,
                rename_candidate=log.rename_candidate,
                rename_status=log.rename_status,
                detected_at=log.detected_at,
            )
            for log in rows.scalars()
        ]
        return MetadataPage(total=total, page=page, page_size=page_size, items=items)

    async def list_tables(
        self,
        session: MetadataQuerySession,
        *,
        urn: str | None,
        source_id: int | None,
        db_name: str | None,
        keyword: str | None,
        include_deleted: bool,
        page: int,
        page_size: int,
    ) -> MetadataPage[TableOut]:
        statement = _table_select()
        if urn is not None:
            statement = statement.where(TableMeta.urn == urn)
        if source_id is not None:
            statement = statement.where(TableMeta.source_id == source_id)
        if db_name is not None:
            statement = statement.where(TableMeta.db_name == db_name)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(
                or_(TableMeta.table_name.ilike(pattern), TableMeta.table_comment.ilike(pattern))
            )
        if not include_deleted:
            statement = statement.where(TableMeta.is_deleted.is_(False))

        total = await _count_select(session, statement)
        rows = await _mapping_rows(
            session,
            statement.order_by(TableMeta.urn.asc())
            .limit(page_size)
            .offset(_offset(page, page_size)),
        )
        return MetadataPage(
            total=total,
            page=page,
            page_size=page_size,
            items=[_table_out(row) for row in rows],
        )

    async def list_columns(
        self,
        session: MetadataQuerySession,
        *,
        urn: str | None,
        table_urn: str | None,
        keyword: str | None,
        include_deleted: bool,
        page: int,
        page_size: int,
    ) -> MetadataPage[ColumnOut]:
        statement = _column_select()
        if urn is not None:
            statement = statement.where(ColumnMeta.urn == urn)
        if table_urn is not None:
            statement = statement.where(ColumnMeta.table_urn == table_urn)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(
                or_(ColumnMeta.column_name.ilike(pattern), ColumnMeta.raw_comment.ilike(pattern))
            )
        if not include_deleted:
            statement = statement.where(ColumnMeta.is_deleted.is_(False))

        total = await _count_select(session, statement)
        rows = await _mapping_rows(
            session,
            statement.order_by(ColumnMeta.ordinal.asc())
            .limit(page_size)
            .offset(_offset(page, page_size)),
        )
        return MetadataPage(
            total=total,
            page=page,
            page_size=page_size,
            items=[_column_out(row) for row in rows],
        )

    async def get_table_ddl(self, session: MetadataQuerySession, *, urn: str) -> TableDdlOut:
        table_page = await self.list_tables(
            session,
            urn=urn,
            source_id=None,
            db_name=None,
            keyword=None,
            include_deleted=False,
            page=1,
            page_size=1,
        )
        if not table_page.items:
            raise NotFoundError("表不存在", detail={"urn": urn})
        column_page = await self.list_columns(
            session,
            urn=None,
            table_urn=urn,
            keyword=None,
            include_deleted=False,
            page=1,
            page_size=100,
        )
        return TableDdlOut(
            urn=cast(Any, urn),
            ddl=self.build_table_ddl(table_page.items[0], column_page.items),
            total=1,
        )

    async def search(
        self,
        session: MetadataQuerySession,
        *,
        query: str,
        page: int,
        page_size: int,
    ) -> SearchOut:
        table_statement = build_table_search_statement(
            query, limit=page_size, offset=_offset(page, page_size)
        )
        column_statement = build_column_search_statement(
            query,
            limit=page_size,
            offset=_offset(page, page_size),
        )
        table_total = await _count_select(session, table_statement)
        column_total = await _count_select(session, column_statement)
        table_rows = await _mapping_rows(session, table_statement)
        column_rows = await _mapping_rows(session, column_statement)
        columns = [_column_out(row) for row in column_rows]
        return SearchOut(
            query=query,
            total=table_total + column_total,
            page=page,
            page_size=page_size,
            tables=[_table_out(row) for row in table_rows],
            field_groups=_group_columns_by_table(columns),
        )

    def build_table_ddl(self, table: TableOut, columns: list[ColumnOut]) -> str:
        column_lines = [
            f"  {_quote_ident(column.column_name)} {column.raw_type} "
            f"{'NULL' if column.is_nullable else 'NOT NULL'}"
            for column in sorted(columns, key=lambda item: item.ordinal)
        ]
        primary_keys = [column for column in columns if column.is_primary_key]
        if primary_keys:
            names = ", ".join(_quote_ident(column.column_name) for column in primary_keys)
            column_lines.append(f"  PRIMARY KEY ({names})")
        return (
            f"CREATE TABLE {_quote_ident(table.table_name)} (\n" + ",\n".join(column_lines) + "\n);"
        )


def _table_select() -> Select[Any]:
    return cast(
        "Select[Any]",
        select(
            TableMeta.urn,
            TableMeta.source_id,
            TableMeta.db_name,
            TableMeta.table_name,
            TableMeta.table_type,
            TableMeta.table_comment,
            TableMeta.row_count,
            TableMeta.data_size,
            TableMeta.dw_layer,
            TableMeta.is_deleted,
        ),
    )


def _column_select() -> Select[Any]:
    return select(
        ColumnMeta.urn,
        ColumnMeta.table_urn,
        v_column_effective.c.source_id,
        v_column_effective.c.db_name,
        v_column_effective.c.table_name,
        ColumnMeta.column_name,
        ColumnMeta.ordinal,
        ColumnMeta.raw_type,
        ColumnMeta.logical_type,
        ColumnMeta.raw_comment,
        ColumnMeta.is_nullable,
        ColumnMeta.is_primary_key,
        ColumnMeta.is_deleted,
        v_column_effective.c.business_meaning,
        v_column_effective.c.effective_type,
        v_column_effective.c.effective_domain_id,
        v_column_effective.c.domain_name,
    ).select_from(
        ColumnMeta.__table__.join(
            v_column_effective,
            v_column_effective.c.urn == ColumnMeta.urn,
        )
    )


def _offset(page: int, page_size: int) -> int:
    return (page - 1) * page_size


async def _mapping_rows(session: MetadataQuerySession, statement: object) -> list[dict[str, Any]]:
    result = await session.execute(statement)
    return [dict(row) for row in result.mappings().all()]


async def _scalar_int(session: MetadataQuerySession, statement: object) -> int:
    result = await session.execute(statement)
    return int(result.scalar_one())


async def _count_select(session: MetadataQuerySession, statement: Select[Any]) -> int:
    count_statement = select(func.count()).select_from(
        statement.order_by(None).limit(None).offset(None).subquery()
    )
    return await _scalar_int(session, count_statement)


def _data_source_out(row: dict[str, Any]) -> DataSourceOut:
    return DataSourceOut(
        id=int(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        db_type=str(row["db_type"]),
        env=str(row["env"]),
        host=str(row["host"]),
        port=int(row["port"]),
        default_db=cast(str | None, row["default_db"]),
        group_name=cast(str | None, row["group_name"]),
        enabled=bool(row["enabled"]),
        username=str(row.get("username") or ""),
        sync_cron=cast(str | None, row.get("sync_cron")),
        last_sync_at=cast("datetime | None", row.get("last_sync_at")),
        include_rules=cast(list[dict[str, Any]], row.get("include_rules") or []),
        exclude_rules=cast(list[dict[str, Any]], row.get("exclude_rules") or []),
    )


def _table_out(row: dict[str, Any]) -> TableOut:
    return TableOut(
        urn=str(row["urn"]),
        source_id=int(row["source_id"]),
        db_name=str(row["db_name"]),
        table_name=str(row["table_name"]),
        table_type=str(row["table_type"]),
        table_comment=cast(str | None, row["table_comment"]),
        row_count=int(row["row_count"]) if row.get("row_count") is not None else None,
        data_size=int(row["data_size"]) if row.get("data_size") is not None else None,
        dw_layer=cast(str | None, row.get("dw_layer")),
        is_deleted=bool(row.get("is_deleted", False)),  # 表搜索已过滤删除表，行里不带该键
        score=float(row["score"]) if row.get("score") is not None else None,
    )


def _column_out(row: dict[str, Any]) -> ColumnOut:
    return ColumnOut(
        urn=str(row["urn"]),
        table_urn=str(row["table_urn"]),
        source_id=int(row["source_id"]) if row.get("source_id") is not None else None,
        db_name=cast(str | None, row.get("db_name")),
        table_name=cast(str | None, row.get("table_name")),
        column_name=str(row["column_name"]),
        ordinal=int(row.get("ordinal", 0)),
        raw_type=str(row["raw_type"]),
        logical_type=str(row["logical_type"]),
        raw_comment=cast(str | None, row.get("raw_comment")),
        is_nullable=bool(row.get("is_nullable", True)),
        is_primary_key=bool(row.get("is_primary_key", False)),
        is_deleted=bool(row.get("is_deleted", False)),
        business_meaning=cast(str | None, row.get("business_meaning")),
        effective_type=cast(str | None, row.get("effective_type")),
        effective_domain_id=(
            int(row["effective_domain_id"]) if row.get("effective_domain_id") is not None else None
        ),
        domain_name=cast(str | None, row.get("domain_name")),
        score=float(row["score"]) if row.get("score") is not None else None,
    )


def _group_columns_by_table(columns: list[ColumnOut]) -> list[FieldSearchGroupOut]:
    grouped: dict[str, list[ColumnOut]] = {}
    for column in columns:
        grouped.setdefault(column.table_urn, []).append(column)
    return [
        FieldSearchGroupOut(
            table_urn=table_columns[0].table_urn,
            source_id=table_columns[0].source_id or 0,
            db_name=table_columns[0].db_name or table_columns[0].table_urn.split(":")[2],
            table_name=table_columns[0].table_name or table_columns[0].table_urn.split(":")[3],
            max_score=max(column.score or 0 for column in table_columns),
            columns=table_columns,
        )
        for table_columns in grouped.values()
    ]


def _quote_ident(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'
