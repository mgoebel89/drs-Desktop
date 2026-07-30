"""Vorgänge & Projekte: Typen der Zeitleiste und ihre Regeln.

Ein Vorgang ist ein Behälter; erzählt wird er über seine **Zeitleiste**. Jeder
Eintrag hat einen Typ, ein Datum und typ-spezifische Felder, die als JSON am
Eintrag hängen (`payload_json`). Diese Datei ist die einzige Stelle, die weiß,
welche Typen es gibt und welche Felder dazugehören — Router und Oberfläche
lesen den Katalog von hier.

Zwei Felder stehen bewusst NICHT im JSON, sondern als echte Spalten:
`betrag_cent` und `hh_posten_id`. Über sie summiert die Budget-Auswertung
(`app/services/haushalt.py`); in einem JSON-Blob wäre das eine Volltextsuche.
"""
from __future__ import annotations

import json
from typing import Any

# Reihenfolge = Reihenfolge im Auswahl-Dialog „Was ist passiert?"
TYPEN: dict[str, dict[str, Any]] = {
    "notiz": {
        "label": "Notiz",
        "hinweis": "Ein Vermerk zum Vorgang.",
        "felder": ["text"],
    },
    "aufgabe": {
        "label": "Aufgabe",
        "hinweis": "Wird als Aufgabe in Vikunja angelegt und erscheint im Modul Aufgaben.",
        "felder": ["titel", "faellig", "prioritaet", "vikunja_task_id"],
    },
    "frist": {
        "label": "Frist / Wiedervorlage",
        "hinweis": "Bis wann muss etwas passieren.",
        "felder": ["titel", "faellig"],
    },
    "weiterleitung": {
        "label": "Information weiterleiten",
        "hinweis": "Wer wurde wann und auf welchem Weg informiert.",
        "felder": ["info", "empfaenger"],
    },
    "email": {
        "label": "E-Mail",
        "hinweis": "Ein- oder ausgegangene Nachricht; die Mail selbst kann als Datei in Paperless liegen.",
        "felder": ["richtung", "von", "an", "betreff", "text", "docs"],
    },
    "telefonat": {
        "label": "Telefonat / Gespräch",
        "hinweis": "Kurzer Gesprächsvermerk.",
        "felder": ["partner", "text"],
    },
    "dokument": {
        "label": "Dokument",
        "hinweis": "Ein oder mehrere Dokumente aus Paperless verknüpfen.",
        "felder": ["titel", "docs"],
    },
    "angebot": {
        "label": "Angebot",
        "hinweis": "Angebot eines Anbieters — mindert die Restmittel noch nicht.",
        "felder": ["anbieter", "beschreibung", "docs"],
        "betrag": True,
    },
    "entscheidung": {
        "label": "Auswahl / Entscheidungsmatrix",
        "hinweis": "Angebote nach gewichteten Kriterien vergleichen und die Wahl begründen.",
        "felder": ["titel", "kriterien", "teilnehmer", "gewaehlt"],
    },
    "genehmigung": {
        "label": "Genehmigung",
        "hinweis": "Beantragt bei, genehmigt oder abgelehnt am.",
        "felder": ["stelle", "ergebnis", "begruendung", "docs"],
    },
    "bestellung": {
        "label": "Bestellung & Lieferung",
        "hinweis": "Bestellt am, geliefert am — schließt die Lücke bis zur Rechnung.",
        "felder": ["haendler", "bestellt_am", "geliefert_am", "beschreibung", "docs"],
    },
    "kosten": {
        "label": "Kosten",
        "hinweis": "Tatsächliche Ausgabe — bucht auf einen Haushaltsposten.",
        "felder": ["beschreibung", "haendler", "docs"],
        "betrag": True,
        "posten": True,
    },
}

# Typen, die einen Geldbetrag tragen
BETRAG_TYPEN = {t for t, d in TYPEN.items() if d.get("betrag")}
# Typen, die auf einen Haushaltsposten buchen (nur Kosten mindern Restmittel)
POSTEN_TYPEN = {t for t, d in TYPEN.items() if d.get("posten")}

STATUS = ("geplant", "bearbeitung", "pausiert", "beendet")
STATUS_LABEL = {
    "geplant": "Geplant", "bearbeitung": "In Bearbeitung",
    "pausiert": "Pausiert", "beendet": "Beendet",
}

WEGE = ("persoenlich", "email", "fach", "telefon")
WEG_LABEL = {
    "persoenlich": "persönlich", "email": "E-Mail",
    "fach": "Postfach", "telefon": "Telefon",
}

GENEHMIGUNG_ERGEBNIS = ("beantragt", "genehmigt", "abgelehnt")

