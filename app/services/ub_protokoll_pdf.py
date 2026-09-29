"""Protokoll eines Unterrichtsbesuchs als PDF (reportlab).

Stufe 1 kennt die chronologische Ordnung: Kopfdaten, Schwerpunkte, Legende,
dann der Verlauf mit den Phasen als Zwischenbänder und dem Piktogramm der
Kategorie vor jedem Eintrag.

Die Piktogramme zeichnet `IconFlowable` direkt aus den Zeichenanweisungen in
`app/services/unterrichtsbesuche.py` — dieselben Daten, aus denen der Browser
sein SVG baut. So sehen Bildschirm und Ausdruck gleich aus, ohne dass der
Container eine SVG-Bibliothek braucht.

Schrift ist Helvetica (WinAnsi). Zeichen außerhalb davon (Emoji, Pfeile aus
der Handy-Tastatur) werden vorher ersetzt, sonst stünden im PDF leere Kästchen.
"""
from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Flowable, Image, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from sqlalchemy.orm import Session

from app.branding import get_logo_bytes, get_school_name
from app.models import UbBesuch, User
from app.services import file_store
from app.services import unterrichtsbesuche as ub

BLAU = colors.HexColor("#00639C")
BLAU_HELL = colors.HexColor("#E6F3FA")
GRAU = colors.HexColor("#666666")
LINIE = colors.HexColor("#E2E5E9")

_BREITE, _HOEHE = A4
_RAND = 18 * mm
# Der Rahmen von SimpleDocTemplate hat 6 pt Innenabstand je Seite — Tabellen
# in voller Randbreite ragten sonst links heraus und stünden versetzt zum Text.
NUTZBREITE = _BREITE - 2 * _RAND - 12


# ── Text ──────────────────────────────────────────────────────────────────

_ERSATZ = {"→": "->", "←": "<-", "⇒": "=>", "✓": "(ok)", "✔": "(ok)",
           "≤": "<=", "≥": ">=", "≠": "!=", "−": "-", "…": "..."}


def _sauber(t: str) -> str:
    t = "".join(_ERSATZ.get(ch, ch) for ch in (t or ""))
    # alles, was cp1252 nicht kann, fällt weg (Emoji etc.)
    return t.encode("cp1252", "ignore").decode("cp1252")


def _p(t: str) -> str:
    """Benutzertext → Paragraph-Markup (escapet, Zeilenumbrüche bleiben)."""
    return escape(_sauber(t)).replace("\n", "<br/>")


def _stil(name, **kw) -> ParagraphStyle:
    basis = dict(fontName="Helvetica", fontSize=9.5, leading=12.5,
                 alignment=TA_LEFT, textColor=colors.black)
    basis.update(kw)
    return ParagraphStyle(name, **basis)


S_TITEL = _stil("titel", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=BLAU)
S_UNTER = _stil("unter", fontSize=9, textColor=GRAU)
S_H2 = _stil("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
             textColor=BLAU, spaceBefore=8, spaceAfter=4)
S_LABEL = _stil("label", fontName="Helvetica-Bold", fontSize=8.5, textColor=GRAU)
S_TEXT = _stil("text")
S_KLEIN = _stil("klein", fontSize=8, leading=10, textColor=GRAU)
S_ZEIT = _stil("zeit", fontSize=8.5, textColor=GRAU)
S_PHASE = _stil("phase", fontName="Helvetica-Bold", fontSize=10, textColor=BLAU)


# ── Piktogramme ───────────────────────────────────────────────────────────

_TOKEN = re.compile(r"[MLHVCQZ]|-?\d*\.?\d+")


def _pfad(c, d: str) -> None:
    """Zeichnet einen SVG-Pfad aus absoluten M/L/H/V/C/Q/Z-Befehlen."""
    tok = _TOKEN.findall(d)
    p = c.beginPath()
    i, cmd = 0, None
    x = y = sx = sy = 0.0

    def zahl():
        nonlocal i
        v = float(tok[i])
        i += 1
        return v

    while i < len(tok):
        if tok[i].isalpha():
            cmd = tok[i]
            i += 1
            if cmd == "Z":
                p.close()
                x, y = sx, sy
                continue
        if cmd == "M":
            x, y = zahl(), zahl()
            sx, sy = x, y
            p.moveTo(x, y)
            cmd = "L"   # weitere Koordinaten nach M sind Linien
        elif cmd == "L":
            x, y = zahl(), zahl()
            p.lineTo(x, y)
        elif cmd == "H":
            x = zahl()
            p.lineTo(x, y)
        elif cmd == "V":
            y = zahl()
            p.lineTo(x, y)
        elif cmd == "C":
            x1, y1, x2, y2, x, y = (zahl() for _ in range(6))
            p.curveTo(x1, y1, x2, y2, x, y)
        elif cmd == "Q":
            qx, qy, nx, ny = (zahl() for _ in range(4))
            p.curveTo(x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                      nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny), nx, ny)
            x, y = nx, ny
        else:
            i += 1   # unbekannt — überspringen statt hängen
    c.drawPath(p, stroke=1, fill=0)


