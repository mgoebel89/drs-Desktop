"""Manueller Stundenplan: Stammdaten, Zeitraster, Schuljahr, Versionen, Ausnahmen.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-14

Legt die tt_*-Tabellen an (idempotent) und füllt Klassen, Fächer und Zeitraster
aus dem Bestand vor.

Der Backfill ist der Kern dieser Migration: Alles im Stundenplan hängt an
    key4 = (lesson_date, klassen_key, subjects_key, block_start)
Die bisherigen Keys sind byte-genaue WebUntis-Strings. Übernehmen wir sie
unverändert als Stammdaten-Keys bzw. Slot-Startzeiten, stimmen die Schlüssel des
manuellen Plans per Konstruktion mit den vorhandenen Notizen überein — sonst
wären alle bisherigen Stundennotizen lautlos abgehängt.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def _plus_90_min(hhmm: str) -> str:
    """Heuristik für die Blockdauer beim Backfill (DRS: 90-Min-Blöcke).
    Im Zeitraster-Editor korrigierbar."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return ""
    total = (h * 60 + m + 90) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, "tt_slots"):
        op.create_table(
            "tt_slots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("name", sa.String(20), server_default=""),
            sa.Column("start_time", sa.String(5), nullable=False),
            sa.Column("end_time", sa.String(5), server_default=""),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "start_time",
                                name="uq_tt_slots_user_start"),
        )

    if not _table_exists(insp, "tt_klassen"):
        op.create_table(
            "tt_klassen",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("klassen_key", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(200), server_default=""),
            sa.Column("kuerzel", sa.String(40), server_default=""),
            sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "klassen_key",
                                name="uq_tt_klassen_user_key"),
        )

    if not _table_exists(insp, "tt_faecher"):
        op.create_table(
            "tt_faecher",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("subjects_key", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(200), server_default=""),
            sa.Column("kuerzel", sa.String(40), server_default=""),
            sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "subjects_key",
                                name="uq_tt_faecher_user_key"),
        )

    if not _table_exists(insp, "tt_schoolyears"):
        op.create_table(
            "tt_schoolyears",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(40), server_default=""),
            sa.Column("first_day", sa.String(10), server_default=""),
            sa.Column("last_day", sa.String(10), server_default=""),
            sa.Column("halfyear_split", sa.String(10), server_default=""),
            sa.Column("a_week_parity", sa.String(4), server_default="even"),
            sa.Column("created_at", sa.DateTime()),
        )

    if not _table_exists(insp, "tt_holidays"):
        op.create_table(
            "tt_holidays",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(120), server_default=""),
            sa.Column("start_date", sa.String(10), nullable=False, index=True),
            sa.Column("end_date", sa.String(10), nullable=False),
            sa.Column("kind", sa.String(16), server_default="ferien"),
            sa.Column("created_at", sa.DateTime()),
        )

    if not _table_exists(insp, "tt_versions"):
        op.create_table(
            "tt_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(80), server_default=""),
            sa.Column("valid_from", sa.String(10), nullable=False, index=True),
            sa.Column("note", sa.String(255), server_default=""),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "valid_from",
                                name="uq_tt_versions_user_from"),
        )

    if not _table_exists(insp, "tt_rows"):
        op.create_table(
            "tt_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("version_id", sa.Integer(),
                      sa.ForeignKey("tt_versions.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("block_start", sa.String(5), nullable=False),
            sa.Column("klasse_id", sa.Integer(),
                      sa.ForeignKey("tt_klassen.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("fach_id", sa.Integer(),
                      sa.ForeignKey("tt_faecher.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("raum", sa.String(60), server_default=""),
            sa.Column("rhythm", sa.String(4), server_default="all"),
            sa.Column("note", sa.String(200), server_default=""),
            sa.UniqueConstraint("version_id", "weekday", "block_start",
                                "klasse_id", "fach_id", "rhythm",
                                name="uq_tt_rows_slot"),
        )
        op.create_index("ix_tt_rows_version_weekday", "tt_rows",
                        ["version_id", "weekday"])

    if not _table_exists(insp, "tt_exceptions"):
        op.create_table(
            "tt_exceptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("lesson_date", sa.String(10), nullable=False, index=True),
            sa.Column("block_start", sa.String(5), nullable=False),
            sa.Column("klassen_key", sa.String(255), server_default=""),
            sa.Column("subjects_key", sa.String(255), server_default=""),
            sa.Column("snap_klassen_display", sa.String(200), server_default=""),
            sa.Column("snap_fach_display", sa.String(200), server_default=""),
            sa.Column("snap_raum", sa.String(60), server_default=""),
            sa.Column("target_date", sa.String(10), server_default="", index=True),
            sa.Column("target_block_start", sa.String(5), server_default=""),
            sa.Column("vertretung_name", sa.String(120), server_default=""),
            sa.Column("fach_text", sa.String(200), server_default=""),
            sa.Column("raum", sa.String(60), server_default=""),
            sa.Column("fuer_kollege", sa.String(120), server_default=""),
            sa.Column("grund", sa.String(255), server_default=""),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

    _backfill(bind)


def _backfill(bind) -> None:
    """Stammdaten + Zeitraster aus dem Bestand vorbefüllen, damit die key4 des
    manuellen Plans mit den vorhandenen Notizen zusammenpassen."""
    users = [r[0] for r in bind.execute(sa.text("SELECT id FROM users")).fetchall()]

    for uid in users:
        # Klassen aus den Stundennotizen (die Wahrheit über die alten Keys)
        klassen = bind.execute(sa.text(
            "SELECT DISTINCT klassen_key FROM lesson_notes "
            "WHERE user_id = :u AND COALESCE(klassen_key, '') <> ''"
        ), {"u": uid}).fetchall()
        for pos, kk in enumerate(sorted(row[0] for row in klassen)):
            bind.execute(sa.text(
                "INSERT OR IGNORE INTO tt_klassen "
                "(user_id, klassen_key, display_name, position, active) "
                "VALUES (:u, :k, :k, :p, 1)"
            ), {"u": uid, "k": kk, "p": pos})

        # Fächer — Anzeigename aus einem vorhandenen Reihen-Override, sonst der Key
        faecher = bind.execute(sa.text(
            "SELECT DISTINCT subjects_key FROM lesson_notes "
            "WHERE user_id = :u AND COALESCE(subjects_key, '') <> ''"
        ), {"u": uid}).fetchall()
        for pos, sk in enumerate(sorted(row[0] for row in faecher)):
            ov = bind.execute(sa.text(
                "SELECT display_name FROM lesson_series_overrides "
                "WHERE user_id = :u AND subjects_key = :s "
                "AND COALESCE(display_name, '') <> '' LIMIT 1"
            ), {"u": uid, "s": sk}).fetchone()
            bind.execute(sa.text(
                "INSERT OR IGNORE INTO tt_faecher "
                "(user_id, subjects_key, display_name, position, active) "
                "VALUES (:u, :s, :d, :p, 1)"
            ), {"u": uid, "s": sk, "d": (ov[0] if ov else sk), "p": pos})

        # Zeitraster aus den Blockstartzeiten der Notizen. Leere block_start
        # (Notizen von vor Migration 0007) übersprungen — die tragen keinen Block.
        blocks = bind.execute(sa.text(
            "SELECT DISTINCT block_start FROM lesson_notes "
            "WHERE user_id = :u AND COALESCE(block_start, '') <> '' "
            "ORDER BY block_start"
        ), {"u": uid}).fetchall()
        for pos, bs in enumerate(row[0] for row in blocks):
            bind.execute(sa.text(
                "INSERT OR IGNORE INTO tt_slots "
                "(user_id, position, name, start_time, end_time) "
                "VALUES (:u, :p, :n, :s, :e)"
            ), {"u": uid, "p": pos, "n": f"Block {pos + 1}",
                "s": bs, "e": _plus_90_min(bs)})


def downgrade() -> None:
    for t in ("tt_exceptions", "tt_rows", "tt_versions", "tt_holidays",
              "tt_schoolyears", "tt_faecher", "tt_klassen", "tt_slots"):
        try:
            op.drop_table(t)
        except Exception:
            pass
