"""Vorgänge & Projekte: Behälter, getippte Zeitleiste, Empfänger-Gedächtnis.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-30

Die typ-spezifischen Felder eines Zeitleisten-Eintrags liegen als JSON in
`payload_json`; `betrag_cent` und `hh_posten_id` stehen als echte Spalten da,
weil die Budget-Auswertung über sie summiert.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def _has_table(insp, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_table(insp, "vorgaenge"):
        op.create_table(
            "vorgaenge",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
            sa.Column("titel", sa.String(250), server_default=""),
            sa.Column("beschreibung", sa.Text(), server_default=""),
            sa.Column("kategorie", sa.String(80), server_default=""),
            sa.Column("status", sa.String(20), server_default="geplant"),
            # Ohne DB-FK auf tt_klassen: SQLite kann FKs nicht nachrüsten, und
            # eine gelöschte Lerngruppe soll den Vorgang nicht mitreißen.
            sa.Column("lerngruppe_id", sa.Integer(), nullable=True),
            sa.Column("haushaltsjahr", sa.Integer(), server_default="0", index=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not _has_table(insp, "vorgang_eintraege"):
        op.create_table(
            "vorgang_eintraege",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("vorgang_id", sa.Integer(),
                      sa.ForeignKey("vorgaenge.id", ondelete="CASCADE"),
                      index=True),
            sa.Column("typ", sa.String(30), server_default="notiz", index=True),
            sa.Column("datum", sa.String(10), server_default="", index=True),
            sa.Column("payload_json", sa.Text(), server_default="{}"),
            sa.Column("betrag_cent", sa.Integer(), server_default="0"),
            sa.Column("hh_posten_id", sa.Integer(), nullable=True),
            sa.Column("erledigt", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not _has_table(insp, "vorgang_kontakte"):
        op.create_table(
            "vorgang_kontakte",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
            sa.Column("name", sa.String(120), server_default=""),
            sa.Column("last_used", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "name", name="uq_vorgang_kontakt"),
        )


def downgrade() -> None:
    for t in ("vorgang_kontakte", "vorgang_eintraege", "vorgaenge"):
        try:
            op.drop_table(t)
        except Exception:
            pass
