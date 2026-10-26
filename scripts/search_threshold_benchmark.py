#!/usr/bin/env python
"""Run DataDict pg_trgm threshold benchmark for DEV-TASKS T4.2."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from typing import Any, cast

from sqlalchemy import delete, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.models.knowledge import AssetAnnotation
from app.models.metadata import ColumnMeta, DataSource, TableMeta
from app.services.search import build_column_search_statement
from app.services.search_tuning import (
    SearchQueryCase,
    ThresholdMeasurement,
    build_representative_fixture,
    build_v01_query_cases,
    calculate_recall,
    percentile_95,
    recommend_threshold,
)

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:15432/datadict"
DEFAULT_THRESHOLDS = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30)


async def main() -> None:
    args = _parse_args()
    db_url = args.db_url or os.environ.get("DB_URL_WEB") or DEFAULT_DB_URL
    thresholds = tuple(float(item) for item in args.thresholds.split(","))

    measurements = await benchmark_thresholds(
        db_url=db_url,
        thresholds=thresholds,
        limit=args.limit,
        runs=args.runs,
        use_fixture=args.fixture,
    )
    recommendation = recommend_threshold(
        measurements,
        min_recall=args.min_recall,
        max_p95_ms=args.max_p95_ms,
    )
    payload = {
        "dataset": "representative_fixture" if args.fixture else "existing_database",
        "query_count": len(build_v01_query_cases()),
        "thresholds": [asdict(measurement) for measurement in measurements],
        "recommended_threshold": recommendation.threshold,
        "constraints": {
            "min_recall": args.min_recall,
            "max_p95_ms": args.max_p95_ms,
        },
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(_to_markdown(payload))


async def benchmark_thresholds(
    *,
    db_url: str,
    thresholds: tuple[float, ...],
    limit: int,
    runs: int,
    use_fixture: bool,
) -> list[ThresholdMeasurement]:
    engine = create_async_engine(db_url, echo=False)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                if use_fixture:
                    await _seed_representative_fixture(conn)
                cases = build_v01_query_cases()
                return [
                    await _benchmark_threshold(
                        conn,
                        threshold=threshold,
                        cases=cases,
                        limit=limit,
                        runs=runs,
                    )
                    for threshold in thresholds
                ]
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _benchmark_threshold(
    conn: AsyncConnection,
    *,
    threshold: float,
    cases: list[SearchQueryCase],
    limit: int,
    runs: int,
) -> ThresholdMeasurement:
    await conn.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = {threshold:.4f}"))
    recalls: list[float] = []
    latencies_ms: list[float] = []
    result_counts: list[int] = []
    for case in cases:
        statement = build_column_search_statement(case.query, limit=limit, offset=0)
        rows: list[dict[str, Any]] = []
        for _ in range(runs):
            started = time.perf_counter()
            result = await conn.execute(statement)
            rows = [dict(row) for row in result.mappings().all()]
            latencies_ms.append((time.perf_counter() - started) * 1000)
        returned_urns = [str(row["urn"]) for row in rows]
        recalls.append(calculate_recall(returned_urns, case.expected_urns))
        result_counts.append(len(rows))

    return ThresholdMeasurement(
        threshold=threshold,
        recall=sum(recalls) / len(recalls),
        p95_ms=percentile_95(latencies_ms),
        avg_result_count=sum(result_counts) / len(result_counts),
    )


async def _seed_representative_fixture(conn: AsyncConnection) -> None:
    fixture = build_representative_fixture()
    source_id = cast(int, fixture.tables[0]["source_id"])
    table_urns = [str(table["urn"]) for table in fixture.tables]
    column_urns = [str(column["urn"]) for column in fixture.columns]
    await conn.execute(delete(AssetAnnotation).where(AssetAnnotation.urn.in_(column_urns)))
    await conn.execute(delete(ColumnMeta).where(ColumnMeta.table_urn.in_(table_urns)))
    await conn.execute(delete(TableMeta).where(TableMeta.source_id == source_id))
    await conn.execute(delete(DataSource).where(DataSource.id == source_id))
    await conn.execute(
        insert(DataSource).values(
            {
                "id": source_id,
                "code": "crm",
                "name": "CRM representative fixture",
                "db_type": "mysql",
                "env": "fixture",
                "host": "127.0.0.1",
                "port": 3306,
                "default_db": None,
                "username": "readonly",
                "password_cipher": "fixture",
                "include_rules": [],
                "exclude_rules": [],
                "sync_cron": "0 2 * * *",
                "enabled": True,
            }
        )
    )
    table_rows = [
        {
            "id": source_id + index,
            "urn": table["urn"],
            "source_id": table["source_id"],
            "db_name": table["db_name"],
            "table_name": table["table_name"],
            "table_type": table["table_type"],
            "table_comment": table["table_comment"],
            "is_deleted": table["is_deleted"],
        }
        for index, table in enumerate(fixture.tables, start=1)
    ]
    await conn.execute(insert(TableMeta).values(table_rows))
    column_rows = [
        {
            "id": source_id + 1000 + ordinal,
            "urn": column["urn"],
            "table_urn": column["table_urn"],
            "column_name": column["column_name"],
            "ordinal": ordinal,
            "raw_type": column["raw_type"],
            "logical_type": column["logical_type"],
            "raw_comment": column["raw_comment"],
            "is_nullable": True,
            "is_primary_key": False,
            "is_auto_incr": False,
            "is_unique": False,
            "is_partition_key": False,
            "is_deleted": column["is_deleted"],
        }
        for ordinal, column in enumerate(fixture.columns, start=1)
    ]
    await conn.execute(insert(ColumnMeta).values(column_rows))
    annotation_rows = [
        {
            "id": source_id + 2000 + index,
            **annotation,
        }
        for index, annotation in enumerate(fixture.annotations, start=1)
    ]
    await conn.execute(pg_insert(AssetAnnotation).values(annotation_rows))


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"dataset: {payload['dataset']}",
        f"query_count: {payload['query_count']}",
        "",
        "| threshold | recall | p95_ms | avg_result_count |",
        "|---:|---:|---:|---:|",
    ]
    for item in payload["thresholds"]:
        lines.append(
            f"| {item['threshold']:.2f} | {item['recall']:.3f} | "
            f"{item['p95_ms']:.3f} | {item['avg_result_count']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"recommended_threshold: {payload['recommended_threshold']:.2f}",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--thresholds", default=",".join(str(item) for item in DEFAULT_THRESHOLDS))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=0.94)
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--no-fixture", dest="fixture", action="store_false")
    parser.set_defaults(fixture=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
