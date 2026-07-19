"""Unterrichts-Reflexion pro Stunde (4 Kategorien × 3 Items, 4-stufig + k.A.).

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-19

Am key4 (Datum + Klasse + Fach + Block) verankert wie die Stundennotiz, aber in
einer eigenen Tabelle — die Reflexion wandert bei der Themen-Kaskade nicht mit.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _has_table(insp, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_table(insp, "lesson_reflections"):
        return
    op.create_table(
        "lesson_reflections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("lesson_date", sa.String(10)),
        sa.Column("klassen_key", sa.String(255)),
        sa.Column("subjects_key", sa.String(255)),
        sa.Column("block_start", sa.String(5), server_default=""),
        sa.Column("ratings_json", sa.Text, server_default="{}"),
        sa.Column("free_text", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("user_id", "lesson_date", "klassen_key",
                            "subjects_key", "block_start",
                            name="uq_lesson_reflection_key4"),
    )
    op.create_index("ix_lesson_reflections_user_id",
                    "lesson_reflections", ["user_id"])
    op.create_index("ix_lesson_reflections_lesson_date",
                    "lesson_reflections", ["lesson_date"])


def downgrade() -> None:
    for idx in ("ix_lesson_reflections_lesson_date",
                "ix_lesson_reflections_user_id"):
        try:
            op.drop_index(idx, table_name="lesson_reflections")
        except Exception:
            pass
    try:
        op.drop_table("lesson_reflections")
    except Exception:
        pass
