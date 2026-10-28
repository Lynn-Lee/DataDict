from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects import postgresql

from app.services.schema_diff import (
    SchemaChangeSet,
    SQLAlchemySchemaChangeLogger,
    detect_schema_changes,
)


class RecordingSQLSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        del parameters
        self.statements.append(
            str(statement.compile(dialect=postgresql.dialect())).replace("\n", " ")
        )


class FakeExistingRows:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self) -> "FakeExistingRows":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class RecordingReadSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, Any] | None = None,
    ) -> FakeExistingRows:
        del parameters
        compiled = str(statement.compile(dialect=postgresql.dialect())).replace("\n", " ")
        self.statements.append(compiled)
        if "FROM table_meta" in compiled:
            return FakeExistingRows(
                [
                    {
                        "urn": "mysql:crm:sales:orders",
                        "source_id": 7,
                        "db_name": "sales",
                        "table_name": "orders",
                    },
                    {
                        "urn": "mysql:crm:archive:orders",
                        "source_id": 7,
                        "db_name": "archive",
                        "table_name": "orders",
                    },
                ]
            )
        return FakeExistingRows([])


def test_detect_schema_changes_covers_tables_columns_and_indexes() -> None:
    detected_at = datetime.now(UTC)

    changes = detect_schema_changes(
        existing_tables=[
            {"urn": "mysql:crm:sales:orders", "table_comment": "订单表"},
            {"urn": "mysql:crm:sales:legacy", "table_comment": "旧表"},
        ],
        existing_columns=[
            {
                "urn": "mysql:crm:sales:orders:pay_amount",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "decimal(10,2)",
                "logical_type": "DECIMAL",
                "raw_comment": "付款金额",
            },
            {
                "urn": "mysql:crm:sales:orders:created_at",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "date",
                "logical_type": "DATE",
                "raw_comment": "创建日期",
            },
            {
                "urn": "mysql:crm:sales:orders:old_flag",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "tinyint(1)",
                "logical_type": "BOOL",
                "raw_comment": "旧标记",
            },
        ],
        existing_indexes=[
            {
                "table_urn": "mysql:crm:sales:orders",
                "index_name": "idx_orders_amount",
                "index_type": "BTREE",
                "columns": [{"name": "pay_amount", "ordinal": 1}],
            },
            {
                "table_urn": "mysql:crm:sales:orders",
                "index_name": "idx_orders_legacy",
                "index_type": "BTREE",
                "columns": [{"name": "old_flag", "ordinal": 1}],
            },
        ],
        new_tables=[
            {"urn": "mysql:crm:sales:orders", "table_comment": "订单表"},
            {"urn": "mysql:crm:sales:payments", "table_comment": "支付表"},
        ],
        new_columns=[
            {
                "urn": "mysql:crm:sales:orders:pay_amount",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "decimal(10,2)",
                "logical_type": "DECIMAL",
                "raw_comment": "支付金额",
            },
            {
                "urn": "mysql:crm:sales:orders:created_at",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "timestamp",
                "logical_type": "DATETIME",
                "raw_comment": "创建时间",
            },
            {
                "urn": "mysql:crm:sales:orders:customer_id",
                "table_urn": "mysql:crm:sales:orders",
                "raw_type": "bigint",
                "logical_type": "INT",
                "raw_comment": "客户ID",
            },
        ],
        new_indexes=[
            {
                "table_urn": "mysql:crm:sales:orders",
                "index_name": "idx_orders_amount",
                "index_type": "BTREE",
                "columns": [
                    {"name": "pay_amount", "ordinal": 1},
                    {"name": "created_at", "ordinal": 2},
                ],
            },
            {
                "table_urn": "mysql:crm:sales:orders",
                "index_name": "idx_orders_customer",
                "index_type": "BTREE",
                "columns": [{"name": "customer_id", "ordinal": 1}],
            },
        ],
        detected_at=detected_at,
    )

    observed = {(change["asset_type"], change["change_type"], change["urn"]) for change in changes}

    assert ("TABLE", "TABLE_ADDED", "mysql:crm:sales:payments") in observed
    assert ("TABLE", "TABLE_DROPPED", "mysql:crm:sales:legacy") in observed
    assert ("COLUMN", "COLUMN_ADDED", "mysql:crm:sales:orders:customer_id") in observed
    assert ("COLUMN", "COLUMN_DROPPED", "mysql:crm:sales:orders:old_flag") in observed
    assert ("COLUMN", "COLUMN_TYPE_CHANGED", "mysql:crm:sales:orders:created_at") in observed
    assert ("COLUMN", "COLUMN_COMMENT_CHANGED", "mysql:crm:sales:orders:pay_amount") in observed
    assert ("INDEX", "INDEX_ADDED", "mysql:crm:sales:orders::idx_orders_customer") in observed
    assert ("INDEX", "INDEX_DROPPED", "mysql:crm:sales:orders::idx_orders_legacy") in observed
    assert ("INDEX", "INDEX_CHANGED", "mysql:crm:sales:orders::idx_orders_amount") in observed
    assert all(change["detected_at"] is detected_at for change in changes)


