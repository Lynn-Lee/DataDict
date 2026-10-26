"""数据源管理接口 schema（PRD M1，Web 控制台配置入口）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DataSourceUpsertPayload(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_\-]+$",
        description="唯一编码，参与 URN 生成，创建后不可修改",
        examples=["prod_tidb_operdb"],
    )
    name: str = Field(min_length=1, max_length=128, examples=["运营库（TiDB）"])
    db_type: Literal["mysql", "postgresql"] = Field(
        description="V1.0 范围：mysql（含 TiDB/StarRocks 等 MySQL 协议库）/ postgresql"
    )
    env: Literal["prod", "pre", "test"]
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    default_db: str | None = Field(default=None, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="创建时必填；编辑时留空表示不修改。密文落库，永不回显",
    )
    include_rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description='白名单，如 [{"db": "operdb", "table": "t_order_*"}]',
    )
    exclude_rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description='黑名单，如 [{"db": "*", "table": "*_bak"}]',
    )
    sync_cron: str = Field(default="0 2 * * *", max_length=64, examples=["0 2 * * *"])
    group_name: str | None = Field(default=None, max_length=64)
    enabled: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "code": "prod_tidb_operdb",
                "name": "运营库（TiDB）",
                "db_type": "mysql",
                "env": "prod",
                "host": "10.0.0.1",
                "port": 4000,
                "default_db": "operdb",
                "username": "datadict_ro",
                "password": "s3cret",
                "include_rules": [{"db": "operdb"}],
                "exclude_rules": [{"db": "*", "table": "*_bak"}, {"db": "*", "table": "tmp_*"}],
                "sync_cron": "0 2 * * *",
                "group_name": "运营",
                "enabled": True,
            }
        }
    }


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str


class SyncTriggerOut(BaseModel):
    started: bool
    source_id: int
