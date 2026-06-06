"""ls_aufgaben + lesson_note_aufgaben M2M

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ls_aufgaben",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("learning_situation_id", sa.Integer(),
                  sa.ForeignKey("learning_situations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("nummer", sa.Integer(), nullable=False),
        sa.Column("titel", sa.String(500), nullable=False, server_default=""),
        sa.Column("anchor", sa.String(120), nullable=False, server_default=""),
        sa.Column("phasen", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ls_aufgaben_ls_nummer", "ls_aufgaben",
                    ["learning_situation_id", "nummer"], unique=True)

    op.create_table(
        "lesson_note_aufgaben",
        sa.Column("lesson_note_id", sa.Integer(),
                  sa.ForeignKey("lesson_notes.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("ls_aufgabe_id", sa.Integer(),
                  sa.ForeignKey("ls_aufgaben.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("lesson_note_aufgaben")
    op.drop_index("ix_ls_aufgaben_ls_nummer", "ls_aufgaben")
    op.drop_table("ls_aufgaben")