def zeichne_icon(c, name: str, x: float, y: float, groesse: float, farbe) -> None:
    """Icon mit linker unterer Ecke bei (x, y). SVG zählt y nach unten, das
    PDF nach oben — deshalb die gespiegelte Skalierung."""
    _, teile = ub.ICONS.get(name, ub.ICONS[ub.STANDARD_ICON])
    f = groesse / 24.0
    c.saveState()
    c.translate(x, y + groesse)
    c.scale(f, -f)
    c.setStrokeColor(farbe)
    c.setLineWidth(1.9)
    c.setLineCap(1)
    c.setLineJoin(1)
    for t in teile:
        if t[0] == "path":
            _pfad(c, t[1])
        elif t[0] == "circle":
            c.circle(t[1], t[2], t[3], stroke=1, fill=0)
        elif t[0] == "rect":
            c.roundRect(t[1], t[2], t[3], t[4], t[5], stroke=1, fill=0)
    c.restoreState()


class IconFlowable(Flowable):
    def __init__(self, name: str, farbe: str, groesse: float = 5 * mm):
        super().__init__()
        self.name, self.farbe, self.groesse = name, colors.HexColor(farbe), groesse
        self.width = self.height = groesse

    def draw(self):
        zeichne_icon(self.canv, self.name, 0, 0, self.groesse, self.farbe)


# ── Seitenrahmen ──────────────────────────────────────────────────────────

class _NummerCanvas(rl_canvas.Canvas):
    """„Seite x von y" braucht die Gesamtzahl — also erst alle Seiten
    sammeln und beim Speichern die Fußzeile nachtragen."""
    fusstext = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._seiten = []

    def showPage(self):
        self._seiten.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        gesamt = len(self._seiten)
        for zustand in self._seiten:
            self.__dict__.update(zustand)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRAU)
            self.drawString(_RAND, 10 * mm, self.fusstext)
            self.drawRightString(_BREITE - _RAND, 10 * mm,
                                 f"Seite {self._pageNumber} von {gesamt}")
            super().showPage()
        super().save()


# ── Bausteine ─────────────────────────────────────────────────────────────

def _fmt_datum(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if len(iso or "") == 10 else (iso or "")


def _kopf(db: Session, user: User, b: UbBesuch) -> list:
    logo_bytes, _ = get_logo_bytes(db)
    links = [Paragraph("Protokoll Unterrichtsbesuch", S_TITEL),
             Paragraph(_p(get_school_name(db)), S_UNTER)]
    rechts = ""
    if logo_bytes:
        try:
            with PILImage.open(io.BytesIO(logo_bytes)) as im:
                w, h = im.size
            hoehe = 14 * mm
            rechts = Image(io.BytesIO(logo_bytes), width=hoehe * w / h, height=hoehe)
        except Exception:
            rechts = ""
    t = Table([[links, rechts]], colWidths=[NUTZBREITE - 45 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLAU),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [t, Spacer(1, 5 * mm)]


def _kopfdaten(db: Session, user: User, b: UbBesuch) -> list:
    a = b.anwaerter
    anwaerter = _p(a.name if a else "")
    if a and a.faecher:
        anwaerter += f' <font color="#666666">· {_p(a.faecher)}</font>'
    zeit = _fmt_datum(b.datum)
    if b.beginn:
        zeit += f", {b.beginn}" + (f" – {b.ende}" if b.ende else "") + " Uhr"
    zeilen = [
        ("Anwärter/in", anwaerter),
        ("Datum", _p(zeit)),
        ("Klasse / Raum", _p(" / ".join(x for x in (b.klasse, b.raum) if x) or "—")),
        ("Thema", _p(b.thema or "—")),
    ]
    if b.lernziele:
        zeilen.append(("Lernziele", _p(b.lernziele)))
    sp = ub.schwerpunkte(db, b.id)
    if sp:
        zeilen.append(("Beratungs-<br/>schwerpunkte",
                       "<br/>".join(f"{i}. {_p(k.name)}" for i, k in enumerate(sp, 1))))
    zeilen.append(("Besucht von", _p(user.full_name or user.username)))

    t = Table([[Paragraph(k, S_LABEL), Paragraph(v, S_TEXT)] for k, v in zeilen],
              colWidths=[32 * mm, NUTZBREITE - 32 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINIE),
    ]))
    return [t, Spacer(1, 4 * mm)]


