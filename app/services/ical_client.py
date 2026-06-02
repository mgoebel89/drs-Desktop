"""iCal-Client: Termine aus externen Kalendern abrufen.

- Verschlüsselte URL aus DB entschlüsseln
- httpx GET (mit User-Agent, follow_redirects)
- icalendar parse, RRULE-Expansion für Wochenrange
- In-Memory-Cache 15 Min pro URL
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import httpx
from icalendar import Calendar

from app.crypto import decrypt_secret

log = logging.getLogger(__name__)

_USER_AGENT = "DRS Unterrichtsmaterial/1.0"
_CACHE_TTL = 15 * 60  # Sekunden
_cache: dict[str, tuple[float, list[dict]]] = {}


@dataclass
class EventDict:
    summary: str
    location: str
    description: str
    start: datetime
    end: datetime
    all_day: bool


def _to_dt(v) -> datetime:
    """date oder datetime → datetime (naive, lokale Zeit, ohne TZ)."""
    if isinstance(v, datetime):
        if v.tzinfo:
            v = v.astimezone().replace(tzinfo=None)
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.now()


def _parse_ics(text: str, start: date, end: date) -> list[dict]:
    """Parse iCal-Text, liefert Liste der Events im Bereich [start, end]."""
    end_incl = end + timedelta(days=1)
    out: list[dict] = []
    try:
        cal = Calendar.from_ical(text)
    except Exception as e:
        log.warning("ICS Parse-Fehler: %s", e)
        return out

    for comp in cal.walk("VEVENT"):
        try:
            dt_start = comp.decoded("dtstart")
            dt_end_v = comp.get("dtend")
            dt_end = comp.decoded("dtend") if dt_end_v else None
        except Exception:
            continue

        s = _to_dt(dt_start)
        e = _to_dt(dt_end) if dt_end is not None else (s + timedelta(hours=1))
        all_day = not isinstance(dt_start, datetime)

        # RRULE → simple expansion mit dateutil.rrule wenn vorhanden
        rrule_obj = comp.get("rrule")
        starts: list[datetime] = []
        if rrule_obj:
            try:
                from dateutil.rrule import rrulestr
                rrule_str = "RRULE:" + rrule_obj.to_ical().decode("utf-8")
                rule = rrulestr(rrule_str, dtstart=s)
                duration = e - s
                window_start = datetime(start.year, start.month, start.day) - timedelta(days=1)
                window_end = datetime(end_incl.year, end_incl.month, end_incl.day)
                for occ in rule.between(window_start, window_end, inc=True):
                    starts.append(occ if not occ.tzinfo else occ.astimezone().replace(tzinfo=None))
                # EXDATE berücksichtigen
                ex = comp.get("exdate")
                if ex:
                    exes = ex if isinstance(ex, list) else [ex]
                    excluded = set()
                    for x in exes:
                        for v in x.dts:
                            excluded.add(_to_dt(v.dt))
                    starts = [d for d in starts if d not in excluded]
                # Events bauen
                for sd in starts:
                    ed = sd + duration
                    if ed > datetime(start.year, start.month, start.day) and \
                       sd < datetime(end_incl.year, end_incl.month, end_incl.day):
                        out.append({
                            "summary": str(comp.get("summary", "")),
                            "location": str(comp.get("location", "")),
                            "description": str(comp.get("description", "")),
                            "start": sd.isoformat(),
                            "end": ed.isoformat(),
                            "all_day": all_day,
                        })
                continue
            except Exception as ex:
                log.debug("RRULE-Expansion fehlgeschlagen: %s", ex)

        # Einfaches Event ohne RRULE
        if e > datetime(start.year, start.month, start.day) and \
           s < datetime(end_incl.year, end_incl.month, end_incl.day):
            out.append({
                "summary": str(comp.get("summary", "")),
                "location": str(comp.get("location", "")),
                "description": str(comp.get("description", "")),
                "start": s.isoformat(),
                "end": e.isoformat(),
                "all_day": all_day,
            })
    return out


def fetch_events(url: str, start: date, end: date) -> tuple[list[dict], str | None]:
    """Holt iCal-URL (mit Cache) und liefert (events_in_range, error_or_None)."""
    cache_key = f"{url}|{start.isoformat()}|{end.isoformat()}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1], None
    try:
        r = httpx.get(url, timeout=15.0, follow_redirects=True,
                      headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return [], f"HTTP-Fehler: {e}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    events = _parse_ics(r.text, start, end)
    _cache[cache_key] = (now, events)
    return events, None


def get_events_for_calendar(cal_model, start: date, end: date) -> tuple[list[dict], str | None]:
    """Holt Events für ein IcalCalendar-DB-Objekt und reichert sie um label/color an."""
    try:
        url = decrypt_secret(cal_model.url_enc)
    except Exception:
        return [], "URL kann nicht entschlüsselt werden."
    if not url:
        return [], "Keine URL hinterlegt."
    events, err = fetch_events(url, start, end)
    if err:
        return [], err
    for ev in events:
        ev["calendar_label"] = cal_model.label
        ev["calendar_color"] = cal_model.color
    return events, None


def test_url(url: str) -> tuple[bool, str]:
    """Schnelltest: URL holt eine gültige iCal-Antwort?"""
    if not url.lower().startswith(("http://", "https://", "webcal://")):
        return False, "URL muss mit http(s):// oder webcal:// beginnen."
    fetch_url = url
    if fetch_url.startswith("webcal://"):
        fetch_url = "https://" + fetch_url[9:]
    try:
        r = httpx.get(fetch_url, timeout=15.0, follow_redirects=True,
                      headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    head = r.text.lstrip()[:32].upper()
    if "BEGIN:VCALENDAR" not in head:
        return False, "Antwort enthält kein iCal-Format (BEGIN:VCALENDAR fehlt)."
    n_events = r.text.upper().count("BEGIN:VEVENT")
    return True, f"OK — {n_events} Termine im Kalender."
