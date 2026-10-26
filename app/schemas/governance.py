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


class GovernanceTodoOut(BaseModel):
    id: int
    column_urn: str
    db_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    actual_type: str | None = None
    standard_field_id: int | None = None
    standard_name: str | None = None
    expected_type: str | None = None
    business_meaning: str | None = None
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
