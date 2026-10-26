#!/usr/bin/env python
"""创建或更新数据源，凭证加密落库（DEV-TASKS T8.2）。

采集器连接生产库需要明文密码，但明文绝不入库：本脚本把 --password 用 Fernet
加密成密文写入 `data_source.password_cipher`，明文不落库、不回显。主密钥取
环境变量 CREDENTIAL_SECRET_KEY（须与运行时一致，否则采集时解密失败）。用法：

    CREDENTIAL_SECRET_KEY=... python scripts/create_datasource.py \
        --code prod_mysql_core --name '核心交易库' --db-type mysql --env prod \
        --host 10.0.0.1 --port 3306 --username datadict_ro --password 's3cret' \
        --default-db trade --sync-cron '0 2 * * *'

按 code 幂等 upsert：已存在则更新连接信息与凭证，可用于轮换密码。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.credentials import encrypt_credential
from app.models.metadata import DataSource

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:15432/datadict"


def _parse_rules(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("include/exclude rules 须为 JSON 数组")
    return parsed


async def upsert_datasource(*, db_url: str, values: dict[str, Any]) -> None:
    engine = create_async_engine(db_url)
    statement = pg_insert(DataSource).values(created_at=func.now(), **values)
    statement = statement.on_conflict_do_update(
        index_elements=[DataSource.code],
        set_={
            "name": statement.excluded.name,
            "db_type": statement.excluded.db_type,
            "env": statement.excluded.env,
            "host": statement.excluded.host,
            "port": statement.excluded.port,
            "default_db": statement.excluded.default_db,
            "username": statement.excluded.username,
            "password_cipher": statement.excluded.password_cipher,
            "include_rules": statement.excluded.include_rules,
            "exclude_rules": statement.excluded.exclude_rules,
            "sync_cron": statement.excluded.sync_cron,
            "group_name": statement.excluded.group_name,
            "enabled": statement.excluded.enabled,
            "updated_at": func.now(),
        },
    )
    async with engine.begin() as conn:
        await conn.execute(statement)
    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建或更新数据源（凭证加密落库）")
    parser.add_argument("--code", required=True, help="数据源唯一编码，幂等 upsert 键")
    parser.add_argument("--name", required=True)
    parser.add_argument("--db-type", required=True, help="如 mysql / postgresql")
    parser.add_argument("--env", required=True, help="如 prod / test")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True, help="明文，加密后落库，不入库明文")
    parser.add_argument("--default-db", default=None)
    parser.add_argument("--include-rules", default=None, help="JSON 数组，白名单")
    parser.add_argument("--exclude-rules", default=None, help="JSON 数组，黑名单")
    parser.add_argument("--sync-cron", default="0 2 * * *")
    parser.add_argument("--group-name", default=None)
    parser.add_argument("--disabled", action="store_true", help="录入后不启用")
    parser.add_argument(
        "--db-url",
        default=None,
        help="默认取环境变量 DB_URL_WEB，其次本地 15432。需用对 data_source 有写权限的角色。",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    db_url = args.db_url or os.environ.get("DB_URL_WEB") or DEFAULT_DB_URL
    values: dict[str, Any] = {
        "code": args.code,
        "name": args.name,
        "db_type": args.db_type,
        "env": args.env,
        "host": args.host,
        "port": args.port,
        "default_db": args.default_db,
        "username": args.username,
        "password_cipher": encrypt_credential(args.password),
        "include_rules": _parse_rules(args.include_rules),
        "exclude_rules": _parse_rules(args.exclude_rules),
        "sync_cron": args.sync_cron,
        "group_name": args.group_name,
        "enabled": not args.disabled,
    }
    await upsert_datasource(db_url=db_url, values=values)
    print(f"数据源 {args.code} 已创建/更新（凭证已加密落库）")


if __name__ == "__main__":
    asyncio.run(main())
