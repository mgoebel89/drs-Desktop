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
    """Period-Objekt in serialisierbares Dict umformen."""
    def _names(items):
        out = []
        for it in (items or []):
            n = getattr(it, "name", None) or getattr(it, "long_name", None) or str(it)
            out.append(n)
        return out
    return {
        "id": getattr(p, "id", None),
        "start": p.start.isoformat() if p.start else None,
        "end": p.end.isoformat() if p.end else None,
        "klassen": _names(p.klassen),
        "subjects": _names(p.subjects),
        "rooms": _names(p.rooms),
        "teachers": _names(p.teachers),
        "code": getattr(p, "code", None),  # "cancelled", "irregular" etc.
        "info": getattr(p, "info", "") or "",
    }


def _warmup(s) -> None:
    """python-webuntis schlägt manchmal mit NotLoggedInError fehl, wenn man direkt
    nach dem Login zu my_timetable() springt. Ein paar Vor-Calls cachen die
    nötigen Stammdaten und stabilisieren die Session."""
    try:
        s.statusdata()
    except Exception:
        log.debug("warmup: statusdata fehlgeschlagen", exc_info=True)
    try:
        list(s.klassen())
    except Exception:
        log.debug("warmup: klassen fehlgeschlagen", exc_info=True)


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
            klassen = step("klassen", lambda: f"{len(list(s.klassen()))} Klassen")
            teachers = step("teachers", lambda: f"{len(list(s.teachers()))} Lehrer")
            step("subjects", lambda: f"{len(list(s.subjects()))} Fächer")
            step("rooms", lambda: f"{len(list(s.rooms()))} Räume")
            # Stundenplan-Versuche
            today = date.today()
            in_week = today + timedelta(days=6)
            step("my_timetable(heute…+6 Tage)",
                 lambda: f"{len(list(s.my_timetable(start=today, end=in_week)))} Lessons")
            # Falls Teachers ging: erste(n) probieren um zu sehen ob timetable allgemein geht
            if teachers and "0 " not in (results[-2]["info"] or ""):
                try:
                    t_first = next(iter(s.teachers()))
                    step(f"timetable(teacher={t_first.id})",
                         lambda: f"{len(list(s.timetable(teacher=t_first, start=today, end=in_week)))} Lessons")
                except Exception as e:
                    results.append({"step": "timetable(teacher=...)", "ok": False,
                                    "info": f"{type(e).__name__}: {e}"})
    except Exception as e:
        results.append({"step": "login", "ok": False,
                        "info": f"{type(e).__name__}: {e}"})

    return results
