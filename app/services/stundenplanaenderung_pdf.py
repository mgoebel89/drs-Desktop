"""Stundenplanänderungs-/Beurlaubungsformular der DRS als ausgefülltes PDF.

Die Schul-Vorlage `app/forms/stundenplanaenderung.pdf` ist ein echtes AcroForm
mit 201 benannten Feldern. Wir befüllen sie **direkt** (statt sie nachzubauen) —
so sieht das Ergebnis 1:1 aus, und der untere Schulleitungs-Block bleibt leer und
damit im Reader weiter interaktiv.

Zwei Fallen, die dieses Modul löst:

1. **Die Tabellen-Feldnamen sind chaotisch** (Zeile 1 heißt `M2`/`M1`, die
   A-Zeilen `M11A2` …). Verlässlich ist nur die **Geometrie**. Deshalb bauen wir
   die Zuordnung (Tag, Zeile, Klasse-/Vertretungs-Spalte) einmalig aus den
   Widget-Rechtecken der Vorlage auf und cachen sie.
2. **Die Unterschrift ist ein Textfeld**, kein Bildfeld. Das Profil-Bild legen
   wir per reportlab-Overlay genau auf die Unterschriftslinie.

Block → Formularzeilen (DRS, Doppelstunden):
  Block 1 → 1./2., Block 2 → 3./4., Block 3 → 5./6., Block 4 → 7./8.,
  Block 5 → A1/A2, Block 6 → A3/A4. Die Zeilen 9./10. bleiben ungenutzt.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject
from sqlalchemy.orm import Session

from app.models import User
from app.services import timetable_grid

TEMPLATE = Path(__file__).resolve().parent.parent / "forms" / "stundenplanaenderung.pdf"

# 6 Tagesspalten des Formulars, in Reihenfolge der x-Position (links→rechts).
_DAY_ORDER = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]
_WEEKDAY_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"]

# Block-Ordinalzahl (1-basiert) → die zwei Formular-Zeilenindizes (0-basiert;
# 0..9 = „1.".."10.", 10..13 = „A1".."A4").
BLOCK_ROWS: list[tuple[int, int]] = [
    (0, 1),    # Block 1 → 1./2.
    (2, 3),    # Block 2 → 3./4.
    (4, 5),    # Block 3 → 5./6.
    (6, 7),    # Block 4 → 7./8.
    (10, 11),  # Block 5 → A1/A2
    (12, 13),  # Block 6 → A3/A4
]

# Begründungs-Optionen: Checkbox-Feld + Textfeld-Zuordnung. Die Schlüssel der
# `felder`-Dicts sind die Namen, die der Wizard im Frontend verwendet.
GRUND_OPTIONEN: dict[str, dict] = {
    "pruefung": {
        "checkbox": "Check Box2",
        "felder": {"fuer": "Teilnahme an Pruefung", "in": "Pruefung in"},
    },
    "sitzung": {
        "checkbox": "Check Box1",
        "felder": {"bezeichnung": "in1"},
    },
    "fortbildung": {
        "checkbox": "Check Box4",
        "felder": {"ort": "Fortbildung in1", "thema": "Thema1",
                   "antrag_am": "Antrag bei SL am1"},
    },
    "beurlaubung": {
        "checkbox": "Check Box3",
        "felder": {},
    },
    "klassenfahrt": {
        "checkbox": "Check Box6",
        "felder": {"klasse": "Klassenfahrt  Klassenwanderung mit der Klasse1",
                   "nach": "nach1", "befoerderung": "Beförderungsmittel1",
                   "von": "Die Fahrt findet vom1",
                   "bis": "Datum oder Unterrichtsstunden bis1"},
    },
    "sonstige": {
        "checkbox": "Check Box5",
        "felder": {"text": "Datum oder Unterrichtsstunden1"},
    },
}

_CHECKBOX_ON = "/Ja"          # ON-State aller Begründungs-Checkboxen
_RADIO_GROUP = "Group1"
_RADIO_ERFORDERLICH = "/1"    # rechte Option „erforderlich"
_RADIO_NICHT = "/0"           # linke Option „nicht erforderlich"


# ── Geometrie: Tabellen-Feldkarte aus der Vorlage ────────────────────────────

def _widgets(reader: PdfReader) -> list[dict]:
    out = []
    for a in reader.pages[0].get("/Annots") or []:
        o = a.get_object()
        if o.get("/Subtype") != "/Widget":
            continue
        parent = o.get("/Parent")
        name = o.get("/T") or (parent.get_object().get("/T") if parent else None)
        ft = o.get("/FT") or (parent.get_object().get("/FT") if parent else None)
        rect = o.get("/Rect")
        if not name or not rect:
            continue
        x0, y0, x1, y1 = (float(v) for v in rect)
        out.append({"name": str(name), "ft": str(ft),
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return out


def _cluster(values: list[float], tol: float) -> list[float]:
    """Werte zu Zentren gruppieren (für Zeilen/Spalten-Raster)."""
    centers: list[float] = []
    for v in sorted(values):
        if centers and abs(v - centers[-1]) <= tol:
            continue
        centers.append(v)
    return centers


@lru_cache(maxsize=1)
def _table_map() -> dict[str, list[tuple[str, str]]]:
    """{tag_kürzel: [(klasse_feld, vertretung_feld)] je Zeile, oben→unten}.

    Ausschließlich aus der Geometrie: Tabellenfelder liegen im Rechteck
    y∈[145,320], x≥115. 12 Spalten (6 Tage × Klasse/Vertretung), 14 Zeilen.
    """
    ws = [w for w in _widgets(PdfReader(str(TEMPLATE)))
          if w["ft"] == "/Tx" and 145 <= w["y0"] <= 320 and w["x0"] >= 115]
    # Zeilen: y absteigend (oben zuerst)
    row_centers = _cluster(sorted((w["y0"] for w in ws), reverse=True), tol=6)
    row_centers.sort(reverse=True)
    # Spalten: x aufsteigend
    col_centers = _cluster(sorted(w["x0"] for w in ws), tol=8)
    col_centers.sort()

    def nearest(centers: list[float], v: float) -> int:
        return min(range(len(centers)), key=lambda i: abs(centers[i] - v))

    # grid[row][col] = feldname
    grid: dict[tuple[int, int], str] = {}
    for w in ws:
        r = nearest(row_centers, w["y0"])
        c = nearest(col_centers, w["x0"])
        grid[(r, c)] = w["name"]

    tage: dict[str, list[tuple[str, str]]] = {}
    for d, tag in enumerate(_DAY_ORDER):
        klasse_col, vert_col = 2 * d, 2 * d + 1
        zeilen = []
        for r in range(len(row_centers)):
            zeilen.append((grid.get((r, klasse_col), ""),
                           grid.get((r, vert_col), "")))
        tage[tag] = zeilen
    return tage


@lru_cache(maxsize=1)
def _signature_rect() -> tuple[float, float, float, float]:
    for w in _widgets(PdfReader(str(TEMPLATE))):
        if w["name"] == "Unterschrift der Lehrperson1":
            return (w["x0"], w["y0"], w["x1"], w["y1"])
    return (250.0, 120.0, 591.0, 138.0)


# ── Datensammlung: Änderungen der Woche ──────────────────────────────────────

def collect_week_changes(db: Session, user: User, monday: date) -> dict:
    """Ausfall/Vertretung der eigenen Stunden dieser Woche.

    Quelle ist bewusst das **Wochengrid** — also genau das, was auch im
    Stundenplan angezeigt wird. Dadurch tauchen nur Änderungen an real
    existierenden Stunden auf: veraltete Ausnahmen (z. B. aus einer früheren
    Grundstundenplan-Version) oder Vertretungen ohne Basisstunde, die das Grid
    ohnehin verwirft, kommen nicht ins Formular. Verlegte (verlegt_weg /
    verlegt_hier) und Zusatzstunden werden ignoriert.

    Rückgabe: {has_changes, von, bis, eintraege:[{day_idx, block_ord, datum,
    klasse, vertretung}]}.
    """
    grid = timetable_grid.get_week_grid(db, user, monday)
    slots = grid.get("slots") or []
    ordinals = {s["start"]: i for i, s in enumerate(slots)}

    eintraege: list[dict] = []
    tage_mit_aenderung: set[date] = set()
    for (slot_start, day_idx), lessons in (grid.get("cells") or {}).items():
        if day_idx > 5:                  # Sonntag hat keine Spalte
            continue
        block_ord = ordinals.get(slot_start)
        if block_ord is None or block_ord >= len(BLOCK_ROWS):
            continue                     # Block außerhalb des Formular-Rasters
        d = monday + timedelta(days=day_idx)
        for l in lessons:
            status = l.get("status")
            if status == "ausfall":
                vertretung = "entfällt, Klasse informiert"
            elif status == "vertretung":
                vertretung = (l.get("vertretung_name") or "").strip()
            else:
                continue                 # regulär, verlegt, zusatz → nicht ins Formular
            klasse = (l.get("klassen_display") or l.get("klassen_key") or "").strip()
            eintraege.append({"day_idx": day_idx, "block_ord": block_ord,
                              "datum": d, "klasse": klasse,
                              "vertretung": vertretung})
            tage_mit_aenderung.add(d)

    eintraege.sort(key=lambda e: (e["day_idx"], e["block_ord"]))
    tage = sorted(tage_mit_aenderung)
    return {
        "has_changes": bool(eintraege),
        "von": tage[0] if tage else None,
        "bis": tage[-1] if tage else None,
        "eintraege": eintraege,
    }


# ── Rendering ────────────────────────────────────────────────────────────────

def _fmt_tag(d: date) -> str:
    return f"{_WEEKDAY_LONG[d.weekday()][:2]}, {d.strftime('%d.%m.%Y')}"


def _fmt_iso(iso: str | None) -> str:
    """'2026-07-20' → 'Mo, 20.07.2026'. Leere/ungültige Eingabe → ''."""
    if not iso:
        return ""
    try:
        return _fmt_tag(date.fromisoformat(iso.strip()))
    except ValueError:
        return iso.strip()   # Freitext unverändert übernehmen


def render_form(db: Session, user: User, monday: date,
                grund_key: str, grund_felder: dict[str, str],
                changes: dict | None = None,
                von: str | None = None, bis: str | None = None) -> bytes:
    """Befüllt die Vorlage und gibt die PDF-Bytes zurück.

    `von`/`bis` sind optionale ISO-Datumsstrings aus dem Wizard und haben
    Vorrang vor dem automatisch erkannten Zeitraum (erster/letzter geänderter
    Tag). So lässt sich das Formular auch aus Versicherungsgründen ohne
    eingetragene Stunden mit selbst gewähltem Zeitraum stellen.
    """
    if changes is None:
        changes = collect_week_changes(db, user, monday)

    tab = _table_map()
    text_values: dict[str, str] = {}

    # Kopf — Zeitraum: manuelle Eingabe schlägt die Automatik.
    text_values["Antragsteller1"] = (user.full_name or user.username or "").strip()
    von_txt = _fmt_iso(von) if von else (_fmt_tag(changes["von"]) if changes["von"] else "")
    bis_txt = _fmt_iso(bis) if bis else (_fmt_tag(changes["bis"]) if changes["bis"] else "")
    if von_txt:
        text_values["am  von1"] = von_txt
    if bis_txt:
        text_values["bis1"] = bis_txt
    text_values["Datum1"] = date.today().strftime("%d.%m.%Y")

    # Tabelle: Block → beide Zeilen identisch
    table_filled: set[str] = set()
    for e in changes["eintraege"]:
        tag = _DAY_ORDER[e["day_idx"]]
        for row_idx in BLOCK_ROWS[e["block_ord"]]:
            klasse_feld, vert_feld = tab[tag][row_idx]
            if klasse_feld:
                text_values[klasse_feld] = e["klasse"]
                table_filled.add(klasse_feld)
            if vert_feld:
                text_values[vert_feld] = e["vertretung"]
                table_filled.add(vert_feld)

    # Begründungs-Textfelder
    opt = GRUND_OPTIONEN.get(grund_key)
    if opt:
        for wizard_key, pdf_feld in opt["felder"].items():
            wert = (grund_felder or {}).get(wizard_key, "").strip()
            if wert:
                text_values[pdf_feld] = wert

    # Schreiben
    reader = PdfReader(str(TEMPLATE))
    writer = PdfWriter()
    writer.append(reader)
    page = writer.pages[0]

    writer.update_page_form_field_values(page, text_values, auto_regenerate=False)

    # Schmale Tabellenspalten: Auto-Schriftgröße, damit langer Text wie
    # „entfällt, Klasse informiert" schrumpft statt abgeschnitten zu werden.
    _autosize_fields(writer, table_filled)

    # Checkboxen/Radio direkt am Widget setzen (V + AS), damit jeder Reader sie
    # angekreuzt zeigt. Radio automatisch nach Lage: betroffene Stunden →
    # „erforderlich", leere Tabelle (z. B. Versicherungsantrag) → „nicht
    # erforderlich".
    radio = _RADIO_ERFORDERLICH if changes["eintraege"] else _RADIO_NICHT
    on_states: dict[str, str] = {_RADIO_GROUP: radio}
    if opt:
        on_states[opt["checkbox"]] = _CHECKBOX_ON
    _set_button_states(writer, on_states)

    # Reader sollen die Feld-Appearances neu erzeugen (Textwerte anzeigen).
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass

    # Unterschrift als Overlay
    if user.signature_data:
        overlay = _signature_overlay(user.signature_data)
        if overlay is not None:
            page.merge_page(overlay)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _set_button_states(writer: PdfWriter, states: dict[str, str]) -> None:
    """Setzt /V und /AS für Checkbox-/Radio-Felder anhand ihres ON-State-Namens.

    Radios: /V am Feld, /AS am passenden Kind-Widget (die anderen auf /Off).
    """
    root = writer._root_object
    acro = root.get("/AcroForm")
    if acro is None:
        return
    fields = acro.get_object().get("/Fields")
    if not fields:
        return
    for f in fields:
        obj = f.get_object()
        name = obj.get("/T")
        if name is None or str(name) not in states:
            continue
        target = states[str(name)]
        obj[NameObject("/V")] = NameObject(target)
        kids = obj.get("/Kids")
        if kids:                                   # Radio-Gruppe
            for kid in kids:
                k = kid.get_object()
                ap = k.get("/AP")
                states_here = []
                if ap and ap.get_object().get("/N"):
                    states_here = [str(s) for s in ap.get_object()["/N"].get_object().keys()]
                k[NameObject("/AS")] = NameObject(
                    target if target in states_here else "/Off")
        else:                                      # einzelne Checkbox
            obj[NameObject("/AS")] = NameObject(target)


def _autosize_fields(writer: PdfWriter, names: set[str]) -> None:
    """Setzt die Schriftgröße im /DA der genannten Felder auf 0 (= automatisch)."""
    if not names:
        return
    for a in writer.pages[0].get("/Annots") or []:
        o = a.get_object()
        parent = o.get("/Parent")
        nm = o.get("/T") or (parent.get_object().get("/T") if parent else None)
        if nm is None or str(nm) not in names:
            continue
        da = o.get("/DA") or (parent.get_object().get("/DA") if parent else None)
        if da:
            new = re.sub(r"(/\S+)\s+[\d.]+\s+Tf", r"\1 0 Tf", str(da), count=1)
        else:
            new = "/Cali 0 Tf 0 0.388235 0.611765 rg"
        o[NameObject("/DA")] = TextStringObject(new)


def _signature_overlay(sig_bytes: bytes):
    """Ein-Seiten-Overlay mit dem Unterschriftsbild auf der Linie."""
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except Exception:
        return None
    try:
        img = ImageReader(io.BytesIO(sig_bytes))
        iw, ih = img.getSize()
    except Exception:
        return None
    if not iw or not ih:
        return None

    reader = PdfReader(str(TEMPLATE))
    mb = reader.pages[0].mediabox
    pw, ph = float(mb.width), float(mb.height)
    x0, y0, x1, y1 = _signature_rect()

    # Die Unterschrift soll AUF der Linie sitzen (Feldunterkante ~y0) und darf
    # NICHT in die darüberliegende Tabelle ragen. Die untersten Tabellenfelder
    # der Vorlage beginnen bei y≈148.7; wir deckeln die Oberkante der
    # Unterschrift knapp darunter. So bleibt sie sauber zwischen Linie und
    # Tabelle statt wie zuvor (44 pt hoch) in die A1–A4-Zeilen zu ragen.
    TABLE_BOTTOM = 146.0
    base_y = y0 - 1.0                     # Bildunterkante knapp unter die Linie → „aufsitzen"
    avail_h = max(10.0, TABLE_BOTTOM - base_y)
    max_w = min((x1 - x0) - 6, 220.0)
    max_h = min(20.0, avail_h)
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    x = x0 + 4
    y = base_y

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    c.drawImage(img, x, y, width=w, height=h, mask="auto",
                preserveAspectRatio=True)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]
