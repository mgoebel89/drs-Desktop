"""LS Schema v4: Auftrag, Lernfelder M2M, Anhänge-Kategorien, Stunden-Budget, Moodle

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-10

Idempotente Migration (wie 0015/0016/0020):
- Neue Spalten an learning_situations (auftrag_md, auftrag_bild_path,
  fachliche_praezisierung_md, moodle_course_id, moodle_last_pushed_at)
- Neue Spalten an ls_arbeitsblaetter (phasen, stunden_geplant,
  moodle_chapter_id)
- Neue Tabellen: lernfelder, ls_lernfelder, ls_attachments
- Bestands-Migration: für jede LS mit nicht-leerem `lernfeld`-String
  einen passenden Lernfeld-Datensatz anlegen (oder wiederverwenden) und
  per M2M verknüpfen. Der String an LS bleibt vorerst erhalten —
  Entfernung in einer Folge-Migration, wenn die UI komplett auf M2M
  umgestellt ist.
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _existing_columns(insp, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _table_exists(insp, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


_LF_NUM_RE = re.compile(r"(?:LF|Lernfeld)\s*(\d+)", re.IGNORECASE)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. learning_situations: neue Spalten
    ls_cols = _existing_columns(insp, "learning_situations")
    ls_additions: list[sa.Column] = []
    if "auftrag_md" not in ls_cols:
        ls_additions.append(sa.Column(
            "auftrag_md", sa.Text(), nullable=False, server_default=""))
    if "auftrag_bild_path" not in ls_cols:
        ls_additions.append(sa.Column(
            "auftrag_bild_path", sa.String(500),
            nullable=False, server_default=""))
    if "fachliche_praezisierung_md" not in ls_cols:
        ls_additions.append(sa.Column(
            "fachliche_praezisierung_md", sa.Text(),
            nullable=False, server_default=""))
    if "moodle_course_id" not in ls_cols:
        ls_additions.append(sa.Column(
            "moodle_course_id", sa.Integer(), nullable=True))
    if "moodle_last_pushed_at" not in ls_cols:
        ls_additions.append(sa.Column(
            "moodle_last_pushed_at", sa.DateTime(), nullable=True))
    if ls_additions:
        with op.batch_alter_table("learning_situations") as batch:
            for col in ls_additions:
                batch.add_column(col)

    # 2. ls_arbeitsblaetter: neue Spalten
    ab_cols = _existing_columns(insp, "ls_arbeitsblaetter")
    ab_additions: list[sa.Column] = []
    if "phasen" not in ab_cols:
        ab_additions.append(sa.Column(
            "phasen", sa.String(128), nullable=False, server_default=""))
    if "stunden_geplant" not in ab_cols:
        ab_additions.append(sa.Column(
            "stunden_geplant", sa.Integer(), nullable=False, server_default="0"))
    if "moodle_chapter_id" not in ab_cols:
        ab_additions.append(sa.Column(
            "moodle_chapter_id", sa.Integer(), nullable=True))
    if ab_additions:
        with op.batch_alter_table("ls_arbeitsblaetter") as batch:
            for col in ab_additions:
                batch.add_column(col)

    # 3. Tabelle: lernfelder
    if not _table_exists(insp, "lernfelder"):
        op.create_table(
            "lernfelder",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("beruf_key", sa.String(64),
                      nullable=False, server_default=""),
            sa.Column("nummer", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("titel", sa.String(255),
                      nullable=False, server_default=""),
            sa.Column("stunden_lehrplan", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(),
                      nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_lernfelder_user_beruf_nr",
            "lernfelder", ["user_id", "beruf_key", "nummer"])

    # 4. Tabelle: ls_lernfelder (M2M)
    if not _table_exists(insp, "ls_lernfelder"):
        op.create_table(
            "ls_lernfelder",
            sa.Column("learning_situation_id", sa.Integer(),
                      sa.ForeignKey("learning_situations.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("lernfeld_id", sa.Integer(),
                      sa.ForeignKey("lernfelder.id", ondelete="CASCADE"),
                      primary_key=True),
        )

    # 5. Tabelle: ls_attachments
    if not _table_exists(insp, "ls_attachments"):
        op.create_table(
            "ls_attachments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("learning_situation_id", sa.Integer(),
                      sa.ForeignKey("learning_situations.id",
                                    ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("kategorie", sa.String(32),
                      nullable=False, server_default="sonstiges"),
            sa.Column("dateiname", sa.String(255),
                      nullable=False, server_default=""),
            sa.Column("smb_relpath", sa.String(500),
                      nullable=False, server_default=""),
            sa.Column("mime_type", sa.String(120),
                      nullable=False, server_default=""),
            sa.Column("position", sa.Integer(),
                      nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(),
                      nullable=False, server_default=sa.func.now()),
        )

    # 6. Bestands-Migration: lernfeld-String → Lernfeld + M2M
    # Pro (user_id, normalisierter Titel) ein Lernfeld-Datensatz. Wenn
    # der String "LF 5" enthält, wird die Nummer extrahiert.
    bind.execute(sa.text("""
        SELECT id, user_id, lernfeld FROM learning_situations
         WHERE COALESCE(lernfeld, '') <> ''
    """))
    rows = bind.execute(sa.text(
        "SELECT id, user_id, lernfeld FROM learning_situations "
        "WHERE COALESCE(lernfeld, '') <> ''"
    )).fetchall()
    cache: dict[tuple[int, str], int] = {}
    for ls_id, user_id, lf_str in rows:
        titel = (lf_str or "").strip()
        if not titel:
            continue
        norm = titel.lower()
        key = (int(user_id), norm)
        lf_id = cache.get(key)
        if lf_id is None:
            existing = bind.execute(sa.text(
                "SELECT id FROM lernfelder WHERE user_id = :uid "
                "AND LOWER(titel) = :t LIMIT 1"
            ), {"uid": user_id, "t": norm}).first()
            if existing:
                lf_id = int(existing[0])
            else:
                nummer = 0
                m = _LF_NUM_RE.search(titel)
                if m:
                    try:
                        nummer = int(m.group(1))
                    except ValueError:
                        nummer = 0
                ins = bind.execute(sa.text(
                    "INSERT INTO lernfelder (user_id, beruf_key, nummer, titel) "
                    "VALUES (:uid, '', :n, :t)"
                ), {"uid": user_id, "n": nummer, "t": titel})
                lf_id = int(ins.lastrowid) if hasattr(ins, "lastrowid") and ins.lastrowid else None
                if lf_id is None:
                    # Fallback (z. B. Postgres ohne lastrowid)
                    lf_id = int(bind.execute(sa.text(
                        "SELECT id FROM lernfelder WHERE user_id = :uid "
                        "AND LOWER(titel) = :t ORDER BY id DESC LIMIT 1"
                    ), {"uid": user_id, "t": norm}).first()[0])
            cache[key] = lf_id
        # M2M-Eintrag idempotent setzen
        bind.execute(sa.text(
            "INSERT OR IGNORE INTO ls_lernfelder "
            "(learning_situation_id, lernfeld_id) VALUES (:ls, :lf)"
        ), {"ls": ls_id, "lf": lf_id})


def downgrade() -> None:
    # ls_attachments + ls_lernfelder + lernfelder droppen
    for tbl in ("ls_attachments", "ls_lernfelder", "lernfelder"):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
    # Arbeitsblatt-Spalten zurück
    with op.batch_alter_table("ls_arbeitsblaetter") as batch:
        for c in ("moodle_chapter_id", "stunden_geplant", "phasen"):
            try:
                batch.drop_column(c)
            except Exception:
                pass
    # LS-Spalten zurück
    with op.batch_alter_table("learning_situations") as batch:
        for c in ("moodle_last_pushed_at", "moodle_course_id",
                  "fachliche_praezisierung_md", "auftrag_bild_path",
                  "auftrag_md"):
            try:
                batch.drop_column(c)
            except Exception:
                pass
