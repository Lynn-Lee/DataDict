"""create standard field tables

Revision ID: 20261026_0007
Revises: 20260812_0006
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261026_0007"
down_revision: str | None = "20260812_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standard_field",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("standard_name", sa.String(length=128), nullable=False),
        sa.Column("business_meaning", sa.Text()),
        sa.Column("logical_type", sa.String(length=32), nullable=False),
        sa.Column("raw_type", sa.String(length=128)),
        sa.Column("status", sa.String(length=16), server_default="DRAFT"),
        sa.Column("source_type", sa.String(length=16), server_default="CLUSTER"),
        sa.Column("has_conflict", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("type_distribution", postgresql.JSONB()),
        sa.Column("candidate_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), server_default=sa.text("1")),
        sa.Column("confirmed_by", sa.BigInteger()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 同名标准在同一时刻只允许一个活跃定义；废弃后允许同名重新定标
    op.create_index(
        "uq_standard_field_active_name",
        "standard_field",
        ["standard_name"],
        unique=True,
        postgresql_where=sa.text("status IN ('DRAFT', 'CONFIRMED')"),
    )
    op.create_index("idx_standard_field_status", "standard_field", ["status"])

    op.create_table(
        "standard_field_item",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "standard_field_id",
            sa.BigInteger(),
            sa.ForeignKey("standard_field.id"),
            nullable=False,
        ),
        sa.Column("column_urn", sa.String(length=768), nullable=False),
        sa.Column("conforms", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("standard_field_id", "column_urn", name="uq_standard_field_item"),
    )
    op.create_index("idx_standard_field_item_urn", "standard_field_item", ["column_urn"])


def downgrade() -> None:
    op.drop_index("idx_standard_field_item_urn", table_name="standard_field_item")
    op.drop_table("standard_field_item")
    op.drop_index("idx_standard_field_status", table_name="standard_field")
    op.drop_index("uq_standard_field_active_name", table_name="standard_field")
    op.drop_table("standard_field")
