"""dataset links and scheduled refresh

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import server.db.models

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("imports", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_url", sa.String(length=2000), nullable=True))

    op.create_table(
        "dataset_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("schedule", sa.String(length=10), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=True),
        sa.Column("next_run_at", server.db.models.UTCDateTime(), nullable=True),
        sa.Column("lease_until", server.db.models.UTCDateTime(), nullable=True),
        sa.Column("last_run_at", server.db.models.UTCDateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified", sa.String(length=100), nullable=True),
        sa.Column("created_at", server.db.models.UTCDateTime(), nullable=False),
        sa.Column("updated_at", server.db.models.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id"),
    )
    with op.batch_alter_table("dataset_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_dataset_links_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_dataset_links_next_run_at"), ["next_run_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("dataset_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dataset_links_next_run_at"))
        batch_op.drop_index(batch_op.f("ix_dataset_links_workspace_id"))
    op.drop_table("dataset_links")
    with op.batch_alter_table("imports", schema=None) as batch_op:
        batch_op.drop_column("source_url")
