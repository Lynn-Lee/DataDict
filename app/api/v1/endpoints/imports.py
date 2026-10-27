"""种子导入接口（T-S5b：历史数据字典 Excel 的 Web 上传导入）。

与 scripts/import_excel_seed.py 共用同一套解析/导入服务；
遵循 PRD 修订 B② 候选队列原则：导入产生 PENDING/IMPORT 标注与 IMPORT 字典，
不直接生效、不覆盖人工标注。dry_run=true 仅返回解析报告，不写库。
"""

import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DataDictError
from app.db.session import get_web_session
from app.schemas.imports import ExcelImportOut
from app.services.excel_import import (
    import_parsed_workbook,
    load_sheets_from_fileobj,
    parse_workbook,
)

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post(
    "/excel",
    response_model=ExcelImportOut,
    summary="上传导入 Excel 数据字典种子",
    description=(
        "上传历史数据字典 .xlsx（≤20MB）。Excel 与源库同步是平级的两路输入来源："
        "字段文档原文留档（按文件名幂等，重传覆盖旧留档），枚举字典按 code upsert；"
        "随后在标准定义工作台「重新聚类」即可与源库字段按字段名取并集生成候选标准。"
        "dry_run=true 仅返回解析预览，不写库。"
    ),
)
async def import_excel(
    session: Annotated[AsyncSession, Depends(get_web_session)],
    file: Annotated[UploadFile, File(description="数据字典 .xlsx 文件")],
    dry_run: Annotated[bool, Query(description="仅解析预览，不写库")] = False,
) -> ExcelImportOut:
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise DataDictError("仅支持 .xlsx 文件", detail={"filename": filename})

    data = await file.read()
    if not data:
        raise DataDictError("上传文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DataDictError("文件超过 20MB 上限，请拆分后分批导入")

    try:
        sheets = load_sheets_from_fileobj(io.BytesIO(data))
    except Exception as exc:
        raise DataDictError(f"Excel 解析失败：{exc}") from exc

    parsed = parse_workbook(sheets)
    distinct_tables = len({doc.table_name for doc in parsed.columns})
    out = ExcelImportOut(
        dry_run=dry_run,
        sheets=len(sheets),
        column_docs=len(parsed.columns),
        dicts_parsed=len(parsed.dicts),
        distinct_tables=distinct_tables,
    )
    if dry_run:
        return out

    report = await import_parsed_workbook(session, parsed, source_file=filename)
    await session.commit()
    out.docs_stored = report.docs_stored
    out.distinct_tables = report.distinct_tables or distinct_tables
    out.matched_synced_columns = report.matched_synced_columns
    out.dicts_imported = report.dicts_imported
    return out
