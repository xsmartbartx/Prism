"""dashboard filters

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("filters", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.drop_column("filters")
