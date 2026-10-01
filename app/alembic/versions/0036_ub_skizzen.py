"""Unterrichtsbesuche: Skizzen / Handschrift an Einträgen.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-01

Je Eintrag die Striche als JSON (zum Weiterzeichnen) und das daraus
gerenderte Bild (für Verlauf und Protokoll).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

def _spalten(insp) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns("ub_eintraege")}
    except Exception:
        return set()


def upgrade() -> None:
    vorhanden = _spalten(sa.inspect(op.get_bind()))
    with op.batch_alter_table("ub_eintraege") as b:
        if "skizze_json" not in vorhanden:
            b.add_column(sa.Column("skizze_json", sa.Text, server_default=""))
        if "skizze_uuid" not in vorhanden:
            b.add_column(sa.Column("skizze_uuid", sa.String(32), server_default=""))
        if "skizze_filename" not in vorhanden:
            b.add_column(sa.Column("skizze_filename", sa.String(255), server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("ub_eintraege") as b:
        for name in ("skizze_filename", "skizze_uuid", "skizze_json"):
            b.drop_column(name)
