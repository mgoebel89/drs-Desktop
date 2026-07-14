"""Schüler-Austritt: Grund (Abschluss/Abgang) + letzter Schultag.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-14

Wer die Klasse verlässt, wird NICHT gelöscht, sondern inaktiv geschaltet:
`active=False` plus Grund und Datum des letzten Schultages. Der Schüler bleibt
dabei in seiner Klasse — sonst verlöre man die Zuordnung, unter der er in alten
Prüfungen geführt wird, und seine Bewertungen hingen in der Luft.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def _has_column(insp, table: str, col: str) -> bool:
    try:
        return col in {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    # Ohne DB-seitigen Constraint (SQLite kann per ALTER TABLE keinen anhängen;
    # die App erzwingt ohnehin keine FKs — siehe app/db.py und Migration 0026).
    if not _has_column(insp, "students", "austritt_grund"):
        op.add_column("students", sa.Column(
            "austritt_grund", sa.String(16), server_default=""))
    if not _has_column(insp, "students", "austritt_datum"):
        op.add_column("students", sa.Column(
            "austritt_datum", sa.String(10), server_default=""))


def downgrade() -> None:
    for col in ("austritt_grund", "austritt_datum"):
        try:
            op.drop_column("students", col)
        except Exception:
            pass
