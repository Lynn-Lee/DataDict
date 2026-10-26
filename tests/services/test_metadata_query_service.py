from app.schemas.metadata_queries import ColumnOut, TableOut
from app.services.metadata_queries import SQLAlchemyMetadataQueryService, _table_out


def test_build_table_ddl_uses_table_and_columns() -> None:
    service = SQLAlchemyMetadataQueryService()

    ddl = service.build_table_ddl(
        TableOut(
            urn="mysql:crm:sales:orders",
            source_id=1,
            db_name="sales",
            table_name="orders",
            table_type="TABLE",
            table_comment="订单表",
            row_count=None,
            data_size=None,
            dw_layer=None,
            is_deleted=False,
        ),
        [
            ColumnOut(
                urn="mysql:crm:sales:orders:id",
                table_urn="mysql:crm:sales:orders",
                column_name="id",
                ordinal=1,
                raw_type="bigint",
                logical_type="integer",
                raw_comment="主键",
                is_nullable=False,
                is_primary_key=True,
                is_deleted=False,
                business_meaning="订单ID",
                effective_type="integer",
                effective_domain_id=None,
                domain_name=None,
            ),
            ColumnOut(
                urn="mysql:crm:sales:orders:pay_amount",
                table_urn="mysql:crm:sales:orders",
                column_name="pay_amount",
                ordinal=2,
                raw_type="decimal(12,2)",
                logical_type="decimal",
                raw_comment="支付金额",
                is_nullable=True,
                is_primary_key=False,
                is_deleted=False,
                business_meaning="订单支付金额",
                effective_type="decimal",
                effective_domain_id=10,
                domain_name="交易域",
            ),
        ],
    )

    assert ddl == (
        'CREATE TABLE "orders" (\n'
        '  "id" bigint NOT NULL,\n'
        '  "pay_amount" decimal(12,2) NULL,\n'
        '  PRIMARY KEY ("id")\n'
        ");"
    )


def test_table_out_accepts_search_row_without_is_deleted() -> None:
    # 表搜索语句只选 6 个字段 + score，且已按 is_deleted=false 过滤，行里没有 is_deleted
    table = _table_out(
        {
            "urn": "mysql:prod:operdb:orders",
            "source_id": 1,
            "db_name": "operdb",
            "table_name": "orders",
            "table_type": "TABLE",
            "table_comment": "订单表",
            "score": 0.5,
        }
    )

    assert table.is_deleted is False
    assert table.score == 0.5
