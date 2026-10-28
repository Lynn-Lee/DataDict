"""standard field sub key for same-name-different-meaning groups

Revision ID: 20261027_0010
Revises: 20261027_0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0010"
down_revision: str | None = "20261027_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 通用字段名（status/type/remark 等）同名不同义，聚类改按「字段名 + 释义」分组，
    # sub_key 存该组释义的哈希；空串表示按字段名整体定的标准。
    op.add_column(
        "standard_field",
        sa.Column("sub_key", sa.String(length=32), nullable=False, server_default=""),
    )
    # NOT NULL 后去掉默认值，由应用显式写入（默认值留在库里易掩盖漏赋值）
    op.alter_column("standard_field", "sub_key", server_default=None)

    # 同名标准唯一性从「按名」改为「按名 + 释义分组」：
    # status(运单状态) 与 status(工单状态) 可以并存，但两组各自不能重复。
    op.drop_index("uq_standard_field_active_name", table_name="standard_field")
    op.create_index(
        "uq_standard_field_active_name_sub",
        "standard_field",
        ["standard_name", "sub_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('DRAFT', 'CONFIRMED')"),
    )
    op.create_index(
        "idx_standard_field_cluster_sub", "standard_field", ["cluster_key", "sub_key"]
    )


def downgrade() -> None:
    op.drop_index("idx_standard_field_cluster_sub", table_name="standard_field")
    op.drop_index("uq_standard_field_active_name_sub", table_name="standard_field")
    op.create_index(
        "uq_standard_field_active_name",
        "standard_field",
        ["standard_name"],
        unique=True,
        postgresql_where=sa.text("status IN ('DRAFT', 'CONFIRMED')"),
    )
    op.drop_column("standard_field", "sub_key")
