"""Aufgabe-Nummer unique pro Arbeitsblatt (statt pro Lernsituation)

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-09

Bisheriger Unique-Index ix_ls_aufgaben_ls_nummer macht
(learning_situation_id, nummer) eindeutig — verhindert, dass eine LS
mehrere Arbeitsblätter mit jeweils 'Aufgabe 1' hat. Wir wechseln auf
Eindeutigkeit pro Arbeitsblatt (arbeitsblatt_id, nummer), damit jedes
Arbeitsblatt seine eigene Aufgaben-Nummerierung ab 1 starten kann
(passt zum v3-Vorlagen-Layout). v2-Aufgaben mit arbeitsblatt_id IS NULL
bleiben unrestringiert; die Reihenfolge regelt dort der App-Code.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in insp.get_indexes("ls_aufgaben")}
    if "ix_ls_aufgaben_ls_nummer" in existing_indexes:
        op.drop_index("ix_ls_aufgaben_ls_nummer", table_name="ls_aufgaben")
    if "ix_ls_aufgaben_ab_nummer" not in existing_indexes:
        # Partial Unique-Index (SQLite + PostgreSQL unterstützen das).
        # Nur greift für Aufgaben, die zu einem konkreten Arbeitsblatt
        # gehören — v2-Datenbestand (arbeitsblatt_id IS NULL) bleibt
        # unangetastet.
        op.create_index(
            "ix_ls_aufgaben_ab_nummer", "ls_aufgaben",
            ["arbeitsblatt_id", "nummer"],
            unique=True,
            sqlite_where=sa.text("arbeitsblatt_id IS NOT NULL"),
            postgresql_where=sa.text("arbeitsblatt_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in insp.get_indexes("ls_aufgaben")}
    if "ix_ls_aufgaben_ab_nummer" in existing_indexes:
        op.drop_index("ix_ls_aufgaben_ab_nummer", table_name="ls_aufgaben")
    if "ix_ls_aufgaben_ls_nummer" not in existing_indexes:
        op.create_index("ix_ls_aufgaben_ls_nummer", "ls_aufgaben",
                        ["learning_situation_id", "nummer"], unique=True)
