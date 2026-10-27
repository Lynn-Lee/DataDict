"""种子导入接口 schema（T-S5b：Web 上传导入）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExcelImportOut(BaseModel):
    dry_run: bool = Field(description="true=仅解析预览，未写库")
    sheets: int
    column_docs: int = Field(description="解析出的字段文档数")
    dicts_parsed: int = Field(description="解析出的枚举字典数")
    distinct_tables: int = 0
    docs_stored: int = Field(default=0, description="留档的字段文档数（同表同字段取最优后）")
    matched_synced_columns: int = Field(
        default=0, description="与已同步字段重合的文档数（信息项，反映当前可用比例）"
    )
    dicts_imported: int = 0
