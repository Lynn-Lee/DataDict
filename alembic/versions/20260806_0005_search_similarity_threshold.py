"""set pg_trgm similarity threshold

Revision ID: 20260806_0005
Revises: 20260806_0004
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0005"
down_revision: str | None = "20260806_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER DATABASE datadict SET pg_trgm.similarity_threshold = 0.1")


def downgrade() -> None:
    op.execute("ALTER DATABASE datadict RESET pg_trgm.similarity_threshold")
