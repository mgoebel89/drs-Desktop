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


def get_my_timetable(user: User, start: date, end: date) -> list[dict]:
    """Eigene Stundenplan-Lessons zwischen start und end (inkl.)."""
    with session_for(user) as s:
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
