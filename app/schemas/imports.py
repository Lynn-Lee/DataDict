"""种子导入接口 schema（T-S5b：Web 上传导入）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExcelImportOut(BaseModel):
    dry_run: bool = Field(description="true=仅解析预览，未写库")
    sheets: int
    column_docs: int = Field(description="解析出的字段文档数")
    dicts_parsed: int = Field(description="解析出的枚举字典数")
    distinct_tables: int
    matched_columns: int = 0
    annotations_created: int = 0
    annotations_skipped_existing: int = 0
    unmatched_docs: int = 0
    dicts_imported: int = 0
    unmatched_tables: list[str] = Field(default_factory=list)
