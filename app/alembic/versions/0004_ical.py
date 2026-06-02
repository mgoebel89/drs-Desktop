"""ical_calendars table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ical_calendars",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False, server_default="Kalender"),
        sa.Column("color", sa.String(16), nullable=False, server_default="#7B61FF"),
        sa.Column("url_enc", sa.LargeBinary, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_ical_calendars_user", "ical_calendars", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ical_calendars_user", "ical_calendars")
    op.drop_table("ical_calendars")
