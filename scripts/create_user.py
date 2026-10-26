#!/usr/bin/env python
"""创建或重置 DataDict 本地登录账号（DEV-TASKS T8.4）。

V0.1 简单登录用；SSO/LDAP 接入后本脚本可弃用。密码经 pbkdf2 哈希后落库，
明文不写入数据库。用法：

    python scripts/create_user.py --username lynn --password 's3cret' \
        --real-name Lynn --email lynn@example.com

按 username 幂等 upsert：已存在则重置密码与资料，可用于找回密码。
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import hash_password
from app.models.support import SysUser

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:15432/datadict"


async def upsert_user(
    *,
    db_url: str,
    username: str,
    password: str,
    real_name: str | None,
    email: str | None,
) -> None:
    engine = create_async_engine(db_url)
    values = {
        "username": username,
        "real_name": real_name,
        "email": email,
        "password_hash": hash_password(password),
        "enabled": True,
        "created_at": func.now(),
    }
    statement = pg_insert(SysUser).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[SysUser.username],
        set_={
            "real_name": statement.excluded.real_name,
            "email": statement.excluded.email,
            "password_hash": statement.excluded.password_hash,
            "enabled": True,
        },
    )
    async with engine.begin() as conn:
        await conn.execute(statement)
    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建或重置 DataDict 本地登录账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--real-name", default=None)
    parser.add_argument("--email", default=None)
    parser.add_argument(
        "--db-url",
        default=None,
        help="默认取环境变量 DB_URL_WEB，其次本地 15432。需用对 sys_user 有写权限的角色。",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    db_url = args.db_url or os.environ.get("DB_URL_WEB") or DEFAULT_DB_URL
    await upsert_user(
        db_url=db_url,
        username=args.username,
        password=args.password,
        real_name=args.real_name,
        email=args.email,
    )
    print(f"用户 {args.username} 已创建/更新")


if __name__ == "__main__":
    asyncio.run(main())
