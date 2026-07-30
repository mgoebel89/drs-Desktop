"""Haushalt: Posten je Haushaltsjahr + Anschaffungsideen.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-30

Zwei getrennte Töpfe (`verwaltung` bis 999 €, `vermoegen` ab 1000 €). Beträge
liegen als Cent (Integer), damit Summen nicht driften. Nicht verausgabte
Mittel verfallen zum Jahresende — deshalb hängt jeder Posten an genau einem
Haushaltsjahr, es gibt keinen Übertrag.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def _has_table(insp, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_table(insp, "hh_posten"):
        op.create_table(
            "hh_posten",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
            sa.Column("jahr", sa.Integer(), index=True),
            sa.Column("art", sa.String(20), server_default="verwaltung"),
            sa.Column("bezeichnung", sa.String(200), server_default=""),
            sa.Column("betrag_cent", sa.Integer(), server_default="0"),
            sa.Column("notiz", sa.Text(), server_default=""),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not _has_table(insp, "hh_ideen"):
        op.create_table(
            "hh_ideen",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
            sa.Column("zieljahr", sa.Integer(), index=True),
            sa.Column("art", sa.String(20), server_default="verwaltung"),
            sa.Column("titel", sa.String(200), server_default=""),
            sa.Column("betrag_cent", sa.Integer(), server_default="0"),
            sa.Column("begruendung", sa.Text(), server_default=""),
            sa.Column("prioritaet", sa.Integer(), server_default="2"),
            sa.Column("status", sa.String(20), server_default="offen"),
            # Bewusst ohne DB-FK auf `vorgaenge`: die Tabelle entsteht erst in
            # 0032, und die App setzt `PRAGMA foreign_keys` ohnehin nie auf ON.
            sa.Column("vorgang_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    for t in ("hh_ideen", "hh_posten"):
        try:
            op.drop_table(t)
        except Exception:
            pass
