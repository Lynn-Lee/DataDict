from pathlib import Path

GRANTS_SQL = Path("deploy/grants.sql")
ALEMBIC_ENV = Path("alembic/env.py")


def test_grants_sql_declares_role_and_default_privileges() -> None:
    assert GRANTS_SQL.exists()

    sql = GRANTS_SQL.read_text(encoding="utf-8").lower()

    assert "create role datadict_web" in sql
    assert "create role datadict_collector" in sql
    assert "alter default privileges in schema public" in sql
    assert "grant all on tables to datadict_web" in sql
    assert "grant usage, select on sequences to datadict_web" in sql


def test_grants_sql_separates_collector_write_and_read_layers() -> None:
    assert GRANTS_SQL.exists()

    sql = GRANTS_SQL.read_text(encoding="utf-8").lower()

    for table_name in (
        "data_source",
        "table_meta",
        "column_meta",
        "index_meta",
        "schema_change_log",
        "sync_job_log",
        "sync_fail_detail",
        "annotation_todo",
    ):
        assert table_name in sql

    assert "grant select, insert, update" in sql
    assert "to datadict_collector" in sql
    assert "grant select on" in sql
    assert "asset_annotation" in sql
    assert "revoke insert, update, delete, truncate" in sql
    assert "from datadict_collector" in sql


def test_alembic_runs_grants_after_online_migrations() -> None:
    env_py = ALEMBIC_ENV.read_text(encoding="utf-8")

    assert "run_grants_sql" in env_py
    assert "deploy/grants.sql" in env_py
    assert "context.run_migrations()" in env_py
