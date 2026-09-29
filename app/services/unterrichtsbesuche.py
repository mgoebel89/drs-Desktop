"""Unterrichtsbesuche — Regeln, Kataloge und Vorgaben an einer Stelle.

Die Piktogramme sind hier als **Zeichenanweisungen** hinterlegt (Pfade mit
absoluten M/L/H/V/C/Q/Z-Befehlen, Kreise, Rechtecke) statt als fertige SVG-
Strings. Grund: Dieselben Daten zeichnen das Icon im Browser (als SVG) UND im
PDF (reportlab kennt kein SVG). Wer ein Icon ergänzt, hält sich deshalb an
diese Befehle — Bögen (A) und relative Befehle kann der PDF-Zeichner nicht.
Alle Icons leben im 24×24-Raster, Strich 1,7, wie die Sidebar.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (UbAnwaerter, UbBesuch, UbEinstellung, UbEintrag,
                        UbKategorie, UbKriterium, UbPhase, UbSchwerpunkt, User)

# ── Piktogramme ───────────────────────────────────────────────────────────
# (label, [teile]) — teil = ("path", d) | ("circle", cx, cy, r)
#                         | ("rect", x, y, w, h, rx)
ICONS: dict[str, tuple[str, list[tuple]]] = {
    "auge": ("Auge", [
        ("path", "M2 12 C5 6.5 8.5 5 12 5 C15.5 5 19 6.5 22 12 "
                 "C19 17.5 15.5 19 12 19 C8.5 19 5 17.5 2 12 Z"),
        ("circle", 12, 12, 3),
    ]),
    "gluehbirne": ("Glühbirne", [
        ("path", "M9 18 H15"),
        ("path", "M10 21 H14"),
        ("path", "M9 15 C9 13.5 8 12.8 7.2 11.8 C6.4 10.8 6 9.6 6 8.5 "
                 "C6 5.2 8.7 2.5 12 2.5 C15.3 2.5 18 5.2 18 8.5 "
                 "C18 9.6 17.6 10.8 16.8 11.8 C16 12.8 15 13.5 15 15 Z"),
    ]),
    "sprechblase": ("Sprechblase", [
        ("path", "M21 15 C21 16.1 20.1 17 19 17 H7 L3 21 V5 C3 3.9 3.9 3 5 3 "
                 "H19 C20.1 3 21 3.9 21 5 Z"),
    ]),
    "stern": ("Stern", [
        ("path", "M12 2.5 L14.9 8.4 L21.4 9.3 L16.7 13.9 L17.8 20.4 L12 17.3 "
                 "L6.2 20.4 L7.3 13.9 L2.6 9.3 L9.1 8.4 Z"),
    ]),
    "frage": ("Fragezeichen", [
        ("circle", 12, 12, 10),
        ("path", "M9.1 9 C9.1 7.3 10.4 6 12 6 C13.6 6 14.9 7.3 14.9 8.8 "
                 "C14.9 10.8 12 11.5 12 13.5"),
        ("path", "M12 17.2 L12 17.3"),
    ]),
    "achtung": ("Achtung", [
        ("path", "M10.3 3.9 L1.8 18 C1.2 19.3 2.1 21 3.5 21 H20.5 "
                 "C21.9 21 22.8 19.3 22.2 18 L13.7 3.9 C12.9 2.6 11.1 2.6 10.3 3.9 Z"),
        ("path", "M12 9 V13"),
        ("path", "M12 17 L12 17.1"),
    ]),
    "daumen": ("Daumen hoch", [
        ("path", "M7 10 V21"),
        ("path", "M7 10 L11 2.5 C12.7 2.5 14 3.8 14 5.5 V9 H19.5 "
                 "C20.8 9 21.7 10.2 21.4 11.4 L19.8 18.6 C19.5 19.9 18.4 21 17 21 "
                 "H4 C3.4 21 3 20.6 3 20 V11 C3 10.4 3.4 10 4 10 Z"),
    ]),
    "flagge": ("Flagge", [
        ("path", "M4 22 V3"),
        ("path", "M4 4 C8 1.5 12 6.5 16 4 C17.5 3.1 19 3 20 3 V14 "
                 "C19 14 17.5 14.1 16 15 C12 17.5 8 12.5 4 15"),
    ]),
    "uhr": ("Uhr", [
        ("circle", 12, 12, 10),
        ("path", "M12 6 V12 L16 14"),
    ]),
    "personen": ("Personen", [
        ("circle", 9, 7, 4),
        ("path", "M17 21 V19 C17 16.8 15.2 15 13 15 H5 C2.8 15 1 16.8 1 19 V21"),
        ("path", "M23 21 V19 C23 17.2 21.8 15.6 20 15.1"),
        ("path", "M16 3.1 C17.8 3.6 19 5.2 19 7 C19 8.8 17.8 10.4 16 10.9"),
    ]),
    "tafel": ("Tafel", [
        ("rect", 2, 3, 20, 14, 1.5),
        ("path", "M8 21 L12 17 L16 21"),
        ("path", "M6 8 H13"),
        ("path", "M6 12 H10"),
    ]),
    "lupe": ("Lupe", [
        ("circle", 11, 11, 7),
        ("path", "M21 21 L16 16"),
    ]),
    "stift": ("Stift", [
        ("path", "M16.5 3.5 C17.3 2.7 18.7 2.7 19.5 3.5 L20.5 4.5 "
                 "C21.3 5.3 21.3 6.7 20.5 7.5 L8 20 L3 21 L4 16 Z"),
        ("path", "M14.5 5.5 L18.5 9.5"),
    ]),
    "blitz": ("Blitz", [
        ("path", "M13 2 L3 14 H12 L11 22 L21 10 H12 Z"),
    ]),
    "haken": ("Haken", [
        ("circle", 12, 12, 10),
        ("path", "M8 12 L11 15 L16 9"),
    ]),
    "herz": ("Herz", [
        ("path", "M12 20.5 C12 20.5 3 15 3 8.8 C3 6 5.2 3.8 7.9 3.8 "
                 "C9.6 3.8 11.1 4.7 12 6 C12.9 4.7 14.4 3.8 16.1 3.8 "
                 "C18.8 3.8 21 6 21 8.8 C21 15 12 20.5 12 20.5 Z"),
    ]),
    "ziel": ("Zielscheibe", [
        ("circle", 12, 12, 10),
        ("circle", 12, 12, 6),
        ("circle", 12, 12, 2),
    ]),
    "trend": ("Aufwärtstrend", [
        ("path", "M3 17 L9 11 L13 15 L21 7"),
        ("path", "M15 7 H21 V13"),
    ]),
    "kamera": ("Kamera", [
        ("path", "M23 19 C23 20.1 22.1 21 21 21 H3 C1.9 21 1 20.1 1 19 V8 "
                 "C1 6.9 1.9 6 3 6 H7 L9 3 H15 L17 6 H21 C22.1 6 23 6.9 23 8 Z"),
        ("circle", 12, 13, 4),
    ]),
    "bild": ("Bild", [
        ("rect", 3, 3, 18, 18, 2),
        ("circle", 8.5, 8.5, 1.5),
        ("path", "M21 15 L16 10 L5 21"),
    ]),
    "plus": ("Plus", [
        ("path", "M12 5 V19"),
        ("path", "M5 12 H19"),
    ]),
}
STANDARD_ICON = "auge"

# Die zwei festen Wertungen — mit eigenem Piktogramm, damit sie im Protokoll
# ohne Legende lesbar sind.
# `pos` steht dabei, weil Jinjas `tojson` die Schlüssel alphabetisch sortiert —
# ohne sie stünde „Entwicklungsfeld" im Handy vor „Stärke".
WERTUNGEN: dict[str, dict] = {
    "staerke":     {"label": "Stärke", "icon": "daumen", "farbe": "#2E7D32", "pos": 0},
    "entwicklung": {"label": "Entwicklungsfeld", "icon": "trend", "farbe": "#C77700", "pos": 1},
}

# Feste Farbpalette statt Farbwähler: alle Töne sind auf Weiß lesbar und
# kräftig genug für ein Piktogramm im Ausdruck.
FARBEN: list[tuple[str, str]] = [
    ("#00639C", "DRS-Blau"),
    ("#00838F", "Petrol"),
    ("#2E7D32", "Grün"),
    ("#C77700", "Orange"),
    ("#C62828", "Rot"),
    ("#D4005E", "Magenta"),
    ("#6A3FA0", "Violett"),
    ("#5A6B7D", "Grau"),
]
_FARB_WERTE = {f for f, _ in FARBEN}

SPALTEN = {"verlauf": "Verlauf (links)", "kommentar": "Kommentar (rechts)"}
STATUS = {"geplant": "Geplant", "laufend": "Läuft", "abgeschlossen": "Abgeschlossen"}
ORDNUNGEN = {
    "chronologisch": "Chronologisch",
    "kategorie": "Nach Kategorie",
    "kriterium": "Nach Beratungsschwerpunkt",
    "zweispaltig": "Zweispaltig (Verlauf | Kommentar)",
}

# Vorgaben beim ersten Öffnen — danach gehört alles dem Lehrer.
VORGABE_KATEGORIEN = [
    ("Beobachtung", "auge", "#00639C", "verlauf"),
    ("Idee", "gluehbirne", "#C77700", "kommentar"),
    ("Anmerkung", "sprechblase", "#6A3FA0", "kommentar"),
]
VORGABE_PHASEN = ["Einstieg", "Erarbeitung", "Sicherung", "Übung / Transfer", "Abschluss"]
# Die „Kriterien" heißen in der Oberfläche **Beratungsschwerpunkte**: EIN Katalog
# für alle Anwärter (Liste des Seminars). Je Besuch wählt der Anwärter daraus
# aus (`ub_schwerpunkte`). Intern bleibt der Name `kriterien`/`kriterium_id`.
VORGABE_KRITERIEN = [
    "Klassenführung", "Strukturierung", "Aktivierung der Lernenden",
    "Lehrersprache & Impulse", "Medien & Material", "Lernatmosphäre",
    "Handlungsorientierung", "Ergebnissicherung",
]

_ZEIT_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── kleine Normalisierer ──────────────────────────────────────────────────

def zeit(wert: str | None) -> str:
    w = (wert or "").strip()[:5]
    return w if _ZEIT_RE.match(w) else ""


def datum(wert: str | None) -> str:
    w = (wert or "").strip()[:10]
    return w if _DATUM_RE.match(w) else ""


def farbe(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in _FARB_WERTE else FARBEN[0][0]


def icon_name(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in ICONS else STANDARD_ICON


def spalte(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in SPALTEN else "verlauf"


def wertung(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in WERTUNGEN else ""


def text(wert, laenge: int | None = None) -> str:
    t = str(wert or "").strip()
    return t[:laenge] if laenge else t


def icon_svg(name: str) -> str:
    """Inneres SVG (ohne <svg>-Hülle) für Templates und JS."""
    _, teile = ICONS.get(name, ICONS[STANDARD_ICON])
    out = []
    for t in teile:
        if t[0] == "path":
            out.append(f'<path d="{t[1]}"/>')
        elif t[0] == "circle":
            out.append(f'<circle cx="{t[1]}" cy="{t[2]}" r="{t[3]}"/>')
        elif t[0] == "rect":
            out.append(f'<rect x="{t[1]}" y="{t[2]}" width="{t[3]}" '
                       f'height="{t[4]}" rx="{t[5]}"/>')
    return "".join(out)


def icon_katalog() -> dict[str, dict[str, str]]:
    return {k: {"label": v[0], "svg": icon_svg(k)} for k, v in ICONS.items()}


# ── Einstellungen ─────────────────────────────────────────────────────────

MODELLE = {"kategorien": UbKategorie, "phasen": UbPhase, "kriterien": UbKriterium}


def einstellung(db: Session, user: User) -> UbEinstellung:
    """Liefert die Einstellungszeile und legt beim allerersten Aufruf die
    Vorgaben an. Danach wird nie wieder geseedet."""
    e = db.get(UbEinstellung, user.id)
    if e:
        return e
    e = UbEinstellung(user_id=user.id, standard_ordnung="chronologisch")
    db.add(e)
    for i, (name, ic, fa, sp) in enumerate(VORGABE_KATEGORIEN):
        db.add(UbKategorie(user_id=user.id, name=name, icon=ic, farbe=fa,
                           spalte=sp, position=i))
    for i, name in enumerate(VORGABE_PHASEN):
        db.add(UbPhase(user_id=user.id, name=name, position=i))
    for i, name in enumerate(VORGABE_KRITERIEN):
        db.add(UbKriterium(user_id=user.id, name=name, position=i))
    db.commit()
    return e


def liste(db: Session, user: User, art: str, nur_aktive: bool = False) -> list:
    model = MODELLE[art]
    q = select(model).where(model.user_id == user.id)
    if nur_aktive:
        q = q.where(model.active.is_(True))
    return list(db.scalars(q.order_by(model.position, model.id)).all())


def eintrag_spalte(art: str) -> str:
    return {"kategorien": "kategorie_id", "phasen": "phase_id",
            "kriterien": "kriterium_id"}[art]


def nutzung(db: Session, art: str, obj_id: int) -> int:
    """Wie oft wird dieser Einstellungswert verwendet? Bei Beratungsschwerpunkten
    zählt auch die Auswahl in einem Besuch — sonst ließe sich ein Schwerpunkt
    löschen, den ein Protokoll im Kopf aufführt."""
    spalte_ = getattr(UbEintrag, eintrag_spalte(art))
    n = db.scalar(select(func.count(UbEintrag.id)).where(spalte_ == obj_id)) or 0
    if art == "kriterien":
        n += db.scalar(select(func.count(UbSchwerpunkt.id))
                       .where(UbSchwerpunkt.kriterium_id == obj_id)) or 0
    return n


def einstellung_dict(art: str, o, nutzung_: int | None = None) -> dict:
    d = {"id": o.id, "name": o.name, "position": o.position, "active": bool(o.active)}
    if art == "kategorien":
        d.update({"icon": o.icon, "farbe": o.farbe, "spalte": o.spalte})
    if nutzung_ is not None:
        d["nutzung"] = nutzung_
    return d


def katalog(db: Session, user: User) -> dict:
    """Alles, was die Erfassung braucht — inklusive stillgelegter Werte, damit
    alte Einträge weiter ihr Piktogramm zeigen. Die Oberfläche bietet nur die
    aktiven zur Auswahl an."""
    einstellung(db, user)
    return {art: [einstellung_dict(art, o) for o in liste(db, user, art)]
            for art in MODELLE}


# ── Anwärter ──────────────────────────────────────────────────────────────

def anwaerter_liste(db: Session, user: User) -> list[UbAnwaerter]:
    return list(db.scalars(
        select(UbAnwaerter).where(UbAnwaerter.user_id == user.id)
        .order_by(UbAnwaerter.active.desc(), UbAnwaerter.name)
    ).all())


def anwaerter_dict(a: UbAnwaerter, besuche: int = 0) -> dict:
    return {"id": a.id, "name": a.name, "faecher": a.faecher,
            "seminar": a.seminar, "notiz": a.notiz, "active": bool(a.active),
            "besuche": besuche}


def besuche_je_anwaerter(db: Session, user: User) -> dict[int, int]:
    return dict(db.execute(
        select(UbBesuch.anwaerter_id, func.count(UbBesuch.id))
        .where(UbBesuch.user_id == user.id)
        .group_by(UbBesuch.anwaerter_id)
    ).all())


# ── Besuche ───────────────────────────────────────────────────────────────

def besuche(db: Session, user: User, anwaerter_id: int | None = None) -> list[UbBesuch]:
    q = select(UbBesuch).where(UbBesuch.user_id == user.id)
    if anwaerter_id:
        q = q.where(UbBesuch.anwaerter_id == anwaerter_id)
    return list(db.scalars(q.order_by(UbBesuch.datum.desc(),
                                      UbBesuch.beginn.desc())).all())


def schwerpunkte(db: Session, besuch_id: int) -> list[UbKriterium]:
    """Die für diesen Besuch gewählten Beratungsschwerpunkte, in Katalog-
    Reihenfolge (so stehen sie im Handy und im Protokoll immer gleich)."""
    return list(db.scalars(
        select(UbKriterium)
        .join(UbSchwerpunkt, UbSchwerpunkt.kriterium_id == UbKriterium.id)
        .where(UbSchwerpunkt.besuch_id == besuch_id)
        .order_by(UbKriterium.position, UbKriterium.id)
    ).all())


def setze_schwerpunkte(db: Session, user: User, besuch: UbBesuch, ids: list) -> None:
    """Setzt die Auswahl auf genau diese Katalog-IDs. Fremde oder unbekannte
    IDs fallen still heraus. Einträge hängen direkt am Katalog, nicht an der
    Auswahl — abwählen nimmt also keinem Eintrag seine Zuordnung."""
    gueltig = []
    for x in ids or []:
        try:
            kid = int(x)
        except (TypeError, ValueError):
            continue
        k = db.get(UbKriterium, kid)
        if k and k.user_id == user.id and kid not in gueltig:
            gueltig.append(kid)
    alt = {s.kriterium_id: s for s in db.scalars(
        select(UbSchwerpunkt).where(UbSchwerpunkt.besuch_id == besuch.id)).all()}
    for kid, zeile in alt.items():
        if kid not in gueltig:
            db.delete(zeile)
    for pos, kid in enumerate(gueltig):
        if kid in alt:
            alt[kid].position = pos
        else:
            db.add(UbSchwerpunkt(besuch_id=besuch.id, kriterium_id=kid, position=pos))


def besuch_dict(db: Session, b: UbBesuch, mit_eintraegen: bool = False) -> dict:
    d = {
        "id": b.id, "anwaerter_id": b.anwaerter_id,
        "anwaerter": b.anwaerter.name if b.anwaerter else "",
        "datum": b.datum, "beginn": b.beginn, "ende": b.ende,
        "klasse": b.klasse, "raum": b.raum, "thema": b.thema,
        "lernziele": b.lernziele, "status": b.status,
        "status_label": STATUS.get(b.status, b.status),
        "reflexion": b.reflexion, "vereinbarungen": b.vereinbarungen,
        # IDs sind Katalog-IDs (ub_kriterien) — dieselben wie `kriterium_id` am Eintrag
        "schwerpunkte": [{"id": k.id, "text": k.name} for k in schwerpunkte(db, b.id)],
    }
    vor = vorheriger_besuch(db, b)
    d["vorige"] = ({"id": vor.id, "datum": vor.datum, "vereinbarungen": vor.vereinbarungen}
                   if vor and (vor.vereinbarungen or "").strip() else None)
    if mit_eintraegen:
        d["eintraege"] = [eintrag_dict(e) for e in eintraege(db, b.id)]
    return d


def vorheriger_besuch(db: Session, b: UbBesuch) -> UbBesuch | None:
    """Der letzte Besuch desselben Anwärters VOR diesem — nach Datum und
    Beginn, bei Gleichstand nach ID. Seine Vereinbarungen sind die
    Erinnerung für diesen Besuch."""
    kandidaten = [x for x in db.scalars(
        select(UbBesuch).where(UbBesuch.user_id == b.user_id,
                               UbBesuch.anwaerter_id == b.anwaerter_id,
                               UbBesuch.id != b.id)).all()
        if (x.datum or "", x.beginn or "", x.id) < (b.datum or "", b.beginn or "", b.id)]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda x: (x.datum or "", x.beginn or "", x.id))


def ist_anstehend(b: UbBesuch) -> bool:
    """Läuft gerade, oder ist geplant und liegt nicht in der Vergangenheit."""
    if b.status == "laufend":
        return True
    return b.status == "geplant" and (not b.datum or b.datum >= date.today().isoformat())


# ── Einträge ──────────────────────────────────────────────────────────────

def eintraege(db: Session, besuch_id: int) -> list[UbEintrag]:
    """Chronologisch: nach Uhrzeit, bei gleicher Minute in Anlegereihenfolge.
    Einträge ohne Uhrzeit rutschen ans Ende."""
    alle = list(db.scalars(
        select(UbEintrag).where(UbEintrag.besuch_id == besuch_id)
    ).all())
    alle.sort(key=lambda e: (e.zeit or "99:99", e.position, e.id))
    return alle


def naechste_position(db: Session, besuch_id: int) -> int:
    m = db.scalar(select(func.max(UbEintrag.position))
                  .where(UbEintrag.besuch_id == besuch_id))
    return (m or 0) + 10


def eintrag_dict(e: UbEintrag) -> dict:
    return {
        "id": e.id, "art": e.art, "zeit": e.zeit, "position": e.position,
        "phase_id": e.phase_id, "kategorie_id": e.kategorie_id, "text": e.text,
        "kriterium_id": e.kriterium_id,
        "wertung": e.wertung, "bezug_id": e.bezug_id,
        "foto": (f"/api/files/{e.file_uuid}/{e.filename}" if e.file_uuid else ""),
    }


def mit_phasen(eintraege_: list[UbEintrag]) -> list[tuple[UbEintrag, int | None]]:
    """Ordnet jedem Eintrag die Phase zu, deren Marke zuletzt davor stand."""
    aktuell = None
    out = []
    for e in eintraege_:
        if e.art == "phase":
            aktuell = e.phase_id
        out.append((e, aktuell))
    return out