async def test_sqlalchemy_schema_change_logger_inserts_schema_change_log_rows() -> None:
    session = RecordingSQLSession()
    logger = SQLAlchemySchemaChangeLogger(batch_size=1)

    await logger.log_changes(
        session,
        [
            {
                "urn": "mysql:crm:sales:orders:pay_amount",
                "table_urn": "mysql:crm:sales:orders",
                "asset_type": "COLUMN",
                "change_type": "COLUMN_COMMENT_CHANGED",
                "before_value": {"raw_comment": "付款金额"},
                "after_value": {"raw_comment": "支付金额"},
                "rename_candidate": None,
                "rename_status": None,
                "detected_at": datetime.now(UTC),
            }
        ],
    )

    assert len(session.statements) == 1
    assert "INSERT INTO schema_change_log" in session.statements[0]


async def test_schema_change_logger_soft_deletes_dropped_tables_and_cascades_columns() -> None:
    session = RecordingSQLSession()
    logger = SQLAlchemySchemaChangeLogger(batch_size=100)
    deleted_at = datetime.now(UTC)

    await logger.mark_soft_deletes(
        session,
        [
            {
                "urn": "mysql:crm:sales:legacy",
                "table_urn": "mysql:crm:sales:legacy",
                "asset_type": "TABLE",
                "change_type": "TABLE_DROPPED",
                "before_value": {"urn": "mysql:crm:sales:legacy"},
                "after_value": None,
                "rename_candidate": None,
                "rename_status": None,
                "detected_at": deleted_at,
            },
            {
                "urn": "mysql:crm:sales:orders:old_flag",
                "table_urn": "mysql:crm:sales:orders",
                "asset_type": "COLUMN",
                "change_type": "COLUMN_DROPPED",
                "before_value": {"urn": "mysql:crm:sales:orders:old_flag"},
                "after_value": None,
                "rename_candidate": None,
                "rename_status": None,
                "detected_at": deleted_at,
            },
        ],
        deleted_at=deleted_at,
    )

    assert len(session.statements) == 2
    assert "UPDATE table_meta SET is_deleted=" in session.statements[0]
    assert "table_meta.urn IN" in session.statements[0]
    assert "UPDATE column_meta SET is_deleted=" in session.statements[1]
    assert "column_meta.table_urn IN" in session.statements[1]
    assert "column_meta.urn IN" in session.statements[1]


async def test_schema_change_logger_limits_existing_tables_to_scanned_databases() -> None:
    session = RecordingReadSession()
    logger = SQLAlchemySchemaChangeLogger(batch_size=100)

    await logger.detect_and_log(
        session,
        source_id=7,
        tables=[
            {
                "urn": "mysql:crm:sales:orders",
                "source_id": 7,
                "db_name": "sales",
                "table_name": "orders",
            }
        ],
        columns=[],
        indexes=[],
        detected_at=datetime.now(UTC),
    )

    assert "table_meta.db_name IN" in session.statements[0]
    assert "table_meta.is_deleted IS false" in session.statements[0]
    assert "column_meta.is_deleted IS false" in session.statements[1]


def test_change_set_selects_governed_columns_for_post_sync_governance() -> None:
    """同步后治理只处理新增/改型/改注释的字段；删除与索引变更不参与增量聚类。"""
    changes = detect_schema_changes(
        existing_tables=[{"urn": "mysql:p:d:t_old"}],
        existing_columns=[
            {"urn": "mysql:p:d:t:gone", "table_urn": "mysql:p:d:t", "column_name": "gone"},
            {
                "urn": "mysql:p:d:t:amount",
                "table_urn": "mysql:p:d:t",
                "column_name": "amount",
                "raw_type": "decimal(10,2)",
                "raw_comment": "金额",
            },
        ],
        existing_indexes=[],
        new_tables=[],
        new_columns=[
            {
                "urn": "mysql:p:d:t:amount",
                "table_urn": "mysql:p:d:t",
                "column_name": "amount",
                "raw_type": "decimal(12,2)",
                "raw_comment": "金额",
            },
            {
                "urn": "mysql:p:d:t:status",
                "table_urn": "mysql:p:d:t",
                "column_name": "status",
                "raw_type": "tinyint",
                "raw_comment": "订单状态",
            },
        ],
        new_indexes=[],
        detected_at=datetime.now(UTC),
    )

    change_set = SchemaChangeSet(changes=changes)
    assert change_set.governed_column_urns == {
        "mysql:p:d:t:amount",
        "mysql:p:d:t:status",
    }


def test_table_snapshot_is_json_serializable_with_real_db_created_at() -> None:
    # 真库返回的 db_created_at 是 datetime，写入 JSONB 的 before/after_value 必须可序列化
    import json

    changes = detect_schema_changes(
        existing_tables=[],
        existing_columns=[],
        existing_indexes=[],
        new_tables=[
            {
                "urn": "mysql:prod:operdb:orders",
                "table_name": "orders",
                "db_created_at": datetime(2026, 1, 2, 3, 4, 5),
                "synced_at": datetime.now(UTC),
            }
        ],
        new_columns=[],
        new_indexes=[],
        detected_at=datetime.now(UTC),
    )

    added = next(c for c in changes if c["change_type"] == "TABLE_ADDED")
    json.dumps(added["after_value"])
    assert added["after_value"]["db_created_at"] == "2026-01-02T03:04:05"
    assert "synced_at" not in added["after_value"]
