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

Dazu das **Namens-Matching**: Werden die Ergebnisse in eine bestehende, an
eine Lerngruppe gebundene Prüfung importiert, sollen die Namen aus der Datei
auf die dort erfassten Schüler treffen — statt wie beim reinen Moodle-Weg
neue, inaktive Datensätze anzulegen.
"""
from __future__ import annotations

import json
import unicodedata


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


# ── Namens-Zuordnung ──────────────────────────────────────────────────────

_UMLAUTE = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
})


def normalisiere(s: str | None) -> str:
    """Vergleichsform eines Namens.

    Moodle und die Klassenliste schreiben denselben Menschen selten identisch:
    Groß-/Kleinschreibung, Umlaute vs. Umschrift ('Müller' / 'Mueller'),
    Bindestriche, Doppelnamen mit unterschiedlichen Trennzeichen. Deshalb wird
    kleingeschrieben, umschrieben, akzentfrei gemacht und alles außer
    Buchstaben und Ziffern verworfen. Ein 'Meyer-Schmidt' trifft damit auf
    'Meyer Schmidt', aber nie auf 'Meyer'."""
    t = (s or "").strip().lower().translate(_UMLAUTE)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "".join(c for c in t if c.isalnum())


def _schluessel(nachname: str, vorname: str) -> str:
    return normalisiere(nachname) + "|" + normalisiere(vorname)


def matche(eintraege: list[dict], kandidaten: list[dict]) -> list[dict]:
    """Ordnet Moodle-Einträge den Schülern einer Prüfung/Lerngruppe zu.

    `kandidaten`: [{'id': int, 'nachname': str, 'vorname': str}, …]
    Rückgabe: je Moodle-Eintrag ein Dict mit `student_id` (Vorschlag oder None)
    und `treffer` = 'voll' | 'nachname' | 'keiner'.

    Zwei Stufen, bewusst in dieser Reihenfolge:
    1. Nachname **und** Vorname — die sichere Bank.
    2. Nur Nachname, und das auch nur, wenn er in der Klasse **eindeutig** ist.
       Zwei Schüler gleichen Nachnamens bleiben unzugeordnet; sie zu raten
       hieße, Noten zu vertauschen.

    Ein Schüler wird höchstens einmal vorgeschlagen: Steht derselbe Mensch
    zweimal in der Moodle-Datei (etwa zwei Versuche), bekommt die zweite Zeile
    keinen Vorschlag und wandert in die Hand des Lehrers."""
    voll: dict[str, int] = {}
    nach_zahl: dict[str, int] = {}
    nach_id: dict[str, int] = {}
    for k in kandidaten:
        voll[_schluessel(k["nachname"], k.get("vorname", ""))] = k["id"]
        n = normalisiere(k["nachname"])
        nach_zahl[n] = nach_zahl.get(n, 0) + 1
        nach_id[n] = k["id"]

    vergeben: set[int] = set()
    out: list[dict] = []
    # Zwei Durchgänge: Erst alle vollen Treffer festnageln, damit ein
    # Nachnamens-Treffer keinen Schüler wegschnappt, den eine spätere Zeile
    # eindeutig für sich beansprucht.
    vorschlag: list[int | None] = [None] * len(eintraege)
    art: list[str] = ["keiner"] * len(eintraege)
    for i, e in enumerate(eintraege):
        sid = voll.get(_schluessel(e["nachname"], e.get("vorname", "")))
        if sid is not None and sid not in vergeben:
            vorschlag[i] = sid
            art[i] = "voll"
            vergeben.add(sid)
    for i, e in enumerate(eintraege):
        if vorschlag[i] is not None:
            continue
        n = normalisiere(e["nachname"])
        if nach_zahl.get(n, 0) == 1:
            sid = nach_id[n]
            if sid not in vergeben:
                vorschlag[i] = sid
                art[i] = "nachname"
                vergeben.add(sid)

    for i, e in enumerate(eintraege):
        out.append({
            "nachname": e["nachname"],
            "vorname": e.get("vorname", ""),
            "percent": e.get("percent"),
            "student_id": vorschlag[i],
            "treffer": art[i],
        })
    return out
