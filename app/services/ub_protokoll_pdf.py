"""Protokoll eines Unterrichtsbesuchs als PDF (reportlab).

Zeichnet nur, was `ub_protokoll.aufbereiten()` liefert — die Entscheidung,
welcher Eintrag in welcher Ordnung wo steht, fällt dort (dieselbe für ODT).

Die Piktogramme zeichnet `IconFlowable` direkt aus den Zeichenanweisungen in
`app/services/unterrichtsbesuche.py` — dieselben Daten, aus denen der Browser
sein SVG baut. So sehen Bildschirm und Ausdruck gleich aus, ohne dass der
Container eine SVG-Bibliothek braucht.

Schrift ist Helvetica (WinAnsi). Zeichen außerhalb davon (Emoji, Pfeile aus
der Handy-Tastatur) werden vorher ersetzt, sonst stünden im PDF leere Kästchen.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Flowable, Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from sqlalchemy.orm import Session

from app.branding import get_logo_bytes
from app.models import UbBesuch, User
from app.services import unterrichtsbesuche as ub
from app.services.ub_protokoll import EintragAnsicht, Protokoll, aufbereiten, pfad_befehle

BLAU = colors.HexColor("#00639C")
BLAU_HELL = colors.HexColor("#E6F3FA")
GELB_HELL = colors.HexColor("#FDF6E6")
GRAU = colors.HexColor("#666666")
LINIE = colors.HexColor("#E2E5E9")

_BREITE, _HOEHE = A4
_RAND = 18 * mm
# Der Rahmen von SimpleDocTemplate hat 6 pt Innenabstand je Seite — Tabellen
# in voller Randbreite ragten sonst links heraus und stünden versetzt zum Text.
NUTZBREITE = _BREITE - 2 * _RAND - 12


# ── Text ──────────────────────────────────────────────────────────────────

_ERSATZ = {"→": "->", "←": "<-", "⇒": "=>", "✓": "(ok)", "✔": "(ok)",
           "≤": "<=", "≥": ">=", "≠": "!=", "−": "-"}


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
S_H3 = _stil("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13)
S_LABEL = _stil("label", fontName="Helvetica-Bold", fontSize=8.5, textColor=GRAU)
S_TEXT = _stil("text")
S_KLEIN = _stil("klein", fontSize=8, leading=10, textColor=GRAU)
S_ZEIT = _stil("zeit", fontSize=8.5, textColor=GRAU)
S_PHASE = _stil("phase", fontName="Helvetica-Bold", fontSize=10, textColor=BLAU)
S_SPALTE = _stil("spalte", fontName="Helvetica-Bold", fontSize=9, textColor=GRAU)


# ── Piktogramme ───────────────────────────────────────────────────────────

def _pfad(c, d: str) -> None:
    p = c.beginPath()
    for b in pfad_befehle(d):
        if b[0] == "M":
            p.moveTo(b[1], b[2])
        elif b[0] == "L":
            p.lineTo(b[1], b[2])
        elif b[0] == "C":
            p.curveTo(*b[1:])
        elif b[0] == "Z":
            p.close()
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

def _tab(daten, breiten, stil, **kw) -> Table:
    t = Table(daten, colWidths=breiten, **kw)
    t.setStyle(TableStyle(stil))
    return t


_OHNE_RAND = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]


def _kopf(db: Session, pr: Protokoll) -> list:
    logo_bytes, _ = get_logo_bytes(db)
    links = [Paragraph("Protokoll Unterrichtsbesuch", S_TITEL), Paragraph(_p(pr.schule), S_UNTER)]
    rechts = ""
    if logo_bytes:
        try:
            with PILImage.open(io.BytesIO(logo_bytes)) as im:
                w, h = im.size
            hoehe = 14 * mm
            rechts = Image(io.BytesIO(logo_bytes), width=hoehe * w / h, height=hoehe)
        except Exception:
            rechts = ""
    t = _tab([[links, rechts]], [NUTZBREITE - 45 * mm, 45 * mm], _OHNE_RAND + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLAU), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])
    return [t, Spacer(1, 5 * mm)]


def _kopfdaten(pr: Protokoll) -> list:
    zeilen = [(k, _p(v)) for k, v in pr.kopf]
    if pr.schwerpunkte:
        zeilen.append(("Beratungs-<br/>schwerpunkte",
                       "<br/>".join(f"{i}. {_p(n)}" for i, n in enumerate(pr.schwerpunkte, 1))))
    zeilen.append(("Besucht von", _p(pr.autor)))
    t = _tab([[Paragraph(k, S_LABEL), Paragraph(v, S_TEXT)] for k, v in zeilen],
             [32 * mm, NUTZBREITE - 32 * mm], [
                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                 ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINIE)])
    out = [t, Spacer(1, 4 * mm)]
    if pr.vorige:
        out.append(_tab([[[Paragraph(f"Vereinbarungen aus dem Besuch am {pr.vorige['datum']}", S_LABEL),
                           Paragraph(_p(pr.vorige["text"]), S_TEXT)]]], [NUTZBREITE], [
            ("BACKGROUND", (0, 0), (-1, -1), GELB_HELL),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        out.append(Spacer(1, 3 * mm))
    return out


def _legende(pr: Protokoll) -> list:
    if not pr.legende:
        return []
    zeile, breiten = [], []
    for k in pr.legende:
        zeile += [IconFlowable(k.icon, k.farbe, 4 * mm), Paragraph(_p(k.name), S_KLEIN)]
        breiten += [5.5 * mm, 30 * mm]
    return [_tab([zeile], breiten, _OHNE_RAND + [("VALIGN", (0, 0), (-1, -1), "MIDDLE")],
                 hAlign="LEFT"), Spacer(1, 3 * mm)]


def _foto(a: EintragAnsicht, max_breite: float) -> Image | None:
    if not a.foto:
        return None
    try:
        with PILImage.open(a.foto) as im:
            w, h = im.size
    except Exception:
        return None
    breite = min(max_breite, 70 * mm, w)
    hoehe = breite * h / w
    if hoehe > 60 * mm:           # Hochkant-Fotos nicht seitenfüllend
        hoehe = 60 * mm
        breite = hoehe * w / h
    img = Image(str(a.foto), width=breite, height=hoehe)
    img.hAlign = "LEFT"
    return img


def _meta(a: EintragAnsicht, kat=True, zuordnung=True, phase=False) -> str:
    teile = []
    if kat and a.kat:
        teile.append(f'<font color="{a.kat.farbe}"><b>{_p(a.kat.name)}</b></font>')
    if zuordnung and a.zuordnung:
        teile.append(_p(a.zuordnung))
    if phase and a.phase:
        teile.append(_p(a.phase))
    if a.wertung:
        teile.append(f'<font color="{a.wertung["farbe"]}">{_p(a.wertung["label"])}</font>')
    if a.bezug:
        teile.append("<i>" + _p(a.bezug) + "</i>")
    return " · ".join(teile)


def _inhalt(a: EintragAnsicht, breite: float, pr: Protokoll, **meta_kw) -> list:
    out = [Paragraph(_p(a.text), S_TEXT)] if a.text else []
    m = _meta(a, **meta_kw)
    if m:
        out.append(Paragraph(m, S_KLEIN))
    if pr.mit_fotos:
        img = _foto(a, breite)
        if img:
            out += [Spacer(1, 1.5 * mm), img]
    return out


def _eintrag_zeile(a: EintragAnsicht, pr: Protokoll, **meta_kw) -> Table:
    textbreite = NUTZBREITE - 27 * mm
    icon = IconFlowable(a.kat.icon, a.kat.farbe) if a.kat else ""
    w_icon = IconFlowable(a.wertung["icon"], a.wertung["farbe"], 4 * mm) if a.wertung else ""
    return _tab([[Paragraph(a.zeit, S_ZEIT), icon, _inhalt(a, textbreite, pr, **meta_kw), w_icon]],
                [13 * mm, 8 * mm, textbreite, 6 * mm], [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINIE)])


def _phasen_band(zeit: str, name: str) -> Table:
    return _tab([[Paragraph(zeit, S_ZEIT), Paragraph(_p(name), S_PHASE)]],
                [13 * mm, NUTZBREITE - 13 * mm], [
                    ("BACKGROUND", (0, 0), (-1, -1), BLAU_HELL),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (0, 0), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])


def _gruppen_kopf(titel: str, kat, hinweis: str) -> Table:
    text = _p(titel) + (f'  <font size="8" color="#666666">({_p(hinweis)})</font>' if hinweis else "")
    # ohne Piktogramm keine leere Symbolspalte — sonst stünde die Überschrift eingerückt
    zeile, breiten = ([IconFlowable(kat.icon, kat.farbe, 5.5 * mm), Paragraph(text, S_H3)],
                      [8 * mm, NUTZBREITE - 8 * mm]) if kat else ([Paragraph(text, S_H3)], [NUTZBREITE])
    return _tab([zeile], breiten, _OHNE_RAND + [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, BLAU)])


def _mini(a: EintragAnsicht, breite: float, pr: Protokoll) -> Table:
    """Ein Eintrag in einer Zelle der zweispaltigen Ansicht."""
    icon = IconFlowable(a.kat.icon, a.kat.farbe, 4.2 * mm) if a.kat else ""
    kopf = f'<font color="#666666">{_p(a.zeit)}</font>'
    if a.text:
        kopf += "  " + _p(a.text)
    inhalt = [Paragraph(kopf, S_TEXT)]
    m = _meta(a, kat=True, zuordnung=True)
    if m:
        inhalt.append(Paragraph(m, S_KLEIN))
    if pr.mit_fotos:
        img = _foto(a, breite - 8 * mm)
        if img:
            inhalt += [Spacer(1, 1.5 * mm), img]
    return _tab([[icon, inhalt]], [6 * mm, breite - 6 * mm], _OHNE_RAND + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])


def _zweispaltig(bloecke: list, pr: Protokoll) -> list:
    halb = NUTZBREITE / 2
    zellbreite = halb - 8
    daten = [[Paragraph("Verlauf", S_SPALTE), Paragraph("Kommentar", S_SPALTE)]]
    stil = [("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, BLAU),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for blk in bloecke:
        r = len(daten)
        if blk.typ == "phase":
            daten.append([Paragraph(f'<font color="#666666" size="8.5">{_p(blk.zeit)}</font>  '
                                    + _p(blk.titel), S_PHASE), ""])
            stil += [("SPAN", (0, r), (1, r)), ("BACKGROUND", (0, r), (1, r), BLAU_HELL)]
            continue
        links = [_mini(blk.links, zellbreite, pr)] if blk.links else ""
        rechts = [_mini(a, zellbreite, pr) for a in blk.rechts] or ""
        daten.append([links, rechts])
        stil += [("LINEBELOW", (0, r), (-1, r), 0.4, LINIE),
                 ("LINEAFTER", (0, r), (0, r), 0.4, LINIE)]
    return [_tab(daten, [halb, halb], stil, repeatRows=1)]


def _textabschnitt(titel: str, inhalt: str) -> list:
    if not (inhalt or "").strip():
        return []
    return [Paragraph(titel, S_H2), Paragraph(_p(inhalt), S_TEXT)]


UEBERSCHRIFT = {
    "chronologisch": "Unterrichtsverlauf",
    "kategorie": "Einträge nach Kategorie",
    "kriterium": "Einträge nach Beratungsschwerpunkt",
    "zweispaltig": "Verlauf und Kommentare",
}


# ── Einstieg ──────────────────────────────────────────────────────────────

def erzeuge(db: Session, user: User, b: UbBesuch, mit_fotos: bool = True,
            ordnung: str | None = None) -> bytes:
    pr = aufbereiten(db, user, b, ordnung, mit_fotos)

    story = _kopf(db, pr) + _kopfdaten(pr)
    story.append(Paragraph(UEBERSCHRIFT[pr.ordnung], S_H2))
    story += _legende(pr)

    if not pr.bloecke:
        story.append(Paragraph("Noch keine Einträge erfasst.", S_KLEIN))
    elif pr.ordnung == "zweispaltig":
        story += _zweispaltig(pr.bloecke, pr)
    else:
        for blk in pr.bloecke:
            if blk.typ == "phase":
                story += [Spacer(1, 2 * mm), _phasen_band(blk.zeit, blk.titel)]
            elif blk.typ == "eintrag":
                story.append(_eintrag_zeile(blk.eintrag, pr))
            elif blk.typ == "gruppe":
                zeilen = [_eintrag_zeile(a, pr, kat=pr.ordnung != "kategorie",
                                         zuordnung=pr.ordnung != "kriterium", phase=True)
                          for a in blk.eintraege]
                if not zeilen:
                    zeilen = [Paragraph("Dazu wurde nichts notiert.", S_KLEIN)]
                # Gruppenkopf nie allein am Seitenende
                story += [Spacer(1, 3 * mm),
                          KeepTogether([_gruppen_kopf(blk.titel, blk.kat, blk.hinweis), zeilen[0]])]
                story += zeilen[1:]

    story += _textabschnitt("Reflexionsgespräch", pr.reflexion)
    story += _textabschnitt("Vereinbarungen", pr.vereinbarungen)

    puffer = io.BytesIO()
    doc = SimpleDocTemplate(
        puffer, pagesize=A4, leftMargin=_RAND, rightMargin=_RAND,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=_sauber(f"Unterrichtsbesuch {pr.anwaerter} {pr.datum}").strip(),
        author=_sauber(pr.autor))

    class _Canvas(_NummerCanvas):
        fusstext = _sauber(f"Unterrichtsbesuch · {pr.anwaerter} · {pr.datum}")

    doc.build(story, canvasmaker=_Canvas)
    return puffer.getvalue()
