"""Unterrichtsbesuche: Anwärter, Besuche, Verlaufseinträge + frei pflegbare
Kategorien, Phasen und Kriterien.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-29

Das Schema deckt gleich beide Ausbaustufen ab (Reflexion, Vereinbarungen,
Bezug zwischen Einträgen, Standard-Ordnung), damit Stufe 2 ohne weitere
Migration auskommt.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def _has_table(insp, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _uid():
    return sa.Column("user_id", sa.Integer,
                     sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_table(insp, "ub_einstellungen"):
        op.create_table(
            "ub_einstellungen",
            sa.Column("user_id", sa.Integer,
                      sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("standard_ordnung", sa.String(20), server_default="chronologisch"),
        )

    if not _has_table(insp, "ub_kategorien"):
        op.create_table(
            "ub_kategorien",
            sa.Column("id", sa.Integer, primary_key=True),
            _uid(),
            sa.Column("name", sa.String(60), server_default=""),
            sa.Column("icon", sa.String(30), server_default="auge"),
            sa.Column("farbe", sa.String(7), server_default="#00639C"),
            sa.Column("spalte", sa.String(12), server_default="verlauf"),
            sa.Column("position", sa.Integer, server_default="0"),
            sa.Column("active", sa.Boolean, server_default=sa.true()),
        )
        op.create_index("ix_ub_kategorien_user_id", "ub_kategorien", ["user_id"])

    for tab, laenge in (("ub_phasen", 60), ("ub_kriterien", 80)):
        if not _has_table(insp, tab):
            op.create_table(
                tab,
                sa.Column("id", sa.Integer, primary_key=True),
                _uid(),
                sa.Column("name", sa.String(laenge), server_default=""),
                sa.Column("position", sa.Integer, server_default="0"),
                sa.Column("active", sa.Boolean, server_default=sa.true()),
            )
            op.create_index(f"ix_{tab}_user_id", tab, ["user_id"])

    if not _has_table(insp, "ub_anwaerter"):
        op.create_table(
            "ub_anwaerter",
            sa.Column("id", sa.Integer, primary_key=True),
            _uid(),
            sa.Column("name", sa.String(120), server_default=""),
            sa.Column("faecher", sa.String(200), server_default=""),
            sa.Column("seminar", sa.String(200), server_default=""),
            sa.Column("notiz", sa.Text, server_default=""),
            sa.Column("active", sa.Boolean, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime),
        )
        op.create_index("ix_ub_anwaerter_user_id", "ub_anwaerter", ["user_id"])

    if not _has_table(insp, "ub_besuche"):
        op.create_table(
            "ub_besuche",
            sa.Column("id", sa.Integer, primary_key=True),
            _uid(),
            sa.Column("anwaerter_id", sa.Integer,
                      sa.ForeignKey("ub_anwaerter.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("datum", sa.String(10), server_default=""),
            sa.Column("beginn", sa.String(5), server_default=""),
            sa.Column("ende", sa.String(5), server_default=""),
            sa.Column("klasse", sa.String(80), server_default=""),
            sa.Column("raum", sa.String(40), server_default=""),
            sa.Column("thema", sa.String(300), server_default=""),
            sa.Column("lernziele", sa.Text, server_default=""),
            sa.Column("status", sa.String(16), server_default="geplant"),
            sa.Column("reflexion", sa.Text, server_default=""),
            sa.Column("vereinbarungen", sa.Text, server_default=""),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
        )
        op.create_index("ix_ub_besuche_user_id", "ub_besuche", ["user_id"])
        op.create_index("ix_ub_besuche_anwaerter_id", "ub_besuche", ["anwaerter_id"])
        op.create_index("ix_ub_besuche_datum", "ub_besuche", ["datum"])

    if not _has_table(insp, "ub_schwerpunkte"):
        op.create_table(
            "ub_schwerpunkte",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("besuch_id", sa.Integer,
                      sa.ForeignKey("ub_besuche.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("text", sa.String(300), server_default=""),
            sa.Column("position", sa.Integer, server_default="0"),
        )
        op.create_index("ix_ub_schwerpunkte_besuch_id", "ub_schwerpunkte", ["besuch_id"])

    if not _has_table(insp, "ub_eintraege"):
        op.create_table(
            "ub_eintraege",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("besuch_id", sa.Integer,
                      sa.ForeignKey("ub_besuche.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("art", sa.String(10), server_default="eintrag"),
            sa.Column("zeit", sa.String(5), server_default=""),
            sa.Column("position", sa.Integer, server_default="0"),
            sa.Column("phase_id", sa.Integer, nullable=True),
            sa.Column("kategorie_id", sa.Integer, nullable=True),
            sa.Column("text", sa.Text, server_default=""),
            sa.Column("kriterium_id", sa.Integer, nullable=True),
            sa.Column("schwerpunkt_id", sa.Integer, nullable=True),
            sa.Column("wertung", sa.String(12), server_default=""),
            sa.Column("bezug_id", sa.Integer, nullable=True),
            sa.Column("file_uuid", sa.String(32), server_default=""),
            sa.Column("filename", sa.String(255), server_default=""),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
        )
        op.create_index("ix_ub_eintraege_besuch_id", "ub_eintraege", ["besuch_id"])


def downgrade() -> None:
    for tab in ("ub_eintraege", "ub_schwerpunkte", "ub_besuche", "ub_anwaerter",
                "ub_kriterien", "ub_phasen", "ub_kategorien", "ub_einstellungen"):
        try:
            op.drop_table(tab)
        except Exception:
            pass
