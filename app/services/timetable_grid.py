"""Wochengrid des manuellen Stundenplans — der Ersatz für WebUntis.

Baut formatgleich dasselbe Dict, das früher `webuntis_client.get_week_grid()`
geliefert hat, nur aus der Datenbank statt aus Untis. Dadurch bleiben das
Template, die Notiz-Overlays im Router und der PDF-Pfad unverändert.

Auflösungsreihenfolge für eine Woche:
  Zeitraster → freie Tage (Ferien/Feiertage) → für jeden Tag die Version, die an
  diesem Tag gilt → deren Zeilen (nach A/B gefiltert) → einmalige Ausnahmen
  darüberlegen → iCal-Termine anhängen.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (TtException, TtFach, TtKlasse, TtRow, TtSlot, TtVersion,
                        User)
from app.services import schulkalender

WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr"]


# ── Stammdaten / Struktur ────────────────────────────────────────────────

def load_slots(db: Session, user: User) -> list[dict]:
    """Das Zeitraster als Block-Liste. `sub_starts` gibt es nur noch aus
    Kompatibilität zum Template — im manuellen Plan ist ein Block ein Block."""
    rows = db.scalars(
        select(TtSlot).where(TtSlot.user_id == user.id)
        .order_by(TtSlot.position, TtSlot.start_time)
    ).all()
    return [
        {"name": s.name or s.start_time, "start": s.start_time,
         "end": s.end_time or s.start_time, "sub_starts": [s.start_time]}
        for s in rows
    ]


def version_for_date(db: Session, user: User, d: date) -> TtVersion | None:
    """Die Version, die an diesem Tag gilt: die mit dem größten `valid_from`,
    das nicht in der Zukunft liegt. Damit rendert auch jede vergangene Woche
    automatisch mit der Version, die damals galt."""
    return db.scalars(
        select(TtVersion).where(
            TtVersion.user_id == user.id,
            TtVersion.valid_from <= d.isoformat(),
        ).order_by(TtVersion.valid_from.desc())
    ).first()


def ab_for_week(db: Session, user: User, monday: date) -> tuple[str, bool]:
    """(A|B|"", ob A/B überhaupt konfiguriert ist)."""
    sy = schulkalender.schoolyear_for(db, user, monday)
    if not sy:
        return "", False
    return schulkalender.ab_for_week(monday, sy.a_week_parity), True


def lesson_key_parts(lesson: dict) -> tuple[str, str]:
    """(klassen_key, subjects_key) für die Notiz-Zuordnung.

    Der manuelle Plan liefert die Keys direkt mit; der Fallback auf das
    sortierte Join bildet das alte Untis-Verhalten nach, damit auch
    Bestands-Lesson-Dicts weiterhin korrekt zugeordnet werden."""
    kk = lesson.get("klassen_key")
    sk = lesson.get("subjects_key")
    if kk is not None and sk is not None:
        return kk, sk
    return ("|".join(sorted(lesson.get("klassen") or [])),
            "|".join(sorted(lesson.get("subjects") or [])))


# ── Lesson-Dicts ─────────────────────────────────────────────────────────

def _iso(d: date, hhmm: str) -> str:
    """'YYYY-MM-DDTHH:MM:SS' — das Bestandsformat der Untis-Lessons."""
    return f"{d.isoformat()}T{hhmm or '00:00'}:00"


def _base_lesson(row: TtRow, klasse: TtKlasse, fach: TtFach,
                 d: date, slot_end: str) -> dict:
    kk = klasse.klassen_key
    sk = fach.subjects_key
    return {
        "id": f"row:{row.id}",
        "start": _iso(d, row.block_start),
        "end": _iso(d, slot_end),
        # Bestandsfelder — Template und PDF lesen sie
        "klassen": kk.split("|"),
        "klassen_long": [klasse.display_name or kk],
        "subjects": sk.split("|"),
        "subjects_long": [fach.display_name or sk],
        "rooms": [row.raum] if row.raum else [],
        "rooms_long": [row.raum] if row.raum else [],
        "code": None,
        "info": row.note or "",
        "lstext": "",
        # Neu: Keys explizit, kein Sort-Join mehr nötig
        "klassen_key": kk,
        "subjects_key": sk,
        "fach_display": fach.display_name or sk,
        "klassen_display": klasse.display_name or kk,
        "status": "regulaer",
        "rhythm": row.rhythm,
        "exception_id": None,
        "moved_to": None,
        "moved_from": None,
        "vertretung_name": "",
        "fuer_kollege": "",
        "grund": "",
    }


def _exception_lesson(exc: TtException, d: date, block_start: str,
                      slot_end: str, status: str) -> dict:
    """Lesson-Dict allein aus einer Ausnahme — für Zusatzstunden und für das
    Ziel einer Verschiebung. Nutzt die Snapshot-Felder, funktioniert also auch,
    wenn die zugrundeliegende Zeile inzwischen aus dem Plan verschwunden ist."""
    kk = exc.klassen_key
    sk = exc.subjects_key
    fach_disp = exc.snap_fach_display or exc.fach_text or sk
    raum = exc.raum or exc.snap_raum
    return {
        "id": f"exc:{exc.id}",
        "start": _iso(d, block_start),
        "end": _iso(d, slot_end),
        "klassen": kk.split("|") if kk else [],
        "klassen_long": [exc.snap_klassen_display or kk],
        "subjects": sk.split("|") if sk else [],
        "subjects_long": [fach_disp],
        "rooms": [raum] if raum else [],
        "rooms_long": [raum] if raum else [],
        "code": "irregular",
        "info": exc.grund or "",
        "lstext": "",
        "klassen_key": kk,
        "subjects_key": sk,
        "fach_display": fach_disp,
        "klassen_display": exc.snap_klassen_display or kk,
        "status": status,
        "rhythm": "all",
        "exception_id": exc.id,
        "moved_to": None,
        "moved_from": ({"date": exc.lesson_date,
                        "block_start": exc.block_start}
                       if status == "verlegt_hier" else None),
        "vertretung_name": "",
        "fuer_kollege": exc.fuer_kollege,
        "grund": exc.grund or "",
    }


# ── Wochengrid ───────────────────────────────────────────────────────────

def get_week_grid(db: Session, user: User, ref: date | None = None,
                  ical_events: list[dict] | None = None) -> dict:
    ref = ref or date.today()
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)

    slots = load_slots(db, user)
    frei = schulkalender.free_days_for_range(db, user, monday, friday)
    ab, ab_enabled = ab_for_week(db, user, monday)
    sy = schulkalender.schoolyear_for(db, user, monday)

    days = []
    for i in range(5):
        d = monday + timedelta(days=i)
        days.append({
            "date": d,
            "weekday_name": WEEKDAY_NAMES[i],
            "free": d in frei,
            "free_label": frei.get(d, ""),
        })

    slot_end = {s["start"]: s["end"] for s in slots}
    cells: dict[tuple[str, int], list[dict]] = {}
    versions: dict[int, TtVersion | None] = {i: None for i in range(5)}

    # Ohne Zeitraster gibt es keine Zeilen, an denen eine Stunde hängen könnte —
    # dann bleibt das Grid leer (setup_needed), statt Zellen zu bauen, die kein
    # Slot je rendert.
    if slots:
        # 1) Grundstundenplan — pro Tag die Version, die an diesem Tag gilt.
        for i, day in enumerate(days):
            if day["free"]:
                continue  # an freien Tagen kein Unterricht
            v = version_for_date(db, user, day["date"])
            versions[i] = v
            if not v:
                continue
            rows = db.scalars(
                select(TtRow).where(TtRow.version_id == v.id, TtRow.weekday == i)
                .order_by(TtRow.block_start)
            ).all()
            for row in rows:
                if row.rhythm != "all" and (not ab_enabled or row.rhythm != ab):
                    continue
                klasse = db.get(TtKlasse, row.klasse_id)
                fach = db.get(TtFach, row.fach_id)
                if not klasse or not fach:
                    continue
                cells.setdefault((row.block_start, i), []).append(
                    _base_lesson(row, klasse, fach, day["date"],
                                 slot_end.get(row.block_start, "")))

        # 2) Einmalige Ausnahmen darüberlegen. Auch Ziele von Verschiebungen
        #    holen, deren Quelle außerhalb dieser Woche liegt.
        mo_iso, fr_iso = monday.isoformat(), friday.isoformat()
        excs = db.scalars(
            select(TtException).where(
                TtException.user_id == user.id,
                or_(
                    TtException.lesson_date.between(mo_iso, fr_iso),
                    TtException.target_date.between(mo_iso, fr_iso),
                ),
            )
        ).all()
        for exc in excs:
            _apply_exception(exc, cells, days, monday, slot_end)

    result = {
        "monday": monday, "friday": friday,
        "days": days, "slots": slots, "cells": cells,
        "events": {}, "skip_cells": set(),
        "all_day_row": {}, "all_day_skip": set(),
        # Neu
        "kw": monday.isocalendar().week,
        "ab": ab,
        "ab_enabled": ab_enabled,
        "schoolyear": sy,
        "halbjahr": schulkalender.halbjahr_for(sy, monday),
        "versions": versions,
        "setup_needed": not slots,
        "no_version": bool(slots) and not any(versions.values()),
    }
    if ical_events:
        _attach_events(result, ical_events)
    return result


def _find_lesson(cells: dict, key: tuple[str, int],
                 kk: str, sk: str) -> dict | None:
    for l in cells.get(key, []):
        if l["klassen_key"] == kk and l["subjects_key"] == sk:
            return l
    return None


def _apply_exception(exc: TtException, cells: dict, days: list[dict],
                     monday: date, slot_end: dict) -> None:
    """Eine Ausnahme auf die Zellen anwenden.

    Findet sich die Basisstunde nicht (Zeile inzwischen aus dem Plan entfernt,
    oder freier Tag), werden Ausfall/Vertretung still ignoriert — das Ziel einer
    Verschiebung und eine Zusatzstunde werden trotzdem aus den Snapshots
    gerendert, sonst verschwände dokumentierter Unterricht."""
    try:
        quelle = date.fromisoformat(exc.lesson_date)
    except ValueError:
        return
    q_idx = (quelle - monday).days
    q_key = (exc.block_start, q_idx)
    in_woche = 0 <= q_idx <= 4

    if exc.kind == "zusatz":
        if in_woche and not days[q_idx]["free"]:
            cells.setdefault(q_key, []).append(_exception_lesson(
                exc, quelle, exc.block_start,
                slot_end.get(exc.block_start, ""), "zusatz"))
        return

    basis = _find_lesson(cells, q_key, exc.klassen_key, exc.subjects_key) \
        if in_woche else None

    if exc.kind == "ausfall":
        if basis:
            basis["status"] = "ausfall"
            basis["code"] = "cancelled"
            basis["exception_id"] = exc.id
            basis["grund"] = exc.grund or ""
        return

    if exc.kind == "vertretung":
        if basis:
            # BEWUSST nicht 'cancelled': das Template blendet bei cancelled die
            # Notiz-Icons aus, die Vertretungsstunde soll aber dokumentierbar
            # bleiben — der Stoff wurde ja behandelt.
            basis["status"] = "vertretung"
            basis["code"] = None
            basis["exception_id"] = exc.id
            basis["vertretung_name"] = exc.vertretung_name
            basis["grund"] = exc.grund or ""
        return

    if exc.kind == "verschiebung":
        if basis:
            basis["status"] = "verlegt_weg"
            basis["code"] = "cancelled"
            basis["exception_id"] = exc.id
            basis["grund"] = exc.grund or ""
            basis["moved_to"] = {"date": exc.target_date,
                                 "block_start": exc.target_block_start}
        # Ziel — kann in einer anderen Woche liegen als die Quelle
        try:
            ziel = date.fromisoformat(exc.target_date)
        except ValueError:
            return
        z_idx = (ziel - monday).days
        if not (0 <= z_idx <= 4):
            return
        l = _exception_lesson(exc, ziel, exc.target_block_start,
                              slot_end.get(exc.target_block_start, ""),
                              "verlegt_hier")
        cells.setdefault((exc.target_block_start, z_idx), []).append(l)


# ── iCal-Termine ─────────────────────────────────────────────────────────
# 1:1 aus webuntis_client portiert (dort Z. 308-405). Bewusst kopiert statt
# importiert, damit im Stundenplan-Pfad kein `import webuntis` mehr hängt.

def _attach_events(grid: dict, ical_events: list[dict]) -> None:
    """Hängt iCal-Events an das Grid an.

    - all_day_row:  dict[day_idx] -> list[event mit colspan]
    - all_day_skip: set[day_idx] (von Multi-Day-Balken überdeckt)
    - events:       dict[(slot_start, day_idx)] -> list[event mit rowspan]
    - skip_cells:   set[(slot_start, day_idx)] (von Event-rowspan überdeckt)
    """
    slots = grid["slots"]
    monday: date = grid["monday"]

    all_day_row: dict[int, list[dict]] = {}
    all_day_skip: set[int] = set()
    events_index: dict[tuple[str, int], list[dict]] = {}
    skip_cells: set[tuple[str, int]] = set()

    def _slot_dt(d: date, s_: str) -> datetime:
        h, m = s_.split(":")
        return datetime(d.year, d.month, d.day, int(h), int(m))

    # 1) Ganztägige Events
    for ev in ical_events:
        if not ev.get("all_day"):
            continue
        try:
            ev_start = datetime.fromisoformat(ev["start"]).date()
            ev_end = datetime.fromisoformat(ev["end"]).date()  # exklusiv
        except Exception:
            continue
        days_in_range = [i for i in range(5)
                         if ev_start <= monday + timedelta(days=i) < ev_end]
        if not days_in_range:
            continue
        first_idx = days_in_range[0]
        span = 1
        for j in range(1, len(days_in_range)):
            if days_in_range[j] == days_in_range[j - 1] + 1:
                span += 1
            else:
                break
        all_day_row.setdefault(first_idx, []).append({**ev, "colspan": span})
        for k in range(1, span):
            all_day_skip.add(first_idx + k)

    # 2) Zeitabhängige Events in der Event-Spur (rechte Sub-Spalte)
    if slots:
        for ev in ical_events:
            if ev.get("all_day"):
                continue
            try:
                ev_start_dt = datetime.fromisoformat(ev["start"])
                ev_end_dt = datetime.fromisoformat(ev["end"])
            except Exception:
                continue
            ev_date = ev_start_dt.date()
            day_idx = (ev_date - monday).days
            if not (0 <= day_idx <= 4):
                continue

            overlapping = []
            for i, sl in enumerate(slots):
                if not sl["start"] or not sl["end"]:
                    continue
                if (ev_start_dt < _slot_dt(ev_date, sl["end"])
                        and ev_end_dt > _slot_dt(ev_date, sl["start"])):
                    overlapping.append(i)
            if not overlapping:
                continue  # außerhalb des Schulrasters → nicht zeigen

            first_idx = overlapping[0]
            span = 1
            for j in range(1, len(overlapping)):
                if overlapping[j] == overlapping[j - 1] + 1:
                    span += 1
                else:
                    break

            events_index.setdefault((slots[first_idx]["start"], day_idx), []).append({
                **ev, "rowspan": span,
                "start_time": ev_start_dt.strftime("%H:%M"),
                "end_time": ev_end_dt.strftime("%H:%M"),
            })
            for k in range(1, span):
                skip_cells.add((slots[first_idx + k]["start"], day_idx))

    grid["all_day_row"] = all_day_row
    grid["all_day_skip"] = all_day_skip
    grid["events"] = events_index
    grid["skip_cells"] = skip_cells
