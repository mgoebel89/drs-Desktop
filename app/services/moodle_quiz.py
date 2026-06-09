"""Parser für Moodle-Quiz-Ergebnis-JSON-Exporte.

Moodle exportiert Test-Bewertungen als Liste von Schüler-Objekten:
- Outer-Wrapper kann `[[...]]` (Liste in Liste) oder flach `[...]` sein.
- Pro Eintrag: nachname, vorname, abteilung, institution, status,
  begonnen, beendet, dauer, bewertung10000 (Gesamt-Prozent als
  deutscher Komma-String), f<num><maxx100> (Frage-Anteile).
- Spezialzeile mit nachname == "Gesamtdurchschnitt" wird gefiltert.
- "-" oder leere Werte → percent=None.

Für den Importer ist aktuell nur das Gesamtergebnis relevant; die
f-Felder werden ignoriert.
"""
from __future__ import annotations

import json


def _parse_de_float(s: str | None) -> float | None:
    if s is None:
        return None
    t = str(s).strip()
    if not t or t == "-":
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def parse_moodle_json(text: str) -> list[dict]:
    """Liefert Liste von Schülerergebnissen.

    Jeder Eintrag: {'nachname': str, 'vorname': str, 'abteilung': str,
                    'percent': float | None}.

    Wirft ValueError bei kaputtem JSON oder falscher Struktur.
    """
    if not text or not text.strip():
        raise ValueError("Leerer Inhalt")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Kein gültiges JSON: {e}") from e

    # [[...]]-Wrapper aufdröseln
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
        raw = raw[0]
    if not isinstance(raw, list):
        raise ValueError("Erwarte eine Liste von Schüler-Objekten")

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        nachname = str(item.get("nachname") or "").strip()
        vorname = str(item.get("vorname") or "").strip()
        if not nachname or nachname.lower() == "gesamtdurchschnitt":
            continue
        percent = _parse_de_float(item.get("bewertung10000"))
        out.append({
            "nachname": nachname,
            "vorname": vorname,
            "abteilung": str(item.get("abteilung") or "").strip(),
            "percent": percent,
        })
    return out
