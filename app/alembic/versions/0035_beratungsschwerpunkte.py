"""Beratungsschwerpunkte: Schwerpunkte eines Besuchs werden eine Auswahl aus
dem Katalog in den Einstellungen (bisher `ub_kriterien`) statt Freitext.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-29

Datenübernahme aus Stufe 1: Jeder Freitext-Schwerpunkt wird einem
Katalogeintrag gleichen Namens zugeordnet (Groß-/Kleinschreibung und
Leerzeichen egal) oder als neuer Katalogeintrag angelegt. Einträge, die am
Freitext-Schwerpunkt hingen, zeigen danach auf den Katalogeintrag — es geht
keine Zuordnung verloren.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def _hat_spalte(insp, tab: str, spalte: str) -> bool:
    try:
        return spalte in {c["name"] for c in insp.get_columns(tab)}
    except Exception:
        return False


def _norm(t: str) -> str:
    return " ".join((t or "").split()).casefold()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not _hat_spalte(insp, "ub_schwerpunkte", "kriterium_id"):
        with op.batch_alter_table("ub_schwerpunkte") as b:
            b.add_column(sa.Column("kriterium_id", sa.Integer, nullable=True))
        op.create_index("ix_ub_schwerpunkte_kriterium_id", "ub_schwerpunkte", ["kriterium_id"])

    alt = bind.execute(sa.text(
        "SELECT s.id, s.besuch_id, s.text, b.user_id FROM ub_schwerpunkte s "
        "JOIN ub_besuche b ON b.id = s.besuch_id WHERE s.kriterium_id IS NULL "
        "ORDER BY s.besuch_id, s.position, s.id")).fetchall()
    if not alt:
        return

    katalog: dict[int, dict[str, int]] = {}
    naechste_pos: dict[int, int] = {}

    def katalog_von(uid: int) -> dict[str, int]:
        if uid not in katalog:
            zeilen = bind.execute(sa.text(
                "SELECT id, name, position FROM ub_kriterien WHERE user_id = :u"),
                {"u": uid}).fetchall()
            katalog[uid] = {_norm(n): i for i, n, _ in zeilen}
            naechste_pos[uid] = max([p or 0 for _, _, p in zeilen], default=-1) + 1
        return katalog[uid]

    gesehen: set[tuple[int, int]] = set()
    for sid, bid, text, uid in alt:
        kat = katalog_von(uid)
        schluessel = _norm(text)
        if not schluessel:
            bind.execute(sa.text("DELETE FROM ub_schwerpunkte WHERE id = :s"), {"s": sid})
            continue
        kid = kat.get(schluessel)
        if kid is None:
            bind.execute(sa.text(
                "INSERT INTO ub_kriterien (user_id, name, position, active) "
                "VALUES (:u, :n, :p, 1)"),
                {"u": uid, "n": " ".join(text.split())[:80], "p": naechste_pos[uid]})
            kid = bind.execute(sa.text("SELECT last_insert_rowid()")).scalar()
            kat[schluessel] = kid
            naechste_pos[uid] += 1
        bind.execute(sa.text(
            "UPDATE ub_eintraege SET kriterium_id = :k "
            "WHERE schwerpunkt_id = :s AND kriterium_id IS NULL"), {"k": kid, "s": sid})
        bind.execute(sa.text(
            "UPDATE ub_eintraege SET schwerpunkt_id = NULL WHERE schwerpunkt_id = :s"),
            {"s": sid})
        if (bid, kid) in gesehen:   # zweimal derselbe Name im selben Besuch
            bind.execute(sa.text("DELETE FROM ub_schwerpunkte WHERE id = :s"), {"s": sid})
        else:
            gesehen.add((bid, kid))
            bind.execute(sa.text(
                "UPDATE ub_schwerpunkte SET kriterium_id = :k WHERE id = :s"),
                {"k": kid, "s": sid})


def downgrade() -> None:
    try:
        op.drop_index("ix_ub_schwerpunkte_kriterium_id", table_name="ub_schwerpunkte")
    except Exception:
        pass
    with op.batch_alter_table("ub_schwerpunkte") as b:
        b.drop_column("kriterium_id")
