"""Themen-Kaskade: Journal der Paket-Bewegungen bei Ausfall/Vertretung.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-19

Fällt eine Stunde aus (oder wird eine Vertretung als „verschieben" markiert),
wandert das Planungspaket (Thema + Notizen + Material) auf die nächste gehaltene
Stunde derselben Reihe (Klasse + Fach); alle folgenden Pakete rücken mit. Damit
das Aufheben der Ausnahme die Kette wieder exakt zurückschieben kann, wird jede
Einzelbewegung hier protokolliert.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def _has_table(insp, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_table(insp, "plan_shift_journal"):
        return
    op.create_table(
        "plan_shift_journal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("exception_id", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, server_default="0"),
        sa.Column("klassen_key", sa.String(255), server_default=""),
        sa.Column("subjects_key", sa.String(255), server_default=""),
        sa.Column("from_date", sa.String(10), server_default=""),
        sa.Column("from_block_start", sa.String(5), server_default=""),
        sa.Column("to_date", sa.String(10), server_default=""),
        sa.Column("to_block_start", sa.String(5), server_default=""),
        sa.Column("moved_theme", sa.Text, server_default=""),
        sa.Column("moved_notes", sa.Text, server_default=""),
        sa.Column("moved_material", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_plan_shift_journal_user_id",
                    "plan_shift_journal", ["user_id"])
    op.create_index("ix_plan_shift_journal_exception_id",
                    "plan_shift_journal", ["exception_id"])
    op.create_index("ix_plan_shift_journal_chain",
                    "plan_shift_journal", ["user_id", "exception_id", "seq"])


def downgrade() -> None:
    for idx in ("ix_plan_shift_journal_chain",
                "ix_plan_shift_journal_exception_id",
                "ix_plan_shift_journal_user_id"):
        try:
            op.drop_index(idx, table_name="plan_shift_journal")
        except Exception:
            pass
    try:
        op.drop_table("plan_shift_journal")
    except Exception:
        pass
