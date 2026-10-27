"""standard field cluster key and merge link

Revision ID: 20261027_0009
Revises: 20261027_0008
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0009"
down_revision: str | None = "20261027_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # cluster_key：候选来源字段名。标准可被改名/合并，聚类按 cluster_key 匹配，
    # 否则改名后重新聚类会把同一批字段再产出一个候选，标准库里出现重复概念。
    op.add_column("standard_field", sa.Column("cluster_key", sa.String(length=128)))
    op.execute("UPDATE standard_field SET cluster_key = standard_name WHERE cluster_key IS NULL")
    op.create_index("idx_standard_field_cluster_key", "standard_field", ["cluster_key"])

    # merged_into_id：本候选被合并进哪个标准（status=MERGED 时有值）
    op.add_column(
        "standard_field",
        sa.Column("merged_into_id", sa.BigInteger(), sa.ForeignKey("standard_field.id")),
    )


def downgrade() -> None:
    op.drop_column("standard_field", "merged_into_id")
    op.drop_index("idx_standard_field_cluster_key", table_name="standard_field")
    op.drop_column("standard_field", "cluster_key")
