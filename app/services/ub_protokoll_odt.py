"""Protokoll eines Unterrichtsbesuchs als ODT (OpenDocument-Text).

Ohne zusätzliche Bibliothek: Ein ODT ist ein ZIP mit ein paar XML-Dateien.
Pflicht ist dabei nur eine Reihenfolge-Regel — die Datei `mimetype` steht
als ERSTE und UNKOMPRIMIERT im Archiv, sonst lehnen manche Programme das
Dokument ab.

Inhalt und Ordnung kommen aus `ub_protokoll.aufbereiten()` — dieselbe
Aufbereitung wie im PDF. Das ODT ist bewusst schlicht formatiert (Tabellen,
wenige Absatzvorlagen), damit man es in LibreOffice oder Word gut
weiterbearbeiten kann.

Piktogramme werden als PNG eingebettet (mit Pillow aus denselben
Zeichenanweisungen gerastert wie im PDF): PNG zeigen LibreOffice, Word und
Google Docs gleichermaßen an, SVG nicht überall.
"""
from __future__ import annotations

import io
import zipfile
from functools import lru_cache
from xml.sax.saxutils import escape, quoteattr

from PIL import Image as PILImage, ImageDraw
from sqlalchemy.orm import Session

from app.branding import get_logo_bytes
from app.models import UbBesuch, User
from app.services import unterrichtsbesuche as ub
from app.services.ub_protokoll import Block, EintragAnsicht, Protokoll, aufbereiten, pfad_befehle
from app.services.ub_protokoll_pdf import UEBERSCHRIFT

BREITE_CM = 17.4        # A4 minus 2 × 1,8 cm Rand


# ── Piktogramme als PNG ──────────────────────────────────────────────────

def _bezier(p0, p1, p2, p3, schritte=14):
    for i in range(1, schritte + 1):
        t = i / schritte
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _linienzuege(d: str) -> list[list[tuple[float, float]]]:
    zuege: list[list] = []
    akt: list = []
    start = (0.0, 0.0)
    for b in pfad_befehle(d):
        if b[0] == "M":
            if len(akt) > 1:
                zuege.append(akt)
            akt = [(b[1], b[2])]
            start = (b[1], b[2])
        elif b[0] == "L":
            akt.append((b[1], b[2]))
        elif b[0] == "C":
            akt.extend(_bezier(akt[-1], (b[1], b[2]), (b[3], b[4]), (b[5], b[6])))
        elif b[0] == "Z":
            akt.append(start)
    if len(akt) > 1:
        zuege.append(akt)
    return zuege


