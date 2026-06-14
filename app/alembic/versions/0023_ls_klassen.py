"""Multi-Klassen-Zuordnung pro LS (Schema v4).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-15

Idempotente Migration. Legt die neue Tabelle `ls_klassen` an und
übernimmt jeden bestehenden `learning_situations.klassen_key` als ersten
Eintrag (sofern nicht leer). Der String-Spalte `klassen_key` an der LS
bleibt erhalten (Anzeige + Bestands-Kompatibilität); die Multi-Sicht
ist additiv.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, "ls_klassen"):
        op.create_table(
            "ls_klassen",
            sa.Column("learning_situation_id", sa.Integer(),
                      sa.ForeignKey("learning_situations.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("klassen_key", sa.String(255), primary_key=True),
        )

    # Bestand übernehmen: jede LS mit nicht-leerem klassen_key bekommt
    # einen ls_klassen-Eintrag (falls noch nicht da).
    rows = bind.execute(sa.text(
        "SELECT id, klassen_key FROM learning_situations "
        "WHERE COALESCE(klassen_key, '') <> ''"
    )).fetchall()
    for ls_id, kk in rows:
        bind.execute(sa.text(
            "INSERT OR IGNORE INTO ls_klassen "
            "(learning_situation_id, klassen_key) VALUES (:ls, :kk)"
        ), {"ls": ls_id, "kk": kk})


def downgrade() -> None:
    try:
        op.drop_table("ls_klassen")
    except Exception:
        pass