def _legende(kategorien: list, genutzt: set[int], wertungen_genutzt: set[str]) -> list:
    """Nur was im Protokoll auch vorkommt — sonst erklärt die Legende
    Symbole, die der Leser nie zu sehen bekommt."""
    zellen = []
    for k in kategorien:
        if k.id in genutzt:
            zellen.append((k.icon, k.farbe, k.name))
    for key, w in ub.WERTUNGEN.items():
        if key in wertungen_genutzt:
            zellen.append((w["icon"], w["farbe"], w["label"]))
    if not zellen:
        return []
    zeile = []
    breiten = []
    for ic, fa, name in zellen:
        zeile += [IconFlowable(ic, fa, 4 * mm), Paragraph(_p(name), S_KLEIN)]
        breiten += [5.5 * mm, 30 * mm]
    t = Table([zeile], colWidths=breiten, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [t, Spacer(1, 3 * mm)]


def _foto(e) -> Image | None:
    if not e.file_uuid:
        return None
    pfad = file_store.resolve(e.file_uuid, e.filename)
    if not pfad:
        return None
    try:
        with PILImage.open(pfad) as im:
            w, h = im.size
    except Exception:
        return None
    breite = min(70 * mm, w)
    hoehe = breite * h / w
    if hoehe > 60 * mm:           # Hochkant-Fotos nicht seitenfüllend
        hoehe = 60 * mm
        breite = hoehe * w / h
    img = Image(str(pfad), width=breite, height=hoehe)
    img.hAlign = "LEFT"
    return img


def _eintrag_zeile(e, kat, zuordnung: str, mit_fotos: bool) -> Table:
    inhalt = [Paragraph(_p(e.text), S_TEXT)] if e.text else []
    meta = []
    if kat:
        meta.append(f'<font color="{kat.farbe}"><b>{_p(kat.name)}</b></font>')
    if zuordnung:
        meta.append(_p(zuordnung))
    w = ub.WERTUNGEN.get(e.wertung)
    if w:
        meta.append(f'<font color="{w["farbe"]}">{_p(w["label"])}</font>')
    if meta:
        inhalt.append(Paragraph(" · ".join(meta), S_KLEIN))
    if mit_fotos:
        img = _foto(e)
        if img:
            inhalt += [Spacer(1, 1.5 * mm), img]
    icon = IconFlowable(kat.icon, kat.farbe) if kat else ""
    w_icon = IconFlowable(w["icon"], w["farbe"], 4 * mm) if w else ""
    t = Table([[Paragraph(e.zeit or "", S_ZEIT), icon, inhalt, w_icon]],
              colWidths=[13 * mm, 8 * mm, NUTZBREITE - 27 * mm, 6 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINIE),
    ]))
    return t


def _phasen_band(e, phase) -> Table:
    name = phase.name if phase else "Phase"
    t = Table([[Paragraph(e.zeit or "", S_ZEIT), Paragraph(_p(name), S_PHASE)]],
              colWidths=[13 * mm, NUTZBREITE - 13 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLAU_HELL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _textabschnitt(titel: str, inhalt: str) -> list:
    if not (inhalt or "").strip():
        return []
    return [Paragraph(titel, S_H2), Paragraph(_p(inhalt), S_TEXT)]


# ── Einstieg ──────────────────────────────────────────────────────────────

def erzeuge(db: Session, user: User, b: UbBesuch, mit_fotos: bool = True) -> bytes:
    kategorien = ub.liste(db, user, "kategorien")
    kat_map = {k.id: k for k in kategorien}
    phasen = {p.id: p for p in ub.liste(db, user, "phasen")}
    kriterien = {k.id: k for k in ub.liste(db, user, "kriterien")}
    alle = ub.eintraege(db, b.id)
    normale = [e for e in alle if e.art == "eintrag"]

    story = _kopf(db, user, b) + _kopfdaten(db, user, b)
    story.append(Paragraph("Unterrichtsverlauf", S_H2))
    story += _legende(kategorien, {e.kategorie_id for e in normale},
                      {e.wertung for e in normale})

    if not alle:
        story.append(Paragraph("Noch keine Einträge erfasst.", S_KLEIN))
    for e in alle:
        if e.art == "phase":
            story.append(Spacer(1, 2 * mm))
            story.append(_phasen_band(e, phasen.get(e.phase_id)))
            continue
        if e.kriterium_id and e.kriterium_id in kriterien:
            zuordnung = kriterien[e.kriterium_id].name
        else:
            zuordnung = ""
        story.append(_eintrag_zeile(e, kat_map.get(e.kategorie_id), zuordnung, mit_fotos))

    story += _textabschnitt("Reflexionsgespräch", b.reflexion)
    story += _textabschnitt("Vereinbarungen", b.vereinbarungen)

    puffer = io.BytesIO()
    name = b.anwaerter.name if b.anwaerter else ""
    doc = SimpleDocTemplate(
        puffer, pagesize=A4, leftMargin=_RAND, rightMargin=_RAND,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Unterrichtsbesuch {name} {_fmt_datum(b.datum)}".strip(),
        author=user.full_name or user.username)

    class _Canvas(_NummerCanvas):
        fusstext = _sauber(f"Unterrichtsbesuch · {name} · {_fmt_datum(b.datum)}")

    doc.build(story, canvasmaker=_Canvas)
    return puffer.getvalue()
