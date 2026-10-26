"""基础查询接口 schema（DEV-TASKS T6.2）。"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import JsonSchemaValue

from app.schemas.urns import ColumnUrn, TableUrn

T = TypeVar("T")

DATA_SOURCE_OUT_EXAMPLE: JsonSchemaValue = {
    "id": 1,
    "code": "crm-prod",
    "name": "CRM 生产库",
    "db_type": "mysql",
    "env": "prod",
    "host": "crm-db.internal",
    "port": 3306,
    "default_db": "sales",
    "group_name": "CRM",
    "enabled": True,
}
TABLE_OUT_EXAMPLE: JsonSchemaValue = {
    "urn": "mysql:crm:sales:orders",
    "source_id": 1,
    "db_name": "sales",
    "table_name": "orders",
    "table_type": "TABLE",
    "table_comment": "订单表",
    "row_count": 1200,
    "data_size": 4096,
    "dw_layer": None,
    "is_deleted": False,
    "score": 0.93,
}
COLUMN_OUT_EXAMPLE: JsonSchemaValue = {
    "urn": "mysql:crm:sales:orders:pay_amount",
    "table_urn": "mysql:crm:sales:orders",
    "source_id": 1,
    "db_name": "sales",
    "table_name": "orders",
    "column_name": "pay_amount",
    "ordinal": 3,
    "raw_type": "decimal(12,2)",
    "logical_type": "decimal",
    "raw_comment": "支付金额",
    "is_nullable": False,
    "is_primary_key": False,
    "is_deleted": False,
    "business_meaning": "订单支付金额",
    "effective_type": "decimal",
    "effective_domain_id": 10,
    "domain_name": "交易域",
    "score": 0.91,
}
FIELD_SEARCH_GROUP_OUT_EXAMPLE: JsonSchemaValue = {
    "table_urn": "mysql:crm:sales:orders",
    "source_id": 1,
    "db_name": "sales",
    "table_name": "orders",
    "max_score": 0.91,
    "columns": [COLUMN_OUT_EXAMPLE],
}


class MetadataPage(BaseModel, Generic[T]):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    items: list[T]


class DataSourceOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": DATA_SOURCE_OUT_EXAMPLE})

    id: int
    code: str
    name: str
    db_type: str
    env: str
    host: str
    port: int
    default_db: str | None
    group_name: str | None
    enabled: bool
    # 数据源管理页（PRD M1）需要的配置回显字段；密码密文永不出现在任何响应中。
    username: str = ""
    sync_cron: str | None = None
    last_sync_at: datetime | None = None
    include_rules: list[dict[str, Any]] = Field(default_factory=list)
    exclude_rules: list[dict[str, Any]] = Field(default_factory=list)


class ChangeOut(BaseModel):
    """结构变更记录（schema_change_log，PRD M3/M9 变更类接口）。"""

    id: int
    urn: str
    table_urn: str | None = None
    asset_type: str | None = None
    change_type: str
    before_value: dict[str, Any] | None = None
    after_value: dict[str, Any] | None = None
    rename_candidate: str | None = None
    rename_status: str | None = None
    detected_at: datetime | None = None


class TableOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": TABLE_OUT_EXAMPLE})

    urn: TableUrn
    source_id: int
    db_name: str
    table_name: str
    table_type: str
    table_comment: str | None
    row_count: int | None
    data_size: int | None
    dw_layer: str | None
    is_deleted: bool
    score: float | None = None


class ColumnOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": COLUMN_OUT_EXAMPLE})

    urn: ColumnUrn
    table_urn: TableUrn
    source_id: int | None = None
    db_name: str | None = None
    table_name: str | None = None
    column_name: str
    ordinal: int
    raw_type: str
    logical_type: str
    raw_comment: str | None
    is_nullable: bool
    is_primary_key: bool
    is_deleted: bool
    business_meaning: str | None
    effective_type: str | None
    effective_domain_id: int | None
    domain_name: str | None
    score: float | None = None


class TableDdlOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "urn": "mysql:crm:sales:orders",
                "ddl": 'CREATE TABLE "orders" (\n  "pay_amount" decimal(12,2) NOT NULL\n);',
                "total": 1,
            }
        }
    )

    urn: TableUrn
    ddl: str
    total: int = 1


class FieldSearchGroupOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": FIELD_SEARCH_GROUP_OUT_EXAMPLE})

    table_urn: TableUrn
    source_id: int
    db_name: str
    table_name: str
    max_score: float
    columns: list[ColumnOut]


class SearchOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "订单",
                "total": 2,
                "page": 1,
                "page_size": 20,
                "tables": [TABLE_OUT_EXAMPLE],
                "field_groups": [FIELD_SEARCH_GROUP_OUT_EXAMPLE],
            }
        }
    )

    query: str
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    tables: list[TableOut]
    field_groups: list[FieldSearchGroupOut]
