"""LsAufgabe: aufgabentyp + antwort_schluessel_json + punkte (SCORM)

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-12

Idempotente Erweiterung von ls_aufgaben für die SCORM-Auto-Bewertung.
Default-Werte ('' für aufgabentyp, '' für antwort_schluessel_json, 1 für
punkte) sorgen dafür, dass Bestand-Aufgaben non-interaktiv bleiben und
nichts kaputt geht.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _existing_columns(insp, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = _existing_columns(insp, "ls_aufgaben")
    additions: list[sa.Column] = []
    if "aufgabentyp" not in cols:
        additions.append(sa.Column(
            "aufgabentyp", sa.String(16),
            nullable=False, server_default=""))
    if "antwort_schluessel_json" not in cols:
        additions.append(sa.Column(
            "antwort_schluessel_json", sa.Text(),
            nullable=False, server_default=""))
    if "punkte" not in cols:
        additions.append(sa.Column(
            "punkte", sa.Integer(), nullable=False, server_default="1"))
    if not additions:
        return
    with op.batch_alter_table("ls_aufgaben") as batch:
        for col in additions:
            batch.add_column(col)


def downgrade() -> None:
    with op.batch_alter_table("ls_aufgaben") as batch:
        for c in ("punkte", "antwort_schluessel_json", "aufgabentyp"):
            try:
                batch.drop_column(c)
            except Exception:
                pass
