import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 - ensure model modules are imported for autogenerate
from alembic import context
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 部署环境用高权限账号（建扩展、ALTER DATABASE）跑迁移，连接串由环境变量注入，
# 不写进 alembic.ini。configparser 把 % 当插值符，密码里的 % 需转义。
_migration_url = os.environ.get("ALEMBIC_DB_URL")
if _migration_url:
    config.set_main_option("sqlalchemy.url", _migration_url.replace("%", "%%"))

target_metadata = Base.metadata
GRANTS_SQL_RELATIVE = Path("deploy/grants.sql")
GRANTS_SQL = Path(__file__).resolve().parents[1] / GRANTS_SQL_RELATIVE


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()

    with connection.begin():
        run_grants_sql(connection)


def run_grants_sql(connection: Connection) -> None:
    if GRANTS_SQL.exists():
        for statement in split_sql_statements(GRANTS_SQL.read_text(encoding="utf-8")):
            connection.exec_driver_sql(statement)


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    dollar_quote = False
    single_quote = False
    index = 0

    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""

        if not single_quote and sql.startswith("$$", index):
            dollar_quote = not dollar_quote
            current.append("$$")
            index += 2
            continue

        if char == "'" and not dollar_quote:
            single_quote = not single_quote
            current.append(char)
            index += 1
            continue

        if char == "-" and next_char == "-" and not dollar_quote and not single_quote:
            while index < len(sql) and sql[index] != "\n":
                current.append(sql[index])
                index += 1
            continue

        if char == ";" and not dollar_quote and not single_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
