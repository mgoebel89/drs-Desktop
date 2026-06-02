"""settings table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False, server_default=""),
        sa.Column("blob", sa.LargeBinary, nullable=True),
        sa.Column("mime", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    op.drop_table("settings")
