"""治理待办接口 schema（T-S8b：同步比对拦截的处理闭环）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GovernanceSweepOut(BaseModel):
    attached_conforming: int
    attached_conflicting: int
    conforms_updated: int
    todos_created: int
    reattached: int = Field(
        default=0, description="因注释变更导致释义组变化而重挂到正确标准的字段数"
    )
    detached: int = Field(default=0, description="释义不再匹配任何组而摘除关联的字段数")
    missing_todos_created: int = 0
    missing_todos_updated: int = 0
    missing_todos_closed: int = 0
    missing_tables: int = Field(default=0, description="仍有字段未关联已定版标准的表数")
    scope: str = Field(default="SWEEP_ONLY", description="FULL / INCREMENTAL / SWEEP_ONLY")
    clustered_generated: int = 0
    clustered_updated: int = 0


class GovernanceGapColumn(BaseModel):
    """STANDARD_MISSING 待办里的未挂标准字段预览。"""

    column_name: str
    raw_type: str | None = None
    raw_comment: str | None = None
    has_draft_candidate: bool = Field(
        description="该字段名是否已有 DRAFT 候选标准（有则动作是去工作台定版，而不是新建标准）"
    )


class GovernanceTodoOut(BaseModel):
    id: int
    column_urn: str = Field(description="STANDARD_CONFLICT=字段 URN；STANDARD_MISSING=表 URN")
    todo_type: str = Field(description="STANDARD_CONFLICT=类型冲突 / STANDARD_MISSING=未挂标准缺口")
    db_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    actual_type: str | None = None
    standard_field_id: int | None = None
    standard_name: str | None = None
    expected_type: str | None = None
    business_meaning: str | None = None
    missing_count: int | None = Field(default=None, description="该表仍未关联已定版标准的字段数")
    missing_columns: list[GovernanceGapColumn] = Field(default_factory=list)
    preview_truncated: bool = False
    status: str
    action: str | None = None
    reason: str | None = None
    created_at: datetime | None = None
    done_at: datetime | None = None


class ResolveTodoPayload(BaseModel):
    action: Literal["ADOPT", "EXEMPT", "IGNORE"] = Field(
        description="ADOPT=采纳标准（生成存量改造建议后关闭）；EXEMPT=豁免（必须填原因，留痕）；IGNORE=忽略"
    )
    reason: str | None = Field(default=None, max_length=500)

    model_config = {
        "json_schema_extra": {
            "example": {"action": "EXEMPT", "reason": "外部供应商接口约定，不可修改"}
        }
    }
