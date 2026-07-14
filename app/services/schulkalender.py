"""Schulkalender: unterrichtsfreie Tage.

Zwei Quellen:
- **Gesetzliche Feiertage Rheinland-Pfalz** werden berechnet (die beweglichen über
  die Osterformel). Sie stehen bewusst NICHT in der Datenbank — sonst müsste sie
  jemand jedes Jahr nachpflegen.
- **Ferien und bewegliche Ferientage** pflegt der Lehrer selbst als Zeiträume
  (`tt_holidays`), weil die je Schule und Jahr verschieden sind.

An einem freien Tag findet kein Unterricht statt: Der Stundenplan überspringt
dort die Zeilen des Grundstundenplans.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TtHoliday, TtSchoolyear, User


def easter_sunday(year: int) -> date:
    """Ostersonntag nach der anonymen gregorianischen Osterformel
    (Meeus/Jones/Butcher). Basis aller beweglichen Feiertage."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    li = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * li) // 451
    month, day = divmod(h + li - 7 * m + 114, 31)
    return date(year, month, day + 1)


def feiertage_rlp(year: int) -> dict[date, str]:
    """Gesetzliche Feiertage in Rheinland-Pfalz für ein Kalenderjahr.

    Oster- und Pfingstsonntag sind Sonntage und für ein Mo–Fr-Raster irrelevant,
    darum nicht enthalten."""
    ostern = easter_sunday(year)
    return {
        date(year, 1, 1): "Neujahr",
        ostern - timedelta(days=2): "Karfreitag",
        ostern + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        ostern + timedelta(days=39): "Christi Himmelfahrt",
        ostern + timedelta(days=50): "Pfingstmontag",
        ostern + timedelta(days=60): "Fronleichnam",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 11, 1): "Allerheiligen",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
    }


def free_days_for_range(db: Session, user: User,
                        start: date, end: date) -> dict[date, str]:
    """Alle unterrichtsfreien Tage im Zeitraum (inklusiv) mit ihrer Bezeichnung.

    Ferien und Feiertage können sich überlappen — der gesetzliche Feiertag
    gewinnt bei der Beschriftung, weil er der konkretere Grund ist."""
    frei: dict[date, str] = {}

    # Ferien / bewegliche Ferientage: alle Einträge, die den Zeitraum berühren
    rows = db.scalars(
        select(TtHoliday).where(
            TtHoliday.user_id == user.id,
            TtHoliday.start_date <= end.isoformat(),
            TtHoliday.end_date >= start.isoformat(),
        )
    ).all()
    for h in rows:
        try:
            h_start = date.fromisoformat(h.start_date)
            h_end = date.fromisoformat(h.end_date)
        except ValueError:
            continue
        tag = max(h_start, start)
        letzter = min(h_end, end)
        while tag <= letzter:
            frei[tag] = h.name or ("Ferien" if h.kind == "ferien" else "frei")
            tag += timedelta(days=1)

    # Gesetzliche Feiertage der berührten Kalenderjahre
    for jahr in range(start.year, end.year + 1):
        for tag, name in feiertage_rlp(jahr).items():
            if start <= tag <= end:
                frei[tag] = name

    return frei


def is_free(db: Session, user: User, d: date) -> tuple[bool, str]:
    frei = free_days_for_range(db, user, d, d)
    return (d in frei), frei.get(d, "")


def schoolyear_for(db: Session, user: User, d: date) -> TtSchoolyear | None:
    """Das Schuljahr, in dessen Zeitraum der Tag liegt. Ohne Treffer: das
    zuletzt angelegte (damit die A/B-Regel auch außerhalb greift)."""
    iso = d.isoformat()
    sy = db.scalars(
        select(TtSchoolyear).where(
            TtSchoolyear.user_id == user.id,
            TtSchoolyear.first_day <= iso,
            TtSchoolyear.last_day >= iso,
        )
    ).first()
    if sy:
        return sy
    return db.scalars(
        select(TtSchoolyear).where(TtSchoolyear.user_id == user.id)
        .order_by(TtSchoolyear.first_day.desc())
    ).first()


def ab_for_week(monday: date, parity: str) -> str:
    """A oder B für die Woche dieses Montags.

    Regel: `parity='even'` heißt „A-Woche ist eine gerade Kalenderwoche".
    Achtung, gewollte Eigenheit: Von KW 53 auf KW 1 sind beide ungerade — dort
    folgen zwei gleichnamige Wochen aufeinander. Die Vorschau in den
    Einstellungen macht das sichtbar."""
    kw = monday.isocalendar().week
    gerade = kw % 2 == 0
    if parity == "odd":
        return "A" if not gerade else "B"
    return "A" if gerade else "B"


def halbjahr_for(sy: TtSchoolyear | None, d: date) -> int:
    """1 oder 2 — rein informativ für die Anzeige."""
    if not sy or not sy.halfyear_split:
        return 0
    return 2 if d.isoformat() >= sy.halfyear_split else 1
