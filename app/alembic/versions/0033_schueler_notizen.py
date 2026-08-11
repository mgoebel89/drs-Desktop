"""Schüler-Notizen: datierte Einträge mit Kategorie pro Schüler.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-10

Bewusst eine eigene Tabelle statt eines Freitextfelds an `students`: Der Wert
liegt in der **Entwicklung über das Schuljahr** (Elterngespräch, Zeugnis-
konferenz), und die braucht Datum und Historie. `owner_user_id` steht neben
`student_id`, damit die Notizen eines Lehrers ohne Join über `students`
gefiltert werden können — die Übersichtsseite tut genau das.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def _has_table(insp, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_table(insp, "student_notizen"):
        return
    op.create_table(
        "student_notizen",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("student_id", sa.Integer, nullable=False),
        sa.Column("owner_user_id", sa.Integer, nullable=False),
        sa.Column("datum", sa.String(10), server_default=""),
        sa.Column("kategorie", sa.String(20), server_default="beobachtung"),
        sa.Column("text", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_index("ix_student_notizen_student_id",
                    "student_notizen", ["student_id"])
    op.create_index("ix_student_notizen_owner_user_id",
                    "student_notizen", ["owner_user_id"])
    op.create_index("ix_student_notizen_datum", "student_notizen", ["datum"])


def downgrade() -> None:
    for idx in ("ix_student_notizen_datum",
                "ix_student_notizen_owner_user_id",
                "ix_student_notizen_student_id"):
        try:
            op.drop_index(idx, table_name="student_notizen")
        except Exception:
            pass
    try:
        op.drop_table("student_notizen")
    except Exception:
        pass
