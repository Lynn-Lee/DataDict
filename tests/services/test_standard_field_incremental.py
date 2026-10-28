"""增量聚类的取数边界（脱库单测，只看编译出来的 SQL）。

同步后只重聚本轮变更的字段名，必须按**字段名**过滤而不是按字段 URN：
同名的其他存量字段也要参与统计，否则类型分布和 candidate_count 会失真。
"""

from typing import Any

from sqlalchemy.dialects import postgresql

from app.services.standard_field import load_cluster_rows, load_doc_rows


class RecordingSession:
    def __init__(self, rows: list[Any]):
        self._rows = rows
        self.statements: list[str] = []

    async def execute(self, statement: object) -> list[Any]:
        self.statements.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        return self._rows


async def test_incremental_clustering_filters_by_column_name_not_urn() -> None:
    rows = [("status", "mysql:a:db:t1:status", "tinyint", "INT", "订单状态")]
    session = RecordingSession(rows)

    result = await load_cluster_rows(session, column_names={"status", "remark"})

    assert result == rows
    sql = session.statements[0]
    assert "column_meta.column_name IN ('remark', 'status')" in sql
    assert "column_meta.is_deleted IS false" in sql


async def test_full_clustering_keeps_unfiltered_scan() -> None:
    session = RecordingSession([])

    await load_cluster_rows(session)

    assert "IN (" not in session.statements[0]


async def test_empty_change_set_skips_query_entirely() -> None:
    """本轮没有字段变更 → 一条 SQL 都不该发，同步后链路要能被廉价地跳过。"""
    session = RecordingSession([])

    assert await load_cluster_rows(session, column_names=set()) == []
    assert await load_doc_rows(session, column_names=set()) == []
    assert session.statements == []


async def test_doc_rows_filter_by_same_column_names() -> None:
    session = RecordingSession([("status", "tinyint", "订单状态")])

    rows = await load_doc_rows(session, column_names={"status"})

    assert rows == [("status", "tinyint", "订单状态")]
    assert "excel_field_doc.column_name IN ('status')" in session.statements[0]
