"""excel field doc table and standard field evidence counts

Revision ID: 20261027_0008
Revises: 20261026_0007
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0008"
down_revision: str | None = "20261026_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "excel_field_doc",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("sheet_name", sa.String(length=128)),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("table_desc", sa.Text()),
        sa.Column("column_name", sa.String(length=128), nullable=False),
        sa.Column("column_desc", sa.Text()),
        sa.Column("column_type", sa.String(length=128)),
        sa.Column("remark", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_excel_doc_column", "excel_field_doc", ["column_name"])
    op.create_index("idx_excel_doc_table", "excel_field_doc", ["table_name", "column_name"])
    op.create_index("idx_excel_doc_file", "excel_field_doc", ["source_file"])

    # 候选标准的 Excel 文档来源计数（candidate_count 已是源库出现次数）
    op.add_column(
        "standard_field",
        sa.Column("doc_count", sa.Integer(), server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("standard_field", "doc_count")
    op.drop_index("idx_excel_doc_file", table_name="excel_field_doc")
    op.drop_index("idx_excel_doc_table", table_name="excel_field_doc")
    op.drop_index("idx_excel_doc_column", table_name="excel_field_doc")
    op.drop_table("excel_field_doc")
