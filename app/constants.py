"""Globale Konstanten für didaktisches Modell und Stundenrechnung.

Diese Datei ist die Single-Source-of-Truth für:
- Phasen der vollständigen Handlung (LS-/Arbeitsblatt-/Aufgaben-Klassifikation)
- Umrechnung Schulstunde ↔ Unterrichtsblock (für Stunden-Budget der LS)
"""
from __future__ import annotations


# Phasen der vollständigen Handlung (Schema v4). Keys sind die kanonischen
# CSV-Werte, die in DB-Feldern (LsAufgabe.phasen, LsArbeitsblatt.phasen)
# gespeichert werden. Reihenfolge entspricht der didaktischen Abfolge.
PHASEN: list[str] = [
    "informieren",
    "planen",
    "entscheiden",
    "ausfuehren",
    "kontrollieren",
    "bewerten",
]

# Anzeige-Labels (UI, PDF, Moodle-Export). Mapping key → Label.
PHASEN_LABELS: dict[str, str] = {
    "informieren": "Informieren",
    "planen": "Planen",
    "entscheiden": "Entscheiden",
    "ausfuehren": "Ausführen",
    "kontrollieren": "Kontrollieren",
    "bewerten": "Bewerten",
}


# Stunden-Umrechnung. dauer_stunden an LS wird in Schulstunden (45 min)
# geführt; der Stundenplan ist in 90-min-Blöcken organisiert.
MIN_PER_SCHULSTUNDE: int = 45
MIN_PER_BLOCK: int = 90
SCHULSTUNDEN_PRO_BLOCK: int = MIN_PER_BLOCK // MIN_PER_SCHULSTUNDE  # = 2


def parse_phasen_csv(value: str | None) -> list[str]:
    """Parst einen Phasen-CSV-String aus der DB in eine sortierte Liste
    der kanonischen Keys. Unbekannte Tokens werden verworfen.

    Akzeptiert Eingaben wie "Informieren, planen" oder "informieren,planen".
    """
    if not value:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in value.split(","):
        token = raw.strip().lower()
        # Umlaut-Normalisierung: "ausführen" → "ausfuehren"
        token = token.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        if token in PHASEN and token not in seen:
            seen.add(token)
            out.append(token)
    # Stabile didaktische Reihenfolge
    return [p for p in PHASEN if p in seen]


def serialize_phasen(phasen: list[str]) -> str:
    """Gibt die kanonische CSV-Form für die DB zurück (sortiert, ohne
    Duplikate, nur gültige Phasen)."""
    return ", ".join(parse_phasen_csv(", ".join(phasen)))


# Kategorien für LS-Anhänge (LsAttachment.kategorie). Geschlossene Liste.
ATTACHMENT_KATEGORIEN: list[str] = [
    "auftragsbild",
    "schaltplan",
    "datenblatt",
    "sonstiges",
]

ATTACHMENT_KATEGORIE_LABELS: dict[str, str] = {
    "auftragsbild": "Auftragsbild",
    "schaltplan": "Schaltplan",
    "datenblatt": "Datenblatt",
    "sonstiges": "Sonstiges",
}
