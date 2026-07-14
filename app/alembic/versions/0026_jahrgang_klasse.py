"""Stammdaten-Hierarchie: Jahrgang -> Klasse -> Schüler, Lerngruppen, Jahrgangs-Fächer.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-14

Trennt die zwei Rollen, die `tt_klassen` bisher vermischt hat:

  * Klasse (`tt_schulklassen`) = Behälter für Schüler. Umbenennbar, trägt kein key4.
  * Lerngruppe (`tt_klassen`, Tabelle bleibt) = was im Stundenplan steht und den
    UNVERÄNDERLICHEN `klassen_key` trägt. art = klasse | kombi | gruppe.

Damit sind MT23a, MT23b, das zusammengelegte MT23 und eine Teilgruppe vier
Lerngruppen mit vier eigenen Keys — ihre Stundennotizen können sich nie mischen.

`tt_klassen.klassen_key` wird hier NICHT angefasst und `lesson_notes` bekommt
keinen FK: die Brücke bleibt `klassen_key == tt_klassen.klassen_key`. Alles andere
würde die key4 der Vergangenheit brechen (siehe 0025).

Der Backfill RÄT den Jahrgang aus dem Klassennamen. Danach ist die Seite
„Zuordnung prüfen" (/stammdaten/zuordnung) da, um das zu korrigieren.
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def _has_column(insp, table: str, col: str) -> bool:
    try:
        return col in {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False


# "BSMT 23 a" -> Stamm "BSMT", Jahr "23", Zug "a"
_KLASSE_RE = re.compile(
    r"^\s*([A-Za-zÄÖÜäöüß.\-_ ]*?)\s*(\d{2,4})\s*([A-Za-z])?\s*$")


def jahrgang_aus_name(name: str) -> str:
    """Rät den Jahrgangsnamen aus einem Klassennamen ('BSMT 23 a' -> 'BSMT 23').

    Ohne erkennbaren Jahrgang wird der Name selbst zum Jahrgang — so geht nichts
    verloren, und der Lehrer sortiert es auf der Zuordnungs-Seite gerade.
    """
    m = _KLASSE_RE.match(name or "")
    if not m:
        return (name or "").strip()
    stamm = re.sub(r"\s+", " ", (m.group(1) or "").strip())
    jahr = m.group(2)
    return f"{stamm} {jahr}".strip()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, "tt_jahrgaenge"):
        op.create_table(
            "tt_jahrgaenge",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("kuerzel", sa.String(40), server_default=""),
            sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "name",
                                name="uq_tt_jahrgaenge_user_name"),
        )

    if not _table_exists(insp, "tt_schulklassen"):
        op.create_table(
            "tt_schulklassen",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("jahrgang_id", sa.Integer(),
                      sa.ForeignKey("tt_jahrgaenge.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("kuerzel", sa.String(40), server_default=""),
            sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("user_id", "name",
                                name="uq_tt_schulklassen_user_name"),
        )

    # Neue Spalten auf BESTEHENDEN Tabellen bewusst OHNE DB-seitigen FK:
    # SQLite kann per ALTER TABLE keinen Constraint anhängen, und `batch_alter_table`
    # würde tt_klassen neu aufbauen — worauf tt_rows zeigt. Die App setzt
    # `PRAGMA foreign_keys` ohnehin nie auf ON (siehe app/db.py), FKs sind hier
    # also reine Deklaration; aufgeräumt wird über die ORM-Kaskaden. Die
    # ForeignKey-Angaben stehen in models.py, damit die Relationships greifen.

    # tt_klassen wird zur Lerngruppe
    if not _has_column(insp, "tt_klassen", "jahrgang_id"):
        op.add_column("tt_klassen", sa.Column(
            "jahrgang_id", sa.Integer(), nullable=True))
    if not _has_column(insp, "tt_klassen", "art"):
        op.add_column("tt_klassen", sa.Column(
            "art", sa.String(10), server_default="klasse"))

    if not _table_exists(insp, "tt_lerngruppe_klassen"):
        op.create_table(
            "tt_lerngruppe_klassen",
            sa.Column("lerngruppe_id", sa.Integer(),
                      sa.ForeignKey("tt_klassen.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("schulklasse_id", sa.Integer(),
                      sa.ForeignKey("tt_schulklassen.id", ondelete="CASCADE"),
                      primary_key=True),
        )

    if not _table_exists(insp, "tt_lerngruppe_students"):
        op.create_table(
            "tt_lerngruppe_students",
            sa.Column("lerngruppe_id", sa.Integer(),
                      sa.ForeignKey("tt_klassen.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      primary_key=True),
        )

    if not _table_exists(insp, "tt_jahrgang_faecher"):
        op.create_table(
            "tt_jahrgang_faecher",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jahrgang_id", sa.Integer(),
                      sa.ForeignKey("tt_jahrgaenge.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("fach_id", sa.Integer(),
                      sa.ForeignKey("tt_faecher.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("stundenansatz", sa.Integer(), server_default="0"),
            sa.Column("zeitraum_von", sa.String(10), server_default=""),
            sa.Column("zeitraum_bis", sa.String(10), server_default=""),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.UniqueConstraint("jahrgang_id", "fach_id",
                                name="uq_tt_jgf_jahrgang_fach"),
        )

    # students: Klassen-Zugehörigkeit als FK. klassen_key bleibt daneben
    # bestehen (denormalisiert), damit exams/exam_md unverändert weiterlaufen.
    if not _has_column(insp, "students", "schulklasse_id"):
        op.add_column("students", sa.Column(
            "schulklasse_id", sa.Integer(), nullable=True))
    if not _has_column(insp, "students", "jahrgang_id"):
        op.add_column("students", sa.Column(
            "jahrgang_id", sa.Integer(), nullable=True))

    if not _table_exists(insp, "student_class_moves"):
        op.create_table(
            "student_class_moves",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("von_klasse_id", sa.Integer(),
                      sa.ForeignKey("tt_schulklassen.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("nach_klasse_id", sa.Integer(),
                      sa.ForeignKey("tt_schulklassen.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("von_name", sa.String(120), server_default=""),
            sa.Column("nach_name", sa.String(120), server_default=""),
            sa.Column("datum", sa.String(10), server_default=""),
            sa.Column("grund", sa.String(255), server_default=""),
            sa.Column("created_at", sa.DateTime()),
        )

    if not _has_column(insp, "exams", "lerngruppe_id"):
        op.add_column("exams", sa.Column(
            "lerngruppe_id", sa.Integer(), nullable=True))

    _backfill(bind)


def _backfill(bind) -> None:
    """Jahrgänge + Klassen aus dem Bestand ableiten. Keys bleiben unangetastet."""
    users = [r[0] for r in bind.execute(sa.text("SELECT id FROM users")).fetchall()]

    for uid in users:
        jahrgang_id: dict[str, int] = {}
        klasse_id: dict[str, int] = {}

        def hole_jahrgang(name: str) -> int:
            name = name.strip() or "Ohne Jahrgang"
            if name not in jahrgang_id:
                row = bind.execute(sa.text(
                    "SELECT id FROM tt_jahrgaenge WHERE user_id=:u AND name=:n"
                ), {"u": uid, "n": name}).fetchone()
                if row:
                    jahrgang_id[name] = row[0]
                else:
                    res = bind.execute(sa.text(
                        "INSERT INTO tt_jahrgaenge (user_id, name, position, active) "
                        "VALUES (:u, :n, :p, 1)"
                    ), {"u": uid, "n": name, "p": len(jahrgang_id)})
                    jahrgang_id[name] = res.lastrowid
            return jahrgang_id[name]

        def hole_klasse(name: str, jg: int) -> int:
            name = name.strip()
            if name not in klasse_id:
                row = bind.execute(sa.text(
                    "SELECT id FROM tt_schulklassen WHERE user_id=:u AND name=:n"
                ), {"u": uid, "n": name}).fetchone()
                if row:
                    klasse_id[name] = row[0]
                else:
                    res = bind.execute(sa.text(
                        "INSERT INTO tt_schulklassen "
                        "(user_id, jahrgang_id, name, position, active) "
                        "VALUES (:u, :j, :n, :p, 1)"
                    ), {"u": uid, "j": jg, "n": name, "p": len(klasse_id)})
                    klasse_id[name] = res.lastrowid
            return klasse_id[name]

        # 1) Bestehende tt_klassen sind ab jetzt Lerngruppen. Aus ihrem
        #    Anzeigenamen entstehen Jahrgang + Schulklasse(n).
        lerngruppen = bind.execute(sa.text(
            "SELECT id, klassen_key, display_name FROM tt_klassen WHERE user_id=:u"
        ), {"u": uid}).fetchall()

        for lg_id, kk, dn in lerngruppen:
            anzeige = (dn or kk or "").strip()
            # Kombi-Keys tragen die Teilklassen mit '|' getrennt (Untis-Erbe).
            teile = [t.strip() for t in anzeige.split("|") if t.strip()]
            art = "kombi" if len(teile) > 1 else "klasse"
            if not teile:
                continue

            jg = hole_jahrgang(jahrgang_aus_name(teile[0]))
            bind.execute(sa.text(
                "UPDATE tt_klassen SET jahrgang_id=:j, art=:a WHERE id=:i"
            ), {"j": jg, "a": art, "i": lg_id})

            for teil in teile:
                sk = hole_klasse(teil, hole_jahrgang(jahrgang_aus_name(teil)))
                bind.execute(sa.text(
                    "INSERT OR IGNORE INTO tt_lerngruppe_klassen "
                    "(lerngruppe_id, schulklasse_id) VALUES (:l, :s)"
                ), {"l": lg_id, "s": sk})

        # 2) Jahrgangs-Fächer aus den real unterrichteten Paaren ableiten.
        #    Quelle: Grundstundenplan-Zeilen + vorhandene Notizen.
        paare = bind.execute(sa.text(
            "SELECT DISTINCT k.id, r.fach_id FROM tt_rows r "
            "JOIN tt_klassen k ON k.id = r.klasse_id WHERE k.user_id=:u"
        ), {"u": uid}).fetchall()
        aus_notizen = bind.execute(sa.text(
            "SELECT DISTINCT k.id, f.id FROM lesson_notes n "
            "JOIN tt_klassen k ON k.user_id=n.user_id AND k.klassen_key=n.klassen_key "
            "JOIN tt_faecher f ON f.user_id=n.user_id AND f.subjects_key=n.subjects_key "
            "WHERE n.user_id=:u"
        ), {"u": uid}).fetchall()

        gesehen: set[tuple[int, int]] = set()
        for lg_id, fach_id in list(paare) + list(aus_notizen):
            jg = bind.execute(sa.text(
                "SELECT jahrgang_id FROM tt_klassen WHERE id=:i"
            ), {"i": lg_id}).fetchone()
            if not jg or not jg[0] or (jg[0], fach_id) in gesehen:
                continue
            gesehen.add((jg[0], fach_id))
            bind.execute(sa.text(
                "INSERT OR IGNORE INTO tt_jahrgang_faecher "
                "(jahrgang_id, fach_id, stundenansatz, position) "
                "VALUES (:j, :f, 0, :p)"
            ), {"j": jg[0], "f": fach_id, "p": len(gesehen)})

        # 3) Schüler an ihre Klasse hängen. Match über den alten klassen_key
        #    gegen den Namen der Schulklasse bzw. den Key der Lerngruppe.
        for sid, skey in bind.execute(sa.text(
            "SELECT id, klassen_key FROM students "
            "WHERE owner_user_id=:u AND COALESCE(klassen_key,'') <> ''"
        ), {"u": uid}).fetchall():
            row = bind.execute(sa.text(
                "SELECT id, jahrgang_id FROM tt_schulklassen "
                "WHERE user_id=:u AND name=:n"
            ), {"u": uid, "n": skey}).fetchone()
            if not row:
                # Schüler-Klassen, die im Stundenplan nie vorkamen: neu anlegen.
                jg = hole_jahrgang(jahrgang_aus_name(skey))
                kid = hole_klasse(skey, jg)
                row = (kid, jg)
            bind.execute(sa.text(
                "UPDATE students SET schulklasse_id=:k, jahrgang_id=:j WHERE id=:i"
            ), {"k": row[0], "j": row[1], "i": sid})


def downgrade() -> None:
    for t in ("student_class_moves", "tt_jahrgang_faecher",
              "tt_lerngruppe_students", "tt_lerngruppe_klassen",
              "tt_schulklassen", "tt_jahrgaenge"):
        try:
            op.drop_table(t)
        except Exception:
            pass
    for tbl, col in (("exams", "lerngruppe_id"),
                     ("students", "schulklasse_id"), ("students", "jahrgang_id"),
                     ("tt_klassen", "jahrgang_id"), ("tt_klassen", "art")):
        try:
            op.drop_column(tbl, col)
        except Exception:
            pass
