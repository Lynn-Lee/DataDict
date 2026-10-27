#!/usr/bin/env python
"""导入历史数据字典 Excel 种子（T-S5）。

解析与留档逻辑在 app/services/excel_import.py；Web 上传导入见
POST /api/v1/imports/excel（同一套服务）。本脚本供运维批量/离线场景使用。

Excel 与源库同步是平级的两路输入来源：导入只做原文留档（excel_field_doc，
按文件名幂等）与枚举字典入库，不写字段级标注；随后在工作台「重新聚类」
按字段名取两路并集生成候选标准定义。

    python scripts/import_excel_seed.py --file /path/to/数据字典.xlsx [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import io
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.excel_import import (
    import_parsed_workbook,
    load_sheets_from_fileobj,
    parse_workbook,
)

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:15432/datadict"


async def run(db_url: str, data: bytes, *, source_file: str, dry_run: bool) -> None:
    sheets = load_sheets_from_fileobj(io.BytesIO(data))
    parsed = parse_workbook(sheets)
    print(f"sheets: {len(sheets)}")
    print(f"parsed: column_docs={len(parsed.columns)} dicts={len(parsed.dicts)}")
    for dict_doc in parsed.dicts[:5]:
        print(f"  dict: {dict_doc.code} {dict_doc.name} items={len(dict_doc.items)}")
    if dry_run:
        tables = {doc.table_name for doc in parsed.columns}
        print(f"distinct tables in docs: {len(tables)}")
        print("dry-run: 未写库")
        return

    engine = create_async_engine(db_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        async with session.begin():
            report = await import_parsed_workbook(session, parsed, source_file=source_file)
    await engine.dispose()

    print("import report:")
    print(f"  column_docs:             {report.column_docs}")
    print(f"  docs_stored:             {report.docs_stored} (excel_field_doc 留档)")
    print(f"  distinct_tables:         {report.distinct_tables}")
    print(f"  matched_synced_columns:  {report.matched_synced_columns} (与已同步字段重合，信息项)")
    print(f"  dicts_imported:          {report.dicts_imported}")
    print("  下一步：到标准定义工作台点「重新聚类」，Excel 文档与源库字段按字段名并集生成候选")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="数据字典 Excel 路径")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()
    path = Path(args.file)
    asyncio.run(run(args.db_url, path.read_bytes(), source_file=path.name, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
