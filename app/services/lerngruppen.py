"""Gemeinsame Abfragen rund um Jahrgang / Klasse / Lerngruppe.

Liegt bewusst als Service und nicht im Stammdaten-Router: Die Regeln „welche
Lerngruppen darf ich auswählen" und „welche Fächer gelten in dieser Lerngruppe"
brauchen auch der Grundstundenplan-Editor und der Ausnahmen-Dialog. Eine Regel,
eine Stelle.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Student, TtFach, TtJahrgang, TtJahrgangFach, TtKlasse,
                        TtLerngruppeKlasse, TtLerngruppeStudent, TtSchulklasse,
                        User)

ARTEN = ("klasse", "kombi", "gruppe")


def lerngruppen(db: Session, user: User, *,
                mit_inaktiven: bool = False) -> list[TtKlasse]:
    """Lerngruppen für die Auswahl im Stundenplan.

    Inaktiv ist eine Lerngruppe auch dann, wenn ihr Jahrgang stillgelegt wurde —
    ein abgeschlossener Jahrgang soll aus allen Pickern verschwinden, ohne dass
    man jede Gruppe einzeln abhaken muss. Vergangene Wochen rendern trotzdem
    weiter: das Grid liest die Stunden aus tt_rows bzw. den Snapshots, nicht aus
    dieser Liste.
    """
    q = (select(TtKlasse)
         .outerjoin(TtJahrgang, TtJahrgang.id == TtKlasse.jahrgang_id)
         .where(TtKlasse.user_id == user.id))
    if not mit_inaktiven:
        q = q.where(TtKlasse.active.is_(True),
                    (TtJahrgang.id.is_(None)) | (TtJahrgang.active.is_(True)))
    return list(db.scalars(q.order_by(TtKlasse.position, TtKlasse.klassen_key)).all())


def faecher_der_lerngruppe(db: Session, user: User,
                           lg: TtKlasse | None) -> tuple[list[TtFach], bool]:
    """Die im Stundenplan wählbaren Fächer einer Lerngruppe.

    Rückgabe: (Fächer, eingeschraenkt). `eingeschraenkt=False` heißt: Die
    Lerngruppe hängt an keinem Jahrgang oder der Jahrgang hat noch keine
    Lernfelder — dann gilt der volle Katalog, damit man sich nicht aussperrt.
    Die UI weist darauf hin.
    """
    if lg is not None and lg.jahrgang_id:
        rows = list(db.scalars(
            select(TtFach)
            .join(TtJahrgangFach, TtJahrgangFach.fach_id == TtFach.id)
            .where(TtJahrgangFach.jahrgang_id == lg.jahrgang_id,
                   TtFach.active.is_(True))
            .order_by(TtJahrgangFach.position, TtFach.display_name)
        ).all())
        if rows:
            return rows, True
    alle = list(db.scalars(
        select(TtFach).where(TtFach.user_id == user.id, TtFach.active.is_(True))
        .order_by(TtFach.position, TtFach.subjects_key)
    ).all())
    return alle, False


def schueler_der_lerngruppe(db: Session, user: User,
                            lg: TtKlasse) -> list[Student]:
    """Wer sitzt in dieser Lerngruppe? Bei 'gruppe' die ausgewählte Teilmenge,
    sonst alle Schüler der beteiligten Klassen."""
    if lg.art == "gruppe":
        return list(db.scalars(
            select(Student)
            .join(TtLerngruppeStudent, TtLerngruppeStudent.student_id == Student.id)
            .where(TtLerngruppeStudent.lerngruppe_id == lg.id,
                   Student.owner_user_id == user.id)
            .order_by(Student.nachname, Student.vorname)
        ).all())
    return list(db.scalars(
        select(Student)
        .join(TtSchulklasse, TtSchulklasse.id == Student.schulklasse_id)
        .join(TtLerngruppeKlasse,
              TtLerngruppeKlasse.schulklasse_id == TtSchulklasse.id)
        .where(TtLerngruppeKlasse.lerngruppe_id == lg.id,
               Student.owner_user_id == user.id, Student.active.is_(True))
        .order_by(Student.nachname, Student.vorname)
    ).all())


def klassen_der_lerngruppe(db: Session, lg: TtKlasse) -> list[TtSchulklasse]:
    return list(db.scalars(
        select(TtSchulklasse)
        .join(TtLerngruppeKlasse,
              TtLerngruppeKlasse.schulklasse_id == TtSchulklasse.id)
        .where(TtLerngruppeKlasse.lerngruppe_id == lg.id)
        .order_by(TtSchulklasse.position, TtSchulklasse.name)
    ).all())
