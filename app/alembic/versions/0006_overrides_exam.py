"""subject overrides + exam flag

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("lesson_notes") as batch:
        batch.add_column(sa.Column("subject_override", sa.String(200),
                                   nullable=False, server_default=""))
        batch.add_column(sa.Column("is_exam", sa.Boolean,
                                   nullable=False, server_default=sa.false()))

    op.create_table(
        "lesson_series_overrides",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("klassen_key", sa.String(255), nullable=False),
        sa.Column("subjects_key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_series_overrides_user", "lesson_series_overrides", ["user_id"])
    op.create_index("ix_series_overrides_lookup", "lesson_series_overrides",
                    ["user_id", "klassen_key", "subjects_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_series_overrides_lookup", "lesson_series_overrides")
    op.drop_index("ix_series_overrides_user", "lesson_series_overrides")
    op.drop_table("lesson_series_overrides")
    with op.batch_alter_table("lesson_notes") as batch:
        batch.drop_column("is_exam")
        batch.drop_column("subject_override")
