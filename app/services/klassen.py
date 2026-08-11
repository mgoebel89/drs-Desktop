"""Klassenmodul — die tägliche Arbeitsansicht auf Klassen und Schüler.

Abgrenzung zu den Stammdaten: Dort werden Klassen **gepflegt** (anlegen,
umbenennen, versetzen, stilllegen). Hier wird mit ihnen **gearbeitet** —
Schüler-Notizen, Bewertungsstand, anstehende Prüfungen. Beide Seiten lesen
dieselben Tabellen; es gibt keine zweite Wahrheit.

Die Übersicht baut ihre Kennzahlen in wenigen Sammelabfragen auf statt je
Klasse eine — bei zehn Klassen mit je 25 Schülern wären das sonst schnell
dreistellig viele Queries.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Exam, ExamStudent, Student, StudentNotiz, TtJahrgang,
                        TtKlasse, TtLerngruppeKlasse, TtSchulklasse, User)

# Die Kategorien einer Schüler-Notiz. Schlüssel wandert in die DB, Label in die
# Oberfläche, `farbe` steuert die Pille. Eine Stelle — Router, Template und JS
# beziehen sich alle hierauf.
KATEGORIEN: dict[str, dict[str, str]] = {
    "beobachtung":  {"label": "Beobachtung",  "farbe": "neutral"},
    "gespraech":    {"label": "Gespräch",     "farbe": "blau"},
    "positiv":      {"label": "Positiv",      "farbe": "gruen"},
    "vereinbarung": {"label": "Vereinbarung", "farbe": "gelb"},
    "fehlzeit":     {"label": "Fehlzeit",     "farbe": "rot"},
}
STANDARD_KATEGORIE = "beobachtung"


def kategorie_label(key: str) -> str:
    return KATEGORIEN.get(key, KATEGORIEN[STANDARD_KATEGORIE])["label"]


def normalize_kategorie(key: str | None) -> str:
    k = (key or "").strip()
    return k if k in KATEGORIEN else STANDARD_KATEGORIE


def meine_klassen(db: Session, user: User) -> list[TtSchulklasse]:
    """Klassen für die Übersicht: aktive Klassen aus aktiven Jahrgängen.

    Der Jahrgang-Join ist dasselbe Sicherheitsnetz wie in den Stammdaten —
    ein abgeschlossener Jahrgang soll verschwinden, auch wenn an einer alten
    Klasse noch `active=True` steht."""
    return list(db.scalars(
        select(TtSchulklasse)
        .outerjoin(TtJahrgang, TtJahrgang.id == TtSchulklasse.jahrgang_id)
        .where(TtSchulklasse.user_id == user.id,
               TtSchulklasse.active.is_(True),
               (TtJahrgang.id.is_(None)) | (TtJahrgang.active.is_(True)))
        .order_by(TtSchulklasse.position, TtSchulklasse.name)
    ).all())


def lerngruppen_der_klasse(db: Session, user: User,
                           schulklasse_id: int) -> list[TtKlasse]:
    """Alle Lerngruppen, in denen diese Klasse steckt — die 1:1-Gruppe genauso
    wie Kombi-Gruppen. Über sie hängen die Prüfungen an der Klasse."""
    return list(db.scalars(
        select(TtKlasse)
        .join(TtLerngruppeKlasse,
              TtLerngruppeKlasse.lerngruppe_id == TtKlasse.id)
        .where(TtLerngruppeKlasse.schulklasse_id == schulklasse_id,
               TtKlasse.user_id == user.id)
        .order_by(TtKlasse.position, TtKlasse.klassen_key)
    ).all())


def uebersicht(db: Session, user: User) -> list[dict]:
    """Kacheldaten je Klasse: Schülerzahl, Notizen, nächste Prüfung."""
    klassen = meine_klassen(db, user)
    if not klassen:
        return []
    ids = [k.id for k in klassen]

    schueler_zahl = dict(db.execute(
        select(Student.schulklasse_id, func.count(Student.id))
        .where(Student.owner_user_id == user.id,
               Student.schulklasse_id.in_(ids),
               Student.active.is_(True))
        .group_by(Student.schulklasse_id)
    ).all())

    # Notizen hängen am Schüler; für die Kachel interessiert die Summe je Klasse
    # und wann zuletzt etwas notiert wurde.
    notiz_zahl: dict[int, int] = {}
    notiz_letzte: dict[int, str] = {}
    for kid, anzahl, letztes in db.execute(
        select(Student.schulklasse_id, func.count(StudentNotiz.id),
               func.max(StudentNotiz.datum))
        .join(StudentNotiz, StudentNotiz.student_id == Student.id)
        .where(StudentNotiz.owner_user_id == user.id,
               Student.schulklasse_id.in_(ids))
        .group_by(Student.schulklasse_id)
    ).all():
        notiz_zahl[kid] = anzahl
        notiz_letzte[kid] = letztes or ""

    heute = date.today().isoformat()
    naechste = _naechste_pruefungen(db, user, ids, heute)

    out = []
    for k in klassen:
        out.append({
            "klasse": k,
            "jahrgang": k.jahrgang.name if k.jahrgang else "",
            "schueler": schueler_zahl.get(k.id, 0),
            "notizen": notiz_zahl.get(k.id, 0),
            "letzte_notiz": notiz_letzte.get(k.id, ""),
            "naechste_pruefung": naechste.get(k.id),
        })
    return out


def _naechste_pruefungen(db: Session, user: User, klassen_ids: list[int],
                         ab_datum: str) -> dict[int, Exam]:
    """Je Klasse die nächste anstehende Prüfung (heute oder später).

    Der Weg führt über die Lerngruppen: Eine Prüfung kennt keine Schulklasse,
    sondern eine Lerngruppe — und eine Kombi-Lerngruppe zählt für jede
    beteiligte Klasse."""
    zuordnung: dict[int, list[int]] = {}   # lerngruppe_id -> [schulklasse_id]
    for lg_id, kid in db.execute(
        select(TtLerngruppeKlasse.lerngruppe_id,
               TtLerngruppeKlasse.schulklasse_id)
        .where(TtLerngruppeKlasse.schulklasse_id.in_(klassen_ids))
    ).all():
        zuordnung.setdefault(lg_id, []).append(kid)
    if not zuordnung:
        return {}

    rows = db.scalars(
        select(Exam)
        .where(Exam.owner_user_id == user.id,
               Exam.lerngruppe_id.in_(list(zuordnung.keys())),
               Exam.datum >= ab_datum)
        .order_by(Exam.datum)
    ).all()
    out: dict[int, Exam] = {}
    for ex in rows:
        for kid in zuordnung.get(ex.lerngruppe_id or 0, []):
            out.setdefault(kid, ex)   # sortiert → der erste Treffer gewinnt
    return out


def notiz_kennzahlen(db: Session, user: User,
                     student_ids: list[int]) -> dict[int, dict]:
    """Anzahl + jüngstes Datum der Notizen je Schüler (eine Abfrage)."""
    if not student_ids:
        return {}
    out: dict[int, dict] = {}
    for sid, anzahl, letztes in db.execute(
        select(StudentNotiz.student_id, func.count(StudentNotiz.id),
               func.max(StudentNotiz.datum))
        .where(StudentNotiz.owner_user_id == user.id,
               StudentNotiz.student_id.in_(student_ids))
        .group_by(StudentNotiz.student_id)
    ).all():
        out[sid] = {"anzahl": anzahl, "letzte": letztes or ""}
    return out


def notizen(db: Session, user: User, student_id: int) -> list[StudentNotiz]:
    """Zeitleiste eines Schülers, jüngste zuerst. Einträge ohne Datum stehen
    oben — sie sind gerade erst entstanden und wollen gefüllt werden."""
    return list(db.scalars(
        select(StudentNotiz)
        .where(StudentNotiz.owner_user_id == user.id,
               StudentNotiz.student_id == student_id)
        .order_by(StudentNotiz.datum.desc(), StudentNotiz.id.desc())
    ).all())


def notiz_dict(n: StudentNotiz) -> dict:
    return {
        "id": n.id,
        "datum": n.datum or "",
        "kategorie": n.kategorie or STANDARD_KATEGORIE,
        "kategorie_label": kategorie_label(n.kategorie or ""),
        "farbe": KATEGORIEN.get(n.kategorie or "",
                                KATEGORIEN[STANDARD_KATEGORIE])["farbe"],
        "text": n.text or "",
    }


def bewertungen(db: Session, user: User, student: Student) -> list[dict]:
    """Prüfungen, an denen dieser Schüler teilgenommen hat — mit Endnote.

    Die Note kommt aus `exam_scoring`, also aus derselben Rechnung wie im
    Bewertungsbogen. Import steht hier unten, weil `exam_scoring` seinerseits
    Modelle lädt und der Kreis sonst beim Modul-Import zuschnappen könnte."""
    from app.services import exam_scoring

    rows = db.execute(
        select(Exam, ExamStudent.group_label)
        .join(ExamStudent, ExamStudent.exam_id == Exam.id)
        .where(ExamStudent.student_id == student.id,
               Exam.owner_user_id == user.id)
        .order_by(Exam.datum.desc(), Exam.id.desc())
    ).all()

    out = []
    for ex, gruppe in rows:
        ctx = exam_scoring.scoring_ctx(db, user, ex)
        n_filled, pct, note = exam_scoring.student_total(
            ctx, student.id, gruppe or "")
        out.append({
            "id": ex.id,
            "titel": ex.title,
            "datum": ex.datum or "",
            "bewertet": n_filled > 0,
            "prozent": round(pct, 1) if n_filled else None,
            "note": note or "",
        })
    return out
