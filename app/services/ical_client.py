"""iCal-Client: Termine aus externen Kalendern abrufen.

- Verschlüsselte URL aus DB entschlüsseln
- httpx GET (mit User-Agent, follow_redirects)
- icalendar parse, RRULE-Expansion für Wochenrange
- Zeitzonen: alle Werte werden auf Europe/Berlin normalisiert (naive Anzeige)
- In-Memory-Cache 15 Min pro URL
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from app.crypto import decrypt_secret

log = logging.getLogger(__name__)

_USER_AGENT = "DRS Unterrichtsmaterial/1.0"
_CACHE_TTL = 15 * 60  # Sekunden
_cache: dict[str, tuple[float, list[dict]]] = {}

BERLIN = ZoneInfo("Europe/Berlin")


def _to_berlin_naive(v) -> datetime:
    """date oder datetime → naiver datetime in Europe/Berlin-Lokalzeit.

    - datetime mit TZ → in Berlin umrechnen, dann tzinfo entfernen
    - datetime ohne TZ (floating) → als bereits-Berlin interpretieren
    - date (all-day) → 00:00 Berlin
    """
    if isinstance(v, datetime):
        if v.tzinfo:
            return v.astimezone(BERLIN).replace(tzinfo=None)
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.now(BERLIN).replace(tzinfo=None)


def _parse_ics(text: str, start: date, end: date) -> list[dict]:
    """Parse iCal-Text, liefert Liste der Events im Bereich [start, end] in
    Europe/Berlin-Zeit (alle Felder als ISO-String ohne TZ-Suffix)."""
    end_incl = end + timedelta(days=1)
    window_start_naive = datetime(start.year, start.month, start.day)
    window_end_naive = datetime(end_incl.year, end_incl.month, end_incl.day)
    out: list[dict] = []
    try:
        cal = Calendar.from_ical(text)
    except Exception as e:
        log.warning("ICS Parse-Fehler: %s", e)
        return out

    for comp in cal.walk("VEVENT"):
        try:
            dt_start_raw = comp.decoded("dtstart")
            dt_end_raw = comp.decoded("dtend") if comp.get("dtend") else None
        except Exception:
            continue

        all_day = not isinstance(dt_start_raw, datetime)
        s = _to_berlin_naive(dt_start_raw)
        if dt_end_raw is not None:
            e = _to_berlin_naive(dt_end_raw)
        else:
            e = s + (timedelta(days=1) if all_day else timedelta(hours=1))

        rrule_obj = comp.get("rrule")
        if rrule_obj:
            try:
                from dateutil.rrule import rrulestr
                rrule_str = "RRULE:" + rrule_obj.to_ical().decode("utf-8")
                # RRULE auf TZ-bewusstem dtstart aufbauen
                if isinstance(dt_start_raw, datetime) and dt_start_raw.tzinfo:
                    rule_dtstart = dt_start_raw
                elif isinstance(dt_start_raw, datetime):
                    rule_dtstart = dt_start_raw.replace(tzinfo=BERLIN)
                else:  # date
                    rule_dtstart = datetime(dt_start_raw.year, dt_start_raw.month,
                                            dt_start_raw.day, tzinfo=BERLIN)
                rule = rrulestr(rrule_str, dtstart=rule_dtstart)
                duration = e - s
                win_start_tz = window_start_naive.replace(tzinfo=BERLIN) - timedelta(days=1)
                win_end_tz = window_end_naive.replace(tzinfo=BERLIN) + timedelta(days=1)
                occurrences = rule.between(win_start_tz, win_end_tz, inc=True)

                # EXDATE einsammeln
                excluded: set[datetime] = set()
                ex = comp.get("exdate")
                if ex:
                    exes = ex if isinstance(ex, list) else [ex]
                    for x in exes:
                        for v in x.dts:
                            excluded.add(_to_berlin_naive(v.dt))

                for occ in occurrences:
                    sd = occ.astimezone(BERLIN).replace(tzinfo=None) if occ.tzinfo else occ
                    if sd in excluded:
                        continue
                    ed = sd + duration
                    if ed > window_start_naive and sd < window_end_naive:
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
        if e > window_start_naive and s < window_end_naive:
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
