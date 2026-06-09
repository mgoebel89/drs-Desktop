"""app_files-Tabelle für die /api/files-Bilder-Bridge

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_uuid", sa.String(32), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(120), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_files")
