"""标准字段定义接口 schema（字段统一治理 T-S3）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StandardFieldOut(BaseModel):
    id: int
    standard_name: str
    business_meaning: str | None = None
    logical_type: str
    raw_type: str | None = None
    status: str
    source_type: str
    has_conflict: bool
    type_distribution: dict[str, int] | None = None
    candidate_count: int
    version: int


class StandardFieldItemOut(BaseModel):
    column_urn: str
    db_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    raw_type: str | None = None
    logical_type: str | None = None
    conforms: bool | None = None


class StandardFieldDetailOut(StandardFieldOut):
    items: list[StandardFieldItemOut] = Field(default_factory=list)


class StandardFieldTagOut(BaseModel):
    id: int
    name: str


class StandardFieldLibraryOut(StandardFieldOut):
    """终版标准定义展示行：定义 + 业务标签（同一含义在不同业务域的叫法）。"""

    tags: list[StandardFieldTagOut] = Field(default_factory=list)


class AttachTagPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["发货网点"])


class GenerateCandidatesOut(BaseModel):
    generated: int
    updated: int
    skipped_confirmed: int
    skipped_conflict: int


class ConfirmStandardFieldPayload(BaseModel):
    raw_type: str = Field(min_length=1, max_length=128, examples=["varchar(32)"])
    logical_type: str = Field(min_length=1, max_length=32, examples=["STRING"])
    business_meaning: str = Field(min_length=1, examples=["运单号"])

    model_config = {
        "json_schema_extra": {
            "example": {
                "raw_type": "varchar(32)",
                "logical_type": "STRING",
                "business_meaning": "运单号",
            }
        }
    }
