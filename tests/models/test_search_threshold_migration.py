from pathlib import Path

MIGRATION = Path("alembic/versions/20260806_0005_search_similarity_threshold.py")


def test_search_threshold_migration_sets_database_level_guc() -> None:
    assert MIGRATION.exists()

    migration_sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert 'down_revision: str | none = "20260806_0004"' in migration_sql
    assert "alter database datadict set pg_trgm.similarity_threshold = 0.1" in migration_sql
    assert "alter database datadict reset pg_trgm.similarity_threshold" in migration_sql
    assert 'op.execute("set pg_trgm.similarity_threshold' not in migration_sql