@lru_cache(maxsize=128)
def icon_png(name: str, farbe: str, px: int = 96) -> bytes:
    """Rastert ein Piktogramm. 4-fach überabgetastet und dann verkleinert,
    damit die Kanten glatt werden; runde Linienenden über Kreise an jedem
    Stützpunkt (Pillow kennt keine runden Kappen)."""
    ss = 4
    groesse = px * ss
    f = groesse / 24.0
    w = 1.9 * f
    r = w / 2
    im = PILImage.new("RGBA", (groesse, groesse), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    rgb = tuple(int(farbe.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    _, teile = ub.ICONS.get(name, ub.ICONS[ub.STANDARD_ICON])
    for t in teile:
        if t[0] == "path":
            for zug in _linienzuege(t[1]):
                pts = [(x * f, y * f) for x, y in zug]
                dr.line(pts, fill=rgb, width=int(round(w)), joint="curve")
                for x, y in pts:
                    dr.ellipse((x - r, y - r, x + r, y + r), fill=rgb)
        elif t[0] == "circle":
            cx, cy, rad = t[1] * f, t[2] * f, t[3] * f
            dr.ellipse((cx - rad - r, cy - rad - r, cx + rad + r, cy + rad + r), fill=rgb)
            innen = rad - r
            dr.ellipse((cx - innen, cy - innen, cx + innen, cy + innen), fill=(0, 0, 0, 0))
        elif t[0] == "rect":
            x, y, bw, bh, rx = (v * f for v in t[1:6])
            dr.rounded_rectangle((x, y, x + bw, y + bh), radius=rx, outline=rgb, width=int(round(w)))
    im = im.resize((px, px), PILImage.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ── XML-Bausteine ────────────────────────────────────────────────────────

def _t(text: str) -> str:
    """Benutzertext → ODF-Text: escapen, Zeilenumbrüche und Mehrfach-
    Leerzeichen erhalten."""
    out = []
    for i, zeile in enumerate((text or "").split("\n")):
        if i:
            out.append("<text:line-break/>")
        z = escape(zeile)
        # ODF schluckt Mehrfach-Leerzeichen, deshalb text:s
        while "  " in z:
            z = z.replace("  ", ' <text:s/>', 1)
        out.append(z)
    return "".join(out)


class _Dok:
    """Sammelt Bilder und Zeichenvorlagen (Farben) während des Aufbaus."""

    def __init__(self):
        self.bilder: dict[str, tuple[bytes, str]] = {}   # Pfad → (Daten, Mime)
        self.farben: set[str] = set()
        self._n = 0

    def bild(self, daten: bytes, endung: str, mime: str, breite_cm: float, hoehe_cm: float,
             schluessel: str | None = None) -> str:
        pfad = f"Pictures/{schluessel or ('b' + str(len(self.bilder)))}.{endung}"
        self.bilder.setdefault(pfad, (daten, mime))
        self._n += 1
        return (f'<draw:frame draw:name="Bild{self._n}" text:anchor-type="as-char" '
                f'svg:width="{breite_cm:.2f}cm" svg:height="{hoehe_cm:.2f}cm" '
                f'draw:z-index="0" draw:style-name="fr">'
                f'<draw:image xlink:href="{pfad}" xlink:type="simple" xlink:show="embed" '
                f'xlink:actuate="onLoad"/></draw:frame>')

    def icon(self, name: str, farbe: str, cm: float = 0.5) -> str:
        return self.bild(icon_png(name, farbe), "png", "image/png", cm, cm,
                         schluessel=f"icon_{name}_{farbe.lstrip('#')}")

    def farbig(self, farbe: str, text: str, fett: bool = False) -> str:
        self.farben.add(farbe)          # je Farbe entstehen T_… und TF_… (fett)
        stil = f"T{'F' if fett else ''}_{farbe.lstrip('#')}"
        return f'<text:span text:style-name="{stil}">{text}</text:span>'


def _meta(dok: _Dok, a: EintragAnsicht, kat=True, zuordnung=True, phase=False) -> str:
    teile = []
    if kat and a.kat:
        teile.append(dok.farbig(a.kat.farbe, escape(a.kat.name), fett=True))
    if zuordnung and a.zuordnung:
        teile.append(escape(a.zuordnung))
    if phase and a.phase:
        teile.append(escape(a.phase))
    if a.wertung:
        teile.append(dok.farbig(a.wertung["farbe"], escape(a.wertung["label"])))
    if a.bezug:
        teile.append(f'<text:span text:style-name="TKursiv">{escape(a.bezug)}</text:span>')
    return " · ".join(teile)


def _foto(dok: _Dok, a: EintragAnsicht, max_cm: float) -> str:
    if not a.foto:
        return ""
    try:
        with PILImage.open(a.foto) as im:
            w, h = im.size
            png = im.format == "PNG"      # Skizzen kommen als PNG
        daten = a.foto.read_bytes()
    except Exception:
        return ""
    breite = min(max_cm, 7.0)
    hoehe = breite * h / w
    if hoehe > 6.0:
        hoehe = 6.0
        breite = hoehe * w / h
    # Rahmen vorher bauen: Ein über Zeilen umbrochener Ausdruck IN einem
    # f-String geht erst ab Python 3.12 — der Container läuft auf 3.11.
    rahmen = dok.bild(daten, "png" if png else "jpg", "image/png" if png else "image/jpeg",
                      breite, hoehe, schluessel=f"foto_{a.id}")
    return f'<text:p text:style-name="PFoto">{rahmen}</text:p>'


def _inhalt(dok: _Dok, a: EintragAnsicht, pr: Protokoll, max_cm: float, **meta_kw) -> str:
    out = ""
    if a.text:
        out += f'<text:p text:style-name="PText">{_t(a.text)}</text:p>'
    m = _meta(dok, a, **meta_kw)
    if m:
        out += f'<text:p text:style-name="PMeta">{m}</text:p>'
    if pr.mit_fotos:
        out += _foto(dok, a, max_cm)
    return out or '<text:p text:style-name="PText"/>'


def _zelle(inhalt: str, stil: str = "ZLinie", spannweite: int = 0) -> str:
    span = f' table:number-columns-spanned="{spannweite}"' if spannweite else ""
    zusatz = "<table:covered-table-cell/>" * (spannweite - 1 if spannweite else 0)
    return (f'<table:table-cell table:style-name="{stil}" office:value-type="string"{span}>'
            f'{inhalt}</table:table-cell>{zusatz}')


def _verlauf_tabelle(dok: _Dok, pr: Protokoll, bloecke, name: str, **meta_kw) -> str:
    zeilen = []
    for blk in bloecke:
        if blk.typ == "phase":
            zeilen.append("<table:table-row>" + _zelle(
                f'<text:p text:style-name="PPhase"><text:span text:style-name="TZeit">{escape(blk.zeit)}</text:span>'
                f'<text:tab/>{escape(blk.titel)}</text:p>', "ZPhase", 4) + "</table:table-row>")
            continue
        a = blk.eintrag
        icon = dok.icon(a.kat.icon, a.kat.farbe) if a.kat else ""
        w_icon = dok.icon(a.wertung["icon"], a.wertung["farbe"], 0.4) if a.wertung else ""
        zeilen.append(
            "<table:table-row>"
            + _zelle(f'<text:p text:style-name="PZeit">{escape(a.zeit)}</text:p>')
            + _zelle(f'<text:p text:style-name="PText">{icon}</text:p>')
            + _zelle(_inhalt(dok, a, pr, 13.0, **meta_kw))
            + _zelle(f'<text:p text:style-name="PText">{w_icon}</text:p>')
            + "</table:table-row>")
    return (f'<table:table table:name="{name}" table:style-name="TabBreit">'
            '<table:table-column table:style-name="SpZeit"/><table:table-column table:style-name="SpIcon"/>'
            '<table:table-column table:style-name="SpText"/><table:table-column table:style-name="SpWert"/>'
            + "".join(zeilen) + "</table:table>")


def _mini(dok: _Dok, a: EintragAnsicht, pr: Protokoll) -> str:
    icon = dok.icon(a.kat.icon, a.kat.farbe, 0.42) if a.kat else ""
    kopf = f'{icon} <text:span text:style-name="TZeit">{escape(a.zeit)}</text:span>'
    if a.text:
        kopf += " " + _t(a.text)
    out = f'<text:p text:style-name="PText">{kopf}</text:p>'
    m = _meta(dok, a, kat=True, zuordnung=True)
    if m:
        out += f'<text:p text:style-name="PMeta">{m}</text:p>'
    if pr.mit_fotos:
        out += _foto(dok, a, 7.8)
    return out


def _zweispaltig(dok: _Dok, pr: Protokoll) -> str:
    zeilen = ['<table:table-header-rows><table:table-row>'
              + _zelle('<text:p text:style-name="PSpalte">Verlauf</text:p>', "ZKopf")
              + _zelle('<text:p text:style-name="PSpalte">Kommentar</text:p>', "ZKopf")
              + "</table:table-row></table:table-header-rows>"]
    for blk in pr.bloecke:
        if blk.typ == "phase":
            zeilen.append("<table:table-row>" + _zelle(
                f'<text:p text:style-name="PPhase"><text:span text:style-name="TZeit">{escape(blk.zeit)}</text:span>'
                f'<text:tab/>{escape(blk.titel)}</text:p>', "ZPhase", 2) + "</table:table-row>")
            continue
        links = _mini(dok, blk.links, pr) if blk.links else '<text:p text:style-name="PText"/>'
        rechts = "".join(_mini(dok, a, pr) for a in blk.rechts) or '<text:p text:style-name="PText"/>'
        zeilen.append("<table:table-row>" + _zelle(links, "ZLinks") + _zelle(rechts) + "</table:table-row>")
    return ('<table:table table:name="Verlauf" table:style-name="TabBreit">'
            '<table:table-column table:style-name="SpHalb" table:number-columns-repeated="2"/>'
            + "".join(zeilen) + "</table:table>")


def _kopfdaten(pr: Protokoll) -> str:
    zeilen = list(pr.kopf)
    if pr.schwerpunkte:
        zeilen.append(("Beratungsschwerpunkte",
                       "\n".join(f"{i}. {n}" for i, n in enumerate(pr.schwerpunkte, 1))))
    zeilen.append(("Besucht von", pr.autor))
    rows = "".join(
        "<table:table-row>"
        + _zelle(f'<text:p text:style-name="PLabel">{escape(k)}</text:p>')
        + _zelle(f'<text:p text:style-name="PText">{_t(v)}</text:p>')
        + "</table:table-row>" for k, v in zeilen)
    return ('<table:table table:name="Kopfdaten" table:style-name="TabBreit">'
            '<table:table-column table:style-name="SpLabel"/><table:table-column table:style-name="SpWert2"/>'
            + rows + "</table:table>")


# ── Dokument zusammensetzen ──────────────────────────────────────────────

_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
       'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
       'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
       'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
       'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
       'xmlns:xlink="http://www.w3.org/1999/xlink" '
       'xmlns:dc="http://purl.org/dc/elements/1.1/" '
       'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
       'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
       'office:version="1.3"')

_FONTS = ('<office:font-face-decls><style:font-face style:name="Arial" svg:font-family="Arial" '
          'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>')


def _styles_xml(fusstext: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {_NS}>{_FONTS}
<office:styles>
 <style:default-style style:family="paragraph">
  <style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0cm"/>
  <style:text-properties style:font-name="Arial" fo:font-size="10pt" fo:language="de" fo:country="DE"/>
 </style:default-style>
 <style:style style:name="Standard" style:family="paragraph" style:class="text"/>
 <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph" style:default-outline-level="1">
  <style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0.1cm"/>
  <style:text-properties fo:font-size="17pt" fo:font-weight="bold" fo:color="#00639C"/>
 </style:style>
 <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph" style:default-outline-level="2">
  <style:paragraph-properties fo:margin-top="0.45cm" fo:margin-bottom="0.15cm" fo:keep-with-next="always"/>
  <style:text-properties fo:font-size="12pt" fo:font-weight="bold" fo:color="#00639C"/>
 </style:style>
 <style:style style:name="Heading_20_3" style:display-name="Heading 3" style:family="paragraph" style:default-outline-level="3">
  <style:paragraph-properties fo:margin-top="0.35cm" fo:margin-bottom="0.1cm" fo:keep-with-next="always"
    fo:border-bottom="0.6pt solid #00639C" fo:padding-bottom="0.05cm"/>
  <style:text-properties fo:font-size="10.5pt" fo:font-weight="bold"/>
 </style:style>
 <style:style style:name="Footer" style:family="paragraph">
  <style:paragraph-properties><style:tab-stops><style:tab-stop style:position="17.4cm" style:type="right"/></style:tab-stops></style:paragraph-properties>
  <style:text-properties fo:font-size="7.5pt" fo:color="#666666"/>
 </style:style>
</office:styles>
<office:automatic-styles>
 <style:page-layout style:name="pm1">
  <style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" fo:margin-top="1.5cm"
    fo:margin-bottom="1.2cm" fo:margin-left="1.8cm" fo:margin-right="1.8cm"/>
  <style:footer-style><style:header-footer-properties fo:min-height="0.6cm" fo:margin-top="0.4cm"/></style:footer-style>
 </style:page-layout>
</office:automatic-styles>
<office:master-styles>
 <style:master-page style:name="Standard" style:page-layout-name="pm1">
  <style:footer><text:p text:style-name="Footer">{escape(fusstext)}<text:tab/>Seite <text:page-number text:select-page="current"/></text:p></style:footer>
 </style:master-page>
</office:master-styles>
</office:document-styles>'''


def _auto_styles(dok: _Dok) -> str:
    farb = []
    for f in sorted(dok.farben):
        farb.append(f'<style:style style:name="T_{f.lstrip("#")}" style:family="text">'
                    f'<style:text-properties fo:color="{f}"/></style:style>')
        farb.append(f'<style:style style:name="TF_{f.lstrip("#")}" style:family="text">'
                    f'<style:text-properties fo:color="{f}" fo:font-weight="bold"/></style:style>')
    rahmen = 'fo:border-bottom="0.5pt solid #E2E5E9"'
    return f'''<office:automatic-styles>
 <style:style style:name="PUnter" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:margin-bottom="0.2cm" fo:border-bottom="1.2pt solid #00639C" fo:padding-bottom="0.15cm"/>
  <style:text-properties fo:font-size="9pt" fo:color="#666666"/></style:style>
 <style:style style:name="PText" style:family="paragraph" style:parent-style-name="Standard"/>
 <style:style style:name="PMeta" style:family="paragraph" style:parent-style-name="Standard">
  <style:text-properties fo:font-size="8pt" fo:color="#666666"/></style:style>
 <style:style style:name="PFoto" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:margin-top="0.1cm"/></style:style>
 <style:style style:name="PLabel" style:family="paragraph" style:parent-style-name="Standard">
  <style:text-properties fo:font-size="8.5pt" fo:font-weight="bold" fo:color="#666666"/></style:style>
 <style:style style:name="PZeit" style:family="paragraph" style:parent-style-name="Standard">
  <style:text-properties fo:font-size="8.5pt" fo:color="#666666"/></style:style>
 <style:style style:name="PSpalte" style:family="paragraph" style:parent-style-name="Standard">
  <style:text-properties fo:font-size="9pt" fo:font-weight="bold" fo:color="#666666"/></style:style>
 <style:style style:name="PPhase" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties><style:tab-stops><style:tab-stop style:position="1.3cm"/></style:tab-stops></style:paragraph-properties>
  <style:text-properties fo:font-weight="bold" fo:color="#00639C"/></style:style>
 <style:style style:name="PVorige" style:family="paragraph" style:parent-style-name="Standard">
  <style:paragraph-properties fo:background-color="#FDF6E6" fo:padding="0.15cm" fo:margin-bottom="0.2cm"/></style:style>
 <style:style style:name="TZeit" style:family="text"><style:text-properties fo:color="#666666" fo:font-weight="normal" fo:font-size="8.5pt"/></style:style>
 <style:style style:name="TKursiv" style:family="text"><style:text-properties fo:font-style="italic"/></style:style>
 <style:style style:name="TGrau" style:family="text"><style:text-properties fo:color="#666666" fo:font-size="8pt" fo:font-weight="normal"/></style:style>
 {"".join(farb)}
 <style:style style:name="TabBreit" style:family="table">
  <style:table-properties style:width="{BREITE_CM}cm" table:align="left" fo:margin-bottom="0.2cm"/></style:style>
 <style:style style:name="SpZeit" style:family="table-column"><style:table-column-properties style:column-width="1.3cm"/></style:style>
 <style:style style:name="SpIcon" style:family="table-column"><style:table-column-properties style:column-width="0.8cm"/></style:style>
 <style:style style:name="SpText" style:family="table-column"><style:table-column-properties style:column-width="14.6cm"/></style:style>
 <style:style style:name="SpWert" style:family="table-column"><style:table-column-properties style:column-width="0.7cm"/></style:style>
 <style:style style:name="SpLabel" style:family="table-column"><style:table-column-properties style:column-width="3.4cm"/></style:style>
 <style:style style:name="SpWert2" style:family="table-column"><style:table-column-properties style:column-width="14cm"/></style:style>
 <style:style style:name="SpHalb" style:family="table-column"><style:table-column-properties style:column-width="8.7cm"/></style:style>
 <style:style style:name="ZLinie" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" {rahmen} fo:border-top="none" fo:border-left="none" fo:border-right="none"/></style:style>
 <style:style style:name="ZLinks" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" {rahmen} fo:border-right="0.5pt solid #E2E5E9" fo:border-top="none" fo:border-left="none"/></style:style>
 <style:style style:name="ZKopf" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" fo:border-bottom="0.8pt solid #00639C" fo:border-top="none" fo:border-left="none" fo:border-right="none"/></style:style>
 <style:style style:name="ZPhase" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.1cm" fo:background-color="#E6F3FA" fo:border="none"/></style:style>
 <style:style style:name="ZOhne" style:family="table-cell">
  <style:table-cell-properties fo:padding="0cm" fo:border="none"/></style:style>
 <style:style style:name="fr" style:family="graphic">
  <style:graphic-properties style:vertical-pos="middle" style:vertical-rel="text" fo:margin-left="0cm" fo:margin-right="0.1cm"/></style:style>
</office:automatic-styles>'''


def _abschnitt(titel: str, inhalt: str) -> str:
    if not (inhalt or "").strip():
        return ""
    return (f'<text:h text:style-name="Heading_20_2" text:outline-level="2">{escape(titel)}</text:h>'
            f'<text:p text:style-name="PText">{_t(inhalt)}</text:p>')


def erzeuge(db: Session, user: User, b: UbBesuch, mit_fotos: bool = True,
            ordnung: str | None = None) -> bytes:
    pr = aufbereiten(db, user, b, ordnung, mit_fotos)
    dok = _Dok()
    body: list[str] = []

    # Kopf mit Logo rechts
    logo, mime = get_logo_bytes(db)
    logo_frame = ""
    if logo:
        try:
            with PILImage.open(io.BytesIO(logo)) as im:
                w, h = im.size
            endung = "png" if "png" in (mime or "") else "jpg"
            logo_frame = dok.bild(logo, endung, mime or "image/jpeg", 1.4 * w / h, 1.4, schluessel="logo")
        except Exception:
            logo_frame = ""
    body.append('<table:table table:name="Kopf" table:style-name="TabBreit">'
                '<table:table-column table:style-name="SpWert2"/><table:table-column table:style-name="SpLabel"/>'
                "<table:table-row>"
                + _zelle('<text:h text:style-name="Heading_20_1" text:outline-level="1">Protokoll Unterrichtsbesuch</text:h>'
                         f'<text:p text:style-name="PMeta">{escape(pr.schule)}</text:p>', "ZOhne")
                + _zelle(f'<text:p text:style-name="PText">{logo_frame}</text:p>', "ZOhne")
                + "</table:table-row></table:table>")
    body.append('<text:p text:style-name="PUnter"/>')
    body.append(_kopfdaten(pr))
    if pr.vorige:
        body.append(f'<text:p text:style-name="PVorige"><text:span text:style-name="TF_666666">'
                    f'Vereinbarungen aus dem Besuch am {escape(pr.vorige["datum"])}</text:span>'
                    f'<text:line-break/>{_t(pr.vorige["text"])}</text:p>')
        dok.farben.add("#666666")

    body.append(f'<text:h text:style-name="Heading_20_2" text:outline-level="2">'
                f'{escape(UEBERSCHRIFT[pr.ordnung])}</text:h>')
    if pr.legende:
        body.append('<text:p text:style-name="PMeta">' + "   ".join(
            f"{dok.icon(k.icon, k.farbe, 0.4)} {escape(k.name)}" for k in pr.legende) + "</text:p>")

    if not pr.bloecke:
        body.append('<text:p text:style-name="PMeta">Noch keine Einträge erfasst.</text:p>')
    elif pr.ordnung == "zweispaltig":
        body.append(_zweispaltig(dok, pr))
    elif pr.ordnung == "chronologisch":
        body.append(_verlauf_tabelle(dok, pr, pr.bloecke, "Verlauf"))
    else:
        for i, blk in enumerate(pr.bloecke):
            icon = dok.icon(blk.kat.icon, blk.kat.farbe, 0.55) + " " if blk.kat else ""
            hinweis = (f' <text:span text:style-name="TGrau">({escape(blk.hinweis)})</text:span>'
                       if blk.hinweis else "")
            body.append(f'<text:h text:style-name="Heading_20_3" text:outline-level="3">'
                        f'{icon}{escape(blk.titel)}{hinweis}</text:h>')
            if blk.eintraege:
                body.append(_verlauf_tabelle(
                    dok, pr, [Block("eintrag", eintrag=a) for a in blk.eintraege],
                    f"Gruppe{i + 1}", kat=pr.ordnung != "kategorie",
                    zuordnung=pr.ordnung != "kriterium", phase=True))
            else:
                body.append('<text:p text:style-name="PMeta">Dazu wurde nichts notiert.</text:p>')

    body.append(_abschnitt("Reflexionsgespräch", pr.reflexion))
    body.append(_abschnitt("Vereinbarungen", pr.vereinbarungen))

    content = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {_NS}>{_FONTS}'
               f'{_auto_styles(dok)}<office:body><office:text>{"".join(body)}'
               '</office:text></office:body></office:document-content>')
    styles = _styles_xml(f"Unterrichtsbesuch · {pr.anwaerter} · {pr.datum}")
    meta = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-meta {_NS}><office:meta>'
            f'<dc:title>{escape(f"Unterrichtsbesuch {pr.anwaerter} {pr.datum}")}</dc:title>'
            f'<meta:initial-creator>{escape(pr.autor)}</meta:initial-creator>'
            '<meta:generator>DRS-Lehrerwerkzeug</meta:generator>'
            '</office:meta></office:document-meta>')
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
                '<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
                'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
                '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
                + "".join(f'<manifest:file-entry manifest:full-path={quoteattr(p)} manifest:media-type={quoteattr(m)}/>'
                          for p, (_, m) in dok.bilder.items())
                + "</manifest:manifest>")

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        # MUSS zuerst und unkomprimiert stehen
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)
        z.writestr("styles.xml", styles)
        z.writestr("meta.xml", meta)
        z.writestr("META-INF/manifest.xml", manifest)
        for pfad, (daten, _) in dok.bilder.items():
            z.writestr(pfad, daten, compress_type=zipfile.ZIP_STORED)
    return puffer.getvalue()
