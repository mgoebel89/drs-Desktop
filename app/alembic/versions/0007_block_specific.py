"""lesson notes pro Block (block_start)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Spalte ergänzen
    with op.batch_alter_table("lesson_notes") as batch:
        batch.add_column(sa.Column("block_start", sa.String(5),
                                   nullable=False, server_default=""))

    # Unique-Index neu anlegen inkl. block_start
    op.drop_index("ix_lesson_notes_lookup", "lesson_notes")
    op.create_index("ix_lesson_notes_lookup", "lesson_notes",
                    ["user_id", "lesson_date", "klassen_key", "subjects_key", "block_start"],
                    unique=True)
    op.create_index("ix_lesson_notes_block", "lesson_notes",
                    ["block_start"])


def downgrade() -> None:
    op.drop_index("ix_lesson_notes_block", "lesson_notes")
    op.drop_index("ix_lesson_notes_lookup", "lesson_notes")
    op.create_index("ix_lesson_notes_lookup", "lesson_notes",
                    ["user_id", "lesson_date", "klassen_key", "subjects_key"],
                    unique=True)
    with op.batch_alter_table("lesson_notes") as batch:
        batch.drop_column("block_start")
