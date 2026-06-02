"""WebUntis-Integration via python-webuntis.

Pro Nutzer werden Server/Schule/Username/Passwort verschlüsselt in der DB
gespeichert. Diese Funktionen entschlüsseln on-demand, öffnen eine
Untis-Session und liefern aufbereitete Daten zurück.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Iterator

import webuntis

from app.crypto import decrypt_secret
from app.models import User

log = logging.getLogger(__name__)

USER_AGENT = "DRS Unterrichtsmaterial"


def _normalize_server(server: str) -> str:
    """Akzeptiert 'neilo.webuntis.com', 'https://neilo…', mit oder ohne Pfad."""
    s = server.strip()
    if not s:
        return s
    if not s.startswith("http://") and not s.startswith("https://"):
        s = "https://" + s
    # python-webuntis erwartet nur Host (ohne Pfad). Trailing-Slash + Pfad weg.
    return s.rstrip("/").split("/WebUntis", 1)[0]


def get_creds(user: User) -> dict | None:
    if not user.untis_creds_enc:
        return None
    try:
        raw = decrypt_secret(user.untis_creds_enc)
        return json.loads(raw) if raw else None
    except Exception:
        log.exception("Untis-Credentials konnten nicht entschlüsselt werden")
        return None


@contextmanager
def session_for(user: User) -> Iterator[webuntis.Session]:
    """Kontextmanager: liefert eingeloggte Untis-Session, loggt am Ende aus."""
    creds = get_creds(user)
    if not creds:
        raise RuntimeError("Keine WebUntis-Credentials hinterlegt.")
    server = _normalize_server(creds.get("server", ""))
    school = creds.get("school", "").strip()
    username = creds.get("username", "").strip()
    password = creds.get("password", "")
    if not all([server, school, username, password]):
        raise RuntimeError("Unvollständige WebUntis-Credentials.")

    s = webuntis.Session(
        server=server,
        username=username,
        password=password,
        school=school,
        useragent=USER_AGENT,
    ).login()
    try:
        yield s
    finally:
        try:
            s.logout()
        except Exception:
            log.debug("Logout-Fehler ignoriert", exc_info=True)


# ── High-Level-Funktionen ─────────────────────────────────────────────────
def test_connection(user: User) -> tuple[bool, str]:
    """Versucht Login + Logout. Liefert (ok, message)."""
    creds = get_creds(user)
    if not creds:
        return False, "Noch keine WebUntis-Credentials hinterlegt."
    if not all([creds.get("server"), creds.get("school"),
                creds.get("username"), creds.get("password")]):
        return False, "Unvollständige Angaben (Server, Schule, Username, Passwort)."
    try:
        with session_for(user) as s:
            # Ein Probe-Request, damit wir wissen ob die Session wirklich funktioniert.
            _ = list(s.schoolyears())
            return True, "Verbindung erfolgreich."
    except webuntis.errors.BadCredentialsError:
        return False, "Benutzername oder Passwort falsch."
    except webuntis.errors.NotLoggedInError:
        return False, "Login fehlgeschlagen — Server akzeptiert die Anmeldung nicht."
    except webuntis.errors.AuthError as e:
        return False, f"Authentifizierungs-Fehler: {e}"
    except Exception as e:
        return False, f"Verbindung fehlgeschlagen: {type(e).__name__}: {e}"


def _period_to_dict(p) -> dict:
    """Period-Objekt in serialisierbares Dict umformen.

    Wichtig: NICHT auf p.teachers zugreifen — die Lazy-Resolution triggert
    intern getTeachers(), wofür viele Lehrer-Accounts keine Berechtigung haben.
    """
    def _names(items):
        out = []
        try:
            for it in (items or []):
                n = getattr(it, "name", None) or getattr(it, "long_name", None) or str(it)
                out.append(n)
        except Exception:
            log.debug("Auflösung fehlgeschlagen", exc_info=True)
        return out
    return {
        "id": getattr(p, "id", None),
        "start": p.start.isoformat() if p.start else None,
        "end": p.end.isoformat() if p.end else None,
        "klassen": _names(p.klassen),
        "subjects": _names(p.subjects),
        "rooms": _names(p.rooms),
        "code": getattr(p, "code", None),
        "info": getattr(p, "info", "") or "",
        # Lernstoff/Lehrtext aus Untis (Unterrichtsbezeichnung). Felder können je
        # nach Schule befüllt sein oder leer bleiben.
        "lstext": (getattr(p, "lstext", "") or "").strip(),
        "subst_text": (getattr(p, "substText", "") or "").strip(),
    }


def _warmup(s) -> None:
    """python-webuntis schlägt manchmal mit NotLoggedInError fehl, wenn man direkt
    nach dem Login zu my_timetable() springt. Wir wärmen die Session, indem wir
    alle Stammdaten-Endpoints einmal aufrufen (Fehler ignorieren)."""
    # teachers() bewusst NICHT abrufen — die meisten Lehrer-Accounts haben dafür
    # keine Berechtigung und es ist für my_timetable auch nicht nötig.
    for name in ("statusdata", "klassen", "subjects", "rooms"):
        try:
            v = getattr(s, name)()
            # iter() forciert die HTTP-Anfrage bei lazy Result-Objects
            if hasattr(v, "__iter__"):
                list(v)
        except Exception:
            log.debug("warmup %s fehlgeschlagen", name, exc_info=True)


def get_my_timetable(user: User, start: date, end: date) -> list[dict]:
    """Eigene Stundenplan-Lessons zwischen start und end (inkl.)."""
    with session_for(user) as s:
        _warmup(s)
        periods = list(s.my_timetable(start=start, end=end))
    return sorted([_period_to_dict(p) for p in periods],
                  key=lambda d: d["start"] or "")


def get_current_day(user: User, day: date | None = None) -> list[dict]:
    d = day or date.today()
    return get_my_timetable(user, d, d)


def get_week(user: User, ref: date | None = None) -> tuple[date, date, list[dict]]:
    ref = ref or date.today()
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday, get_my_timetable(user, monday, friday)


def _fmt_hhmm(v) -> str:
    """Untis liefert Zeiten je nach Lib als time-Objekt, datetime oder int (HHMM).
    Vereinheitlichen auf 'HH:MM'."""
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    s = str(v).zfill(4)
    return f"{s[:2]}:{s[2:]}" if s.isdigit() and len(s) == 4 else s


def get_timegrid(user: User) -> list[dict]:
    """Liefert die schul-weiten Stundenblöcke aus Untis als Liste von Slots,
    gemerged über alle Wochentage. Format: [{name, start, end}]."""
    with session_for(user) as s:
        _warmup(s)
        grid = s.timegrid_units()
        slots: dict[tuple[str, str], str] = {}
        # TimegridObject iteriert über Day-Objekte; jedes Day hat .dayUnits oder Liste von Slots
        try:
            for day in grid:
                units = getattr(day, "dayUnits", None) or getattr(day, "_data", {}).get("timeUnits", []) or []
                for u in units:
                    name = (u.get("name") if isinstance(u, dict) else getattr(u, "name", "")) or ""
                    start = _fmt_hhmm((u.get("startTime") if isinstance(u, dict) else getattr(u, "start", None)))
                    end = _fmt_hhmm((u.get("endTime") if isinstance(u, dict) else getattr(u, "end", None)))
                    if start and end:
                        slots.setdefault((start, end), str(name))
        except Exception:
            log.debug("timegrid_units konnte nicht geparst werden", exc_info=True)
    out = [{"name": n, "start": s_, "end": e} for (s_, e), n in slots.items()]
    out.sort(key=lambda x: x["start"])
    # Falls Namen leer: durchnummerieren
    for i, slot in enumerate(out, start=1):
        if not slot["name"]:
            slot["name"] = str(i)
    return out


def _pair_slots(slots: list[dict]) -> list[dict]:
    """Fasst je zwei aufeinanderfolgende Slots zu einem 90-Min-Block zusammen,
    sofern sie nahtlos sind (Ende[i] == Start[i+1]). Sonst Slot solo."""
    out: list[dict] = []
    i = 0
    while i < len(slots):
        a = slots[i]
        b = slots[i + 1] if i + 1 < len(slots) else None
        if b and a["end"] == b["start"]:
            out.append({
                "name": f"{a['name']}./{b['name']}.",
                "start": a["start"],
                "end": b["end"],
                "sub_starts": [a["start"], b["start"]],
            })
            i += 2
        else:
            out.append({"name": a["name"] + ".", "start": a["start"],
                        "end": a["end"], "sub_starts": [a["start"]]})
            i += 1
    return out


def _merge_block_lessons(lessons: list[dict]) -> list[dict]:
    """Innerhalb eines Block-Slots: gleichartige Lessons (selbe Klasse/Fach/Raum)
    zu einem einzigen Eintrag zusammenfassen, Lernstoff vereinen."""
    by_key: dict[tuple, dict] = {}
    order: list[tuple] = []
    for l in lessons:
        key = (tuple(l.get("klassen") or []),
               tuple(l.get("subjects") or []),
               tuple(l.get("rooms") or []),
               l.get("code") or "")
        if key not in by_key:
            by_key[key] = dict(l)
            order.append(key)
        else:
            existing = by_key[key]
            # Lernstoff aus beiden Hälften zusammenführen (uniq)
            stoff = [s for s in [existing.get("lstext"), l.get("lstext")] if s]
            if stoff:
                existing["lstext"] = " · ".join(dict.fromkeys(stoff))
            infos = [s for s in [existing.get("info"), l.get("info")] if s]
            if infos:
                existing["info"] = " · ".join(dict.fromkeys(infos))
    return [by_key[k] for k in order]


def get_week_grid(user: User, ref: date | None = None) -> dict:
    """Vollständige Wochenansicht im Grid-Format.
    Liefert: {monday, friday, days: [{date, weekday_name}], slots: [{name,start,end}],
              cells: dict[(slot_start, day_idx)] -> list[lesson_dict]}."""
    ref = ref or date.today()
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    lessons = get_my_timetable(user, monday, friday)
    slots = get_timegrid(user)

    # Fallback: kein timegrid lieferbar → dynamisch aus den Lessons ableiten
    if not slots:
        unique = {}
        for l in lessons:
            st = (l["start"] or "")[11:16]
            en = (l["end"] or "")[11:16]
            if st and en:
                unique.setdefault((st, en), True)
        slots = [{"name": str(i+1), "start": s_, "end": e}
                 for i, (s_, e) in enumerate(sorted(unique.keys()))]

    # Doppelstunden bilden (DRS: 90-Min-Raster).
    blocks = _pair_slots(slots)

    days = []
    weekday_names = ["Mo", "Di", "Mi", "Do", "Fr"]
    for i in range(5):
        d = monday + timedelta(days=i)
        days.append({"date": d, "weekday_name": weekday_names[i]})

    # Cells befüllen: key = (block_start, day_idx)
    cells: dict[tuple[str, int], list[dict]] = {}
    for l in lessons:
        ltime = (l["start"] or "")[11:16]
        try:
            lday = datetime.fromisoformat(l["start"]).date()
            day_idx = (lday - monday).days
        except Exception:
            continue
        if not (0 <= day_idx <= 4):
            continue
        # Block finden: lesson-Start liegt in einem der sub_starts ODER innerhalb [start, end)
        block_key = None
        for bl in blocks:
            if ltime in bl["sub_starts"]:
                block_key = bl["start"]; break
        if block_key is None:
            for bl in blocks:
                if bl["start"] <= ltime < bl["end"]:
                    block_key = bl["start"]; break
        if block_key is None:
            continue
        cells.setdefault((block_key, day_idx), []).append(l)

    # Innerhalb jedes Blocks gleichartige Lessons zusammenfassen
    cells = {k: _merge_block_lessons(v) for k, v in cells.items()}

    return {
        "monday": monday, "friday": friday,
        "days": days, "slots": blocks, "cells": cells,
    }


def diagnose(user: User) -> list[dict]:
    """Schrittweise Diagnose: testet einzelne API-Calls und liefert Statusliste."""
    results: list[dict] = []

    def step(name: str, fn):
        try:
            v = fn()
            results.append({"step": name, "ok": True, "info": str(v)[:200]})
            return v
        except Exception as e:
            results.append({"step": name, "ok": False,
                            "info": f"{type(e).__name__}: {e}"})
            return None

    creds = get_creds(user)
    if not creds:
        results.append({"step": "credentials", "ok": False,
                        "info": "Keine Untis-Credentials hinterlegt."})
        return results
    results.append({"step": "credentials", "ok": True,
                    "info": f"server={_normalize_server(creds.get('server',''))}, "
                            f"school={creds.get('school','')}, "
                            f"user={creds.get('username','')}"})

    try:
        with session_for(user) as s:
            results.append({"step": "login", "ok": True, "info": "Session etabliert"})
            step("schoolyears", lambda: f"{len(list(s.schoolyears()))} Jahre")
            step("statusdata", lambda: f"{type(s.statusdata()).__name__}")
            step("klassen", lambda: f"{len(list(s.klassen()))} Klassen")
            step("subjects", lambda: f"{len(list(s.subjects()))} Fächer")
            step("rooms", lambda: f"{len(list(s.rooms()))} Räume")
            # Stundenplan-Versuche
            today = date.today()
            in_week = today + timedelta(days=6)
            step("my_timetable(heute…+6 Tage)",
                 lambda: f"{len(list(s.my_timetable(start=today, end=in_week)))} Lessons")
            # Aktuelle Woche Mo-Fr (so wie die /timetable-Seite es macht)
            monday = today - timedelta(days=today.weekday())
            friday = monday + timedelta(days=4)
            step(f"my_timetable(Mo {monday.isoformat()} – Fr {friday.isoformat()})",
                 lambda: f"{len(list(s.my_timetable(start=monday, end=friday)))} Lessons")
    except Exception as e:
        results.append({"step": "login", "ok": False,
                        "info": f"{type(e).__name__}: {e}"})

    return results
