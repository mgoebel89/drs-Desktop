"""lesson_notes table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_notes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_date", sa.String(10), nullable=False),
        sa.Column("klassen_key", sa.String(255), nullable=False),
        sa.Column("subjects_key", sa.String(255), nullable=False),
        sa.Column("theme", sa.String(500), nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("material", sa.Text, nullable=False, server_default=""),
        sa.Column("remarks", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_lesson_notes_user", "lesson_notes", ["user_id"])
    op.create_index("ix_lesson_notes_date", "lesson_notes", ["lesson_date"])
    op.create_index("ix_lesson_notes_lookup", "lesson_notes",
                    ["user_id", "lesson_date", "klassen_key", "subjects_key"], unique=True)
    op.create_index("ix_lesson_notes_series", "lesson_notes",
                    ["user_id", "klassen_key", "subjects_key", "lesson_date"])


def downgrade() -> None:
    op.drop_index("ix_lesson_notes_series", "lesson_notes")
    op.drop_index("ix_lesson_notes_lookup", "lesson_notes")
    op.drop_index("ix_lesson_notes_date", "lesson_notes")
    op.drop_index("ix_lesson_notes_user", "lesson_notes")
    op.drop_table("lesson_notes")