# Klartext-Skala der Entscheidungsmatrix (wie in der Gemeindeverwaltung)
SCORE_MAX = 5
SCORE_LABEL = {
    0: "trifft nicht zu", 1: "trifft kaum zu", 2: "trifft wenig zu",
    3: "trifft teilweise zu", 4: "trifft weitgehend zu", 5: "trifft voll zu",
}


def _s(wert, grenze: int = 500) -> str:
    return str(wert or "").strip()[:grenze]


def _liste(wert) -> list:
    return wert if isinstance(wert, list) else []


def normalize_payload(typ: str, roh: dict | None) -> dict:
    """Nur bekannte Felder eines Typs übernehmen — und sie in die Form
    bringen, in der die Oberfläche sie erwartet.

    Damit kann ein manipulierter oder veralteter Request keine fremden Felder
    in den Eintrag schmuggeln, und jeder Eintrag hat dieselbe Gestalt.
    """
    roh = roh or {}
    p: dict[str, Any] = {}

    for f in TYPEN.get(typ, {}).get("felder", []):
        if f == "docs":
            # [{id, title}] — die verknüpften Paperless-Dokumente
            p["docs"] = [{
                "id": int(d.get("id")),
                "title": _s(d.get("title"), 250),
            } for d in _liste(roh.get("docs")) if str(d.get("id") or "").isdigit()]
        elif f == "empfaenger":
            p["empfaenger"] = [{
                "name": _s(e.get("name"), 120),
                "weg": e.get("weg") if e.get("weg") in WEGE else "persoenlich",
                "datum": _s(e.get("datum"), 10),
                "erledigt": bool(e.get("erledigt")),
            } for e in _liste(roh.get("empfaenger")) if _s(e.get("name"))]
        elif f == "kriterien":
            p["kriterien"] = [{
                "id": _s(k.get("id"), 40) or f"k{n}",
                "name": _s(k.get("name"), 120),
                "gewicht": max(1, min(10, int(k.get("gewicht") or 1))),
            } for n, k in enumerate(_liste(roh.get("kriterien"))) if _s(k.get("name"))]
        elif f == "teilnehmer":
            p["teilnehmer"] = [{
                "id": _s(t.get("id"), 40) or f"t{n}",
                "name": _s(t.get("name"), 160),
                "preis": t.get("preis") if isinstance(t.get("preis"), (int, float)) else None,
                "punkte": {
                    _s(kid, 40): max(0, min(SCORE_MAX, int(v or 0)))
                    for kid, v in (t.get("punkte") or {}).items()
                },
            } for n, t in enumerate(_liste(roh.get("teilnehmer"))) if _s(t.get("name"))]
        elif f == "richtung":
            p["richtung"] = "aus" if roh.get("richtung") == "aus" else "ein"
        elif f == "ergebnis":
            e = roh.get("ergebnis")
            p["ergebnis"] = e if e in GENEHMIGUNG_ERGEBNIS else "beantragt"
        elif f == "prioritaet":
            try:
                p["prioritaet"] = max(0, min(5, int(roh.get("prioritaet") or 0)))
            except (TypeError, ValueError):
                p["prioritaet"] = 0
        elif f == "vikunja_task_id":
            try:
                p["vikunja_task_id"] = int(roh.get("vikunja_task_id") or 0) or None
            except (TypeError, ValueError):
                p["vikunja_task_id"] = None
        elif f in ("text", "beschreibung", "begruendung", "info"):
            p[f] = _s(roh.get(f), 8000)
        else:
            p[f] = _s(roh.get(f), 250)
    return p


def score(eintrag_payload: dict, teilnehmer: dict) -> int:
    """Gewichtete Punktzahl eines Angebots in der Entscheidungsmatrix.

    Σ (Punkte 0–5 × Gewicht des Kriteriums). Fehlende Punkte zählen als 0 —
    ein nicht bewertetes Kriterium soll nicht zum Vorteil werden.
    """
    punkte = teilnehmer.get("punkte") or {}
    total = 0
    for k in eintrag_payload.get("kriterien") or []:
        total += int(punkte.get(k["id"], 0)) * int(k.get("gewicht") or 1)
    return total


def matrix_auswertung(payload: dict) -> dict:
    """Punktzahlen, Empfehlung (höchste Punktzahl) und getroffene Wahl."""
    teilnehmer = payload.get("teilnehmer") or []
    punkte = {t["id"]: score(payload, t) for t in teilnehmer}
    empfehlung = max(punkte, key=punkte.get) if punkte else None
    return {
        "punkte": punkte,
        "empfehlung": empfehlung,
        "gewaehlt": payload.get("gewaehlt") or "",
    }


def load_payload(roh: str | None) -> dict:
    try:
        d = json.loads(roh or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def dump_payload(p: dict) -> str:
    return json.dumps(p, ensure_ascii=False)
