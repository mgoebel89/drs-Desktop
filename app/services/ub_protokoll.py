"""Protokoll eines Unterrichtsbesuchs — formatunabhängig aufbereitet.

Hier fällt EINMAL die Entscheidung, was in welcher Ordnung wo steht. PDF
(`ub_protokoll_pdf.py`) und ODT (`ub_protokoll_odt.py`) zeichnen nur noch,
was `aufbereiten()` liefert. So können die beiden Formate nicht
auseinanderlaufen.

Die vier Ordnungen:
- **chronologisch**: Verlauf mit Phasen als Zwischenbänder.
- **kategorie**: je Kategorie ein Block (in Einstellungs-Reihenfolge).
- **kriterium**: je Beratungsschwerpunkt ein Block — die vom Anwärter
  gewählten zuerst, dann weitere benutzte, am Ende „ohne Zuordnung".
- **zweispaltig**: links Einträge der Kategorien mit Spalte „verlauf",
  rechts die mit Spalte „kommentar". Ein Kommentar steht neben dem Eintrag,
  auf den er sich bezieht (`bezug_id`); ohne Bezug neben dem zeitlich
  vorigen Verlaufs-Eintrag derselben Phase. Gibt es keinen, bekommt er eine
  eigene Zeile mit leerer linker Seite.

Außerdem hier: der Pfad-Parser für die Piktogramme, den PDF und ODT teilen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.branding import get_school_name
from app.models import UbBesuch, User
from app.services import file_store
from app.services import unterrichtsbesuche as ub


# ── Datenklassen ─────────────────────────────────────────────────────────

@dataclass
class Kat:
    name: str
    icon: str
    farbe: str


@dataclass
class EintragAnsicht:
    id: int
    zeit: str
    text: str
    kat: Kat | None
    zuordnung: str              # Name des Beratungsschwerpunkts oder ""
    wertung: dict | None        # {label, icon, farbe}
    phase: str                  # Name der Phase, in der der Eintrag steht
    foto: Path | None
    bezug: str                  # „zu 08:14 · Arbeitsauftrag …" oder ""


@dataclass
class Block:
    typ: str                    # phase | eintrag | gruppe | zeile2
    zeit: str = ""
    titel: str = ""
    kat: Kat | None = None      # Piktogramm einer Kategorie-Gruppe
    hinweis: str = ""           # z. B. „vom Anwärter gewählt"
    eintrag: EintragAnsicht | None = None
    eintraege: list = field(default_factory=list)
    links: EintragAnsicht | None = None
    rechts: list = field(default_factory=list)


@dataclass
class Protokoll:
    schule: str
    anwaerter: str
    datum: str                  # TT.MM.JJJJ
    kopf: list                  # [(Label, Text)]
    schwerpunkte: list          # [Name]
    vorige: dict | None         # {datum, text}
    legende: list               # [Kat]
    ordnung: str
    ordnung_label: str
    bloecke: list
    reflexion: str
    vereinbarungen: str
    autor: str
    mit_fotos: bool


def fmt_datum(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if len(iso or "") == 10 else (iso or "")


def _kurz(text: str, n: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ── Aufbereiten ──────────────────────────────────────────────────────────

def aufbereiten(db: Session, user: User, b: UbBesuch, ordnung: str | None = None,
                mit_fotos: bool = True) -> Protokoll:
    if ordnung not in ub.ORDNUNGEN:
        ordnung = ub.einstellung(db, user).standard_ordnung
    if ordnung not in ub.ORDNUNGEN:
        ordnung = "chronologisch"

    kategorien = ub.liste(db, user, "kategorien")
    kat_map = {k.id: k for k in kategorien}
    phasen = {p.id: p for p in ub.liste(db, user, "phasen")}
    katalog = ub.liste(db, user, "kriterien")
    krit_map = {k.id: k for k in katalog}
    gewaehlt = ub.schwerpunkte(db, b.id)
    gewaehlt_ids = [k.id for k in gewaehlt]

    alle = ub.eintraege(db, b.id)
    nach_id = {e.id: e for e in alle}

    def ansicht(e, phase_name: str) -> EintragAnsicht:
        k = kat_map.get(e.kategorie_id)
        foto = None
        if mit_fotos and e.file_uuid:
            foto = file_store.resolve(e.file_uuid, e.filename)
        bez = ""
        if e.bezug_id and e.bezug_id in nach_id:
            r = nach_id[e.bezug_id]
            bez = f"zu {r.zeit} · {_kurz(r.text, 50)}" if r.zeit else f"zu {_kurz(r.text, 50)}"
        w = ub.WERTUNGEN.get(e.wertung)
        return EintragAnsicht(
            id=e.id, zeit=e.zeit or "", text=e.text or "",
            kat=Kat(k.name, k.icon, k.farbe) if k else None,
            zuordnung=krit_map[e.kriterium_id].name if e.kriterium_id in krit_map else "",
            wertung=w, phase=phase_name, foto=foto, bezug=bez)

    # chronologische Rohfolge mit abgeleiteter Phase
    folge: list[tuple] = []          # ("phase", e, name) | ("eintrag", ansicht, e)
    for e, pid in ub.mit_phasen(alle):
        name = phasen[pid].name if pid in phasen else ""
        if e.art == "phase":
            folge.append(("phase", e, name))
        else:
            folge.append(("eintrag", ansicht(e, name), e))
    eintraege = [x for x in folge if x[0] == "eintrag"]

    bloecke: list[Block] = []
    if ordnung == "chronologisch":
        for typ, a, extra in folge:
            if typ == "phase":
                bloecke.append(Block("phase", zeit=a.zeit or "", titel=extra or "Phase"))
            else:
                bloecke.append(Block("eintrag", eintrag=a))

    elif ordnung == "kategorie":
        for k in kategorien:
            drin = [a for _, a, e in eintraege if e.kategorie_id == k.id]
            if drin:
                bloecke.append(Block("gruppe", titel=k.name, kat=Kat(k.name, k.icon, k.farbe),
                                     eintraege=drin))
        ohne = [a for _, a, e in eintraege if e.kategorie_id not in kat_map]
        if ohne:
            bloecke.append(Block("gruppe", titel="Ohne Kategorie", eintraege=ohne))

    elif ordnung == "kriterium":
        benutzt = {e.kriterium_id for _, _, e in eintraege if e.kriterium_id}
        reihenfolge = gewaehlt_ids + [k.id for k in katalog
                                      if k.id in benutzt and k.id not in gewaehlt_ids]
        for kid in reihenfolge:
            k = krit_map.get(kid)
            drin = [a for _, a, e in eintraege if e.kriterium_id == kid]
            if not k:
                continue
            bloecke.append(Block(
                "gruppe", titel=k.name, eintraege=drin,
                hinweis="Schwerpunkt des Anwärters" if kid in gewaehlt_ids else ""))
        ohne = [a for _, a, e in eintraege if not e.kriterium_id or e.kriterium_id not in krit_map]
        if ohne:
            bloecke.append(Block("gruppe", titel="Ohne Zuordnung", eintraege=ohne))

    else:  # zweispaltig
        zeile_von: dict[int, Block] = {}
        letzte: Block | None = None
        for typ, a, extra in folge:
            if typ == "phase":
                bloecke.append(Block("phase", zeit=a.zeit or "", titel=extra or "Phase"))
                letzte = None          # Kommentare wandern nie über eine Phasengrenze
                continue
            e = extra
            k = kat_map.get(e.kategorie_id)
            if not k or k.spalte != "kommentar":
                zeile = Block("zeile2", links=a)
                bloecke.append(zeile)
                zeile_von[e.id] = zeile
                letzte = zeile
                continue
            if e.bezug_id and e.bezug_id in zeile_von:
                a.bezug = ""           # steht ja direkt daneben
                zeile_von[e.bezug_id].rechts.append(a)
            elif letzte is not None:
                letzte.rechts.append(a)
            else:
                letzte = Block("zeile2", links=None, rechts=[a])
                bloecke.append(letzte)

    # Kopfdaten
    anw = b.anwaerter
    zeit = fmt_datum(b.datum)
    if b.beginn:
        zeit += f", {b.beginn}" + (f" – {b.ende}" if b.ende else "") + " Uhr"
    kopf = [
        ("Anwärter/in", (anw.name if anw else "") + (f" · {anw.faecher}" if anw and anw.faecher else "")),
        ("Datum", zeit),
        ("Klasse / Raum", " / ".join(x for x in (b.klasse, b.raum) if x) or "—"),
        ("Thema", b.thema or "—"),
    ]
    if b.lernziele:
        kopf.append(("Lernziele", b.lernziele))

    # Legende: nur, was im Protokoll vorkommt
    legende: list[Kat] = []
    benutzte_kat = {e.kategorie_id for _, _, e in eintraege}
    for k in kategorien:
        if k.id in benutzte_kat:
            legende.append(Kat(k.name, k.icon, k.farbe))
    benutzte_w = {e.wertung for _, _, e in eintraege}
    for key in sorted(ub.WERTUNGEN, key=lambda x: ub.WERTUNGEN[x]["pos"]):
        if key in benutzte_w:
            w = ub.WERTUNGEN[key]
            legende.append(Kat(w["label"], w["icon"], w["farbe"]))

    vor = ub.vorheriger_besuch(db, b)
    return Protokoll(
        schule=get_school_name(db),
        anwaerter=anw.name if anw else "",
        datum=fmt_datum(b.datum),
        kopf=kopf,
        schwerpunkte=[k.name for k in gewaehlt],
        vorige=({"datum": fmt_datum(vor.datum), "text": vor.vereinbarungen}
                if vor and (vor.vereinbarungen or "").strip() else None),
        legende=legende,
        ordnung=ordnung,
        ordnung_label=ub.ORDNUNGEN[ordnung],
        bloecke=bloecke,
        reflexion=b.reflexion or "",
        vereinbarungen=b.vereinbarungen or "",
        autor=user.full_name or user.username,
        mit_fotos=mit_fotos,
    )


# ── Piktogramm-Pfade (geteilt von PDF und ODT) ───────────────────────────

_TOKEN = re.compile(r"[MLHVCQZ]|-?\d*\.?\d+")


def pfad_befehle(d: str) -> list[tuple]:
    """Zerlegt einen SVG-Pfad (nur absolute M/L/H/V/C/Q/Z) in
    ("M", x, y) · ("L", x, y) · ("C", x1, y1, x2, y2, x, y) · ("Z",).
    H/V werden zu L, Q zu C — damit müssen die Zeichner nur vier Befehle kennen."""
    tok = _TOKEN.findall(d)
    out: list[tuple] = []
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
                out.append(("Z",))
                x, y = sx, sy
                continue
        if cmd == "M":
            x, y = zahl(), zahl()
            sx, sy = x, y
            out.append(("M", x, y))
            cmd = "L"   # weitere Koordinaten nach M sind Linien
        elif cmd == "L":
            x, y = zahl(), zahl()
            out.append(("L", x, y))
        elif cmd == "H":
            x = zahl()
            out.append(("L", x, y))
        elif cmd == "V":
            y = zahl()
            out.append(("L", x, y))
        elif cmd == "C":
            x1, y1, x2, y2, x, y = (zahl() for _ in range(6))
            out.append(("C", x1, y1, x2, y2, x, y))
        elif cmd == "Q":
            qx, qy, nx, ny = (zahl() for _ in range(4))
            out.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                        nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny), nx, ny))
            x, y = nx, ny
        else:
            i += 1   # unbekannt — überspringen statt hängen
    return out
