"""标准字段定义接口 schema（字段统一治理 T-S3）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SimilarStandardOut(BaseModel):
    """候选可能已被标准库覆盖的提示（按 名/别名/释义相似 命中）。"""

    id: int
    standard_name: str
    raw_type: str | None = None
    business_meaning: str | None = None
    matched_by: str = Field(description="NAME=同名 / ALIAS=别名命中 / MEANING=释义相似")
    score: float = 0.0


class StandardFieldOut(BaseModel):
    id: int
    standard_name: str
    cluster_key: str | None = None
    # 非空表示该标准是按释义拆出来的通用字段名分组（status 运单状态 vs 工单状态）
    sub_key: str = ""
    merged_into_id: int | None = None
    business_meaning: str | None = None
    logical_type: str
    raw_type: str | None = None
    status: str
    source_type: str
    has_conflict: bool
    type_distribution: dict[str, int] | None = None
    candidate_count: int
    doc_count: int = 0
    version: int
    similar_standards: list[SimilarStandardOut] = Field(default_factory=list)


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
    standard_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="标准字段名，可改（如把 bill_code 组定版为 waybill_no）；留空表示沿用候选名",
        examples=["waybill_no"],
    )
    raw_type: str = Field(min_length=1, max_length=128, examples=["varchar(16)"])
    logical_type: str = Field(min_length=1, max_length=32, examples=["STRING"])
    business_meaning: str = Field(min_length=1, examples=["运单号"])

    model_config = {
        "json_schema_extra": {
            "example": {
                "standard_name": "waybill_no",
                "raw_type": "varchar(16)",
                "logical_type": "STRING",
                "business_meaning": "运单号",
            }
        }
    }
