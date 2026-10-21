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

Dazu die **Namens-Zuordnung** (`ordne_zu`): Die Namen aus der Datei sollen
auf die Schüler der Lerngruppe treffen. Neue Schüler-Datensätze entstehen
dabei nie von selbst — was unklar ist, entscheidet der Lehrer im Fragedialog.
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


def ordne_zu(eintraege: list[dict], kern: list[dict],
             weitere: list[dict] | None = None) -> list[dict]:
    """Ordnet Moodle-Einträge Schülern zu — und sagt ehrlich, wo es unsicher ist.

    `kern`: die Schüler, um die es geht (Lerngruppe der Prüfung, ggf. plus
    bereits erfasste Teilnehmer). `weitere`: die übrigen Schüler derselben
    Klassen — bei einer Teilgruppe also die andere Hälfte. Beide als
    [{'id': int, 'nachname': str, 'vorname': str}, …].

    Je Eintrag kommt ein Dict mit `status` zurück:
    - 'sicher'     voller Name, genau ein Schüler im Kern → still zuordnen
    - 'teilgruppe' voller Name, aber der Schüler sitzt nur in `weitere`
    - 'frage'      es gibt Kandidaten, aber keinen eindeutigen (nur der
                   Nachname passt, Name doppelt in Klasse oder Datei)
    - 'keiner'     niemand kommt in Frage
    `student_id` ist der Vorschlag (bei 'frage' nur, wenn genau ein Kandidat),
    `optionen` die Kandidaten-IDs für den Fragedialog.

    Reihenfolge wie bisher: Erst alle vollen Treffer festnageln, damit ein
    schwächerer Treffer keinen Schüler wegschnappt, den eine spätere Zeile
    eindeutig beansprucht. Geraten wird nie — ein nur über den Nachnamen
    gefundener Schüler ist ein Vorschlag, keine Zuordnung."""
    weitere = weitere or []
    kern_ids = {k["id"] for k in kern}
    weitere = [w for w in weitere if w["id"] not in kern_ids]

    def index(liste: list[dict]) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for k in liste:
            out.setdefault(_schluessel(k["nachname"], k.get("vorname", "")),
                           []).append(k["id"])
        return out

    voll_kern = index(kern)
    voll_weitere = index(weitere)
    nach: dict[str, list[int]] = {}
    for k in kern + weitere:
        nach.setdefault(normalisiere(k["nachname"]), []).append(k["id"])

    zeilen = [{
        "nachname": e["nachname"],
        "vorname": e.get("vorname", ""),
        "percent": e.get("percent"),
        "status": "", "student_id": None, "optionen": [], "hinweis": "",
    } for e in eintraege]
    vergeben: set[int] = set()

    def setze(z: dict, status: str, sid: int | None, optionen: list[int],
              hinweis: str = "") -> None:
        z.update(status=status, student_id=sid, optionen=optionen, hinweis=hinweis)
        if status in ("sicher", "teilgruppe") and sid is not None:
            vergeben.add(sid)

    # 1. Voller Name im Kern
    for e, z in zip(eintraege, zeilen):
        ids = voll_kern.get(_schluessel(e["nachname"], e.get("vorname", "")), [])
        if len(ids) == 1 and ids[0] not in vergeben:
            setze(z, "sicher", ids[0], ids)
        elif len(ids) > 1:
            setze(z, "frage", None, ids,
                  "Diesen Namen gibt es mehrfach in der Lerngruppe.")
    # 2. Voller Name in den übrigen Schülern der Klassen
    for e, z in zip(eintraege, zeilen):
        if z["status"]:
            continue
        ids = voll_weitere.get(_schluessel(e["nachname"], e.get("vorname", "")), [])
        if len(ids) == 1 and ids[0] not in vergeben:
            setze(z, "teilgruppe", ids[0], ids)
        elif len(ids) > 1:
            setze(z, "frage", None, ids, "Diesen Namen gibt es mehrfach in der Klasse.")
    # 3. Alles Übrige: Wer käme in Frage?
    for e, z in zip(eintraege, zeilen):
        if z["status"]:
            continue
        schluessel = _schluessel(e["nachname"], e.get("vorname", ""))
        doppelt = voll_kern.get(schluessel) or voll_weitere.get(schluessel)
        if doppelt:
            # voller Treffer, aber der Schüler ist schon an eine andere Zeile
            # vergeben: derselbe Mensch steht zweimal in der Datei
            setze(z, "frage", None, list(doppelt),
                  "Dieser Name steht mehrfach in der Datei.")
            continue
        ids = nach.get(normalisiere(e["nachname"]), [])
        if len(ids) == 1:
            setze(z, "frage", ids[0], ids, "Nur der Nachname stimmt überein.")
        elif ids:
            setze(z, "frage", None, list(ids),
                  "Mehrere Schüler haben diesen Nachnamen.")
        else:
            setze(z, "keiner", None, [], "Kein Schüler mit diesem Namen gefunden.")
    return zeilen
