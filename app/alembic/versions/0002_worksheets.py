"""worksheets + revisions

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worksheets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="Neues Aufgabenblatt"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_worksheets_owner", "worksheets", ["owner_user_id"])

    op.create_table(
        "worksheet_revisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("worksheet_id", sa.Integer,
                  sa.ForeignKey("worksheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("created_by_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("comment", sa.String(255), nullable=False, server_default=""),
        sa.Column("meta_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("aufgaben_json", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index("ix_worksheet_revisions_ws", "worksheet_revisions", ["worksheet_id"])
    op.create_index("ix_worksheet_revisions_at", "worksheet_revisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_worksheet_revisions_at", "worksheet_revisions")
    op.drop_index("ix_worksheet_revisions_ws", "worksheet_revisions")
    op.drop_table("worksheet_revisions")
    op.drop_index("ix_worksheets_owner", "worksheets")
    op.drop_table("worksheets")
