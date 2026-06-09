"""Schema-v3-Writer/Parser für Lernsituationen.

Die v3-Vorlage strukturiert eine Lernsituation in:
- `# Unterrichtsinformationen` (Metadaten-Tabelle, App-managed)
- `# Lernsituation` (Hauptszenario inkl. Bild)
- `# Lehrerinformationen` (Kompetenzen, Übergreifende Aspekte, Vorwissen)
- `# Arbeitsblatt N` (1..n, je mit Phasen-Blockquote + Bearbeitungshinweis-
  Callout + Aufgaben/Lösungsskizzen als `## Aufgabe N`/`## Lösungsskizze
  Aufgabe N`)
- `# Leistungsfeststellung` (freier Platzhalter)

Zusätzlich zum sichtbaren Inhalt schreibt der Writer ein verstecktes
YAML-Frontmatter mit Maschinenfeldern (ls_id, slug, schema_version,
content_hash, …) — die Tabelle bleibt für Obsidian/Lehrer sichtbar,
das Frontmatter macht den Parse robuster.

Der Parser ist gutmütig: er akzeptiert die Vorlage 1:1, ignoriert
Reihenfolge der Hauptsektionen und liefert strukturierte Daten für
DB-Sync und Konflikt-Anzeige.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import yaml

from app.models import LearningSituation


SCHEMA_VERSION = 3


# ── Datenklassen ────────────────────────────────────────────────────────


@dataclass
class V3Aufgabe:
    nummer: int
    titel: str
    text_md: str
    loesungsskizze_md: str = ""


@dataclass
class V3Arbeitsblatt:
    position: int  # 1-basiert (entspricht der Nummer im Titel)
    title: str
    phase: str = ""
    bearbeitungshinweis_md: str = ""
    intro_md: str = ""  # alles vor der ersten Aufgabe
    aufgaben: list[V3Aufgabe] = field(default_factory=list)


@dataclass
class V3Document:
    frontmatter: dict
    meta: dict  # Felder aus der Unterrichtsinformationen-Tabelle
    lernsituation_md: str
    lernsituation_bild_path: str
    kompetenzen_md: str
    uebergreifende_aspekte_md: str
    lehrer_vorwissen_md: str
    arbeitsblaetter: list[V3Arbeitsblatt]
    leistungsfeststellung_md: str


# ── Hash + Frontmatter ──────────────────────────────────────────────────


def content_hash(md: str) -> str:
    """sha256 des Inhalts ohne Frontmatter (Frontmatter ändert sich bei
    jedem Schreiben, soll Sync nicht triggern)."""
    _, body = split_frontmatter(md)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def split_frontmatter(md: str) -> tuple[dict, str]:
    if not md.startswith("---\n"):
        return {}, md
    end = md.find("\n---\n", 4)
    if end < 0:
        return {}, md
    fm_text = md[4:end]
    body = md[end + 5:]
    try:
        return yaml.safe_load(fm_text) or {}, body
    except yaml.YAMLError:
        return {}, body


# ── Builder ─────────────────────────────────────────────────────────────


def _meta_table(ls: LearningSituation) -> str:
    rows = [
        ("ls_id", str(ls.id)),
        ("Name Lernsituation", ls.display_name or ""),
        ("Klasse", ls.klassen_key or ""),
        ("Dauer in Stunden", str(ls.dauer_stunden or 0)),
        ("Version", str(ls.version_no or 1)),
    ]
    width_key = max(len(k) for k, _ in rows)
    width_val = max(len(v) for _, v in rows)
    sep_key = "-" * max(3, width_key)
    sep_val = "-" * max(3, width_val)
    lines = [f"| {k.ljust(width_key)} | {v.ljust(width_val)} |" for k, v in rows]
    return (
        f"| {' '.ljust(width_key)} | {' '.ljust(width_val)} |\n"
        f"| {sep_key} | {sep_val} |\n"
        + "\n".join(lines)
    )


def build_template_md_v3(ls: LearningSituation) -> str:
    """Leeres v3-Skeleton für eine neue Lernsituation."""
    ab = V3Arbeitsblatt(position=1, title="Arbeitsblatt 1",
                        phase="Arbeitsplanung",
                        bearbeitungshinweis_md="Hinweis zur Bearbeitung (Optional)",
                        aufgaben=[
                            V3Aufgabe(nummer=1, titel="", text_md="Aufgabentext",
                                      loesungsskizze_md="Lösungsskizze"),
                        ])
    doc = V3Document(
        frontmatter={},
        meta={},
        lernsituation_md="Hier steht die Situation",
        lernsituation_bild_path="",
        kompetenzen_md="- Kompetenz 1",
        uebergreifende_aspekte_md="- Aspekt 1",
        lehrer_vorwissen_md="- Vorwissen 1",
        arbeitsblaetter=[ab],
        leistungsfeststellung_md="",
    )
    return build_markdown_v3(ls, doc)


def build_markdown_v3(ls: LearningSituation, doc: V3Document) -> str:
    """Vollständiger v3-MD-Aufbau aus DB-Inhalten."""
    fm = {
        "ls_id": ls.id,
        "slug": ls.slug,
        "schema_version": SCHEMA_VERSION,
        "display_name": ls.display_name,
        "klasse": ls.klassen_key,
        "lernfeld": ls.lernfeld,
        "created": ls.created_at.date().isoformat() if ls.created_at else "",
        "updated": datetime.utcnow().date().isoformat(),
    }

    buf = io.StringIO()
    buf.write("---\n")
    buf.write(yaml.safe_dump(fm, allow_unicode=True, sort_keys=False))
    buf.write("---\n\n")

    buf.write("\n# Unterrichtsinformationen\n\n")
    buf.write(_meta_table(ls))
    buf.write("\n\n# Lernsituation\n\n")
    # Bild und Text werden getrennt verwaltet: Bild-Headline + ![] aus
    # dem Pfad-Feld, danach der reine Prosa-Text aus lernsituation_md.
    if doc.lernsituation_bild_path:
        buf.write("## Bild\n\n")
        buf.write(f"![]({doc.lernsituation_bild_path})\n\n")
    if doc.lernsituation_md and doc.lernsituation_md.strip():
        buf.write(doc.lernsituation_md.rstrip() + "\n\n")
    elif not doc.lernsituation_bild_path:
        buf.write("\n")

    buf.write("# Lehrerinformationen\n\n")
    buf.write("## Kompetenzen\n\n")
    buf.write((doc.kompetenzen_md or "").rstrip() + "\n\n")
    buf.write("## Übergreifende Aspekte\n\n")
    buf.write((doc.uebergreifende_aspekte_md or "").rstrip() + "\n\n")
    buf.write("## Vorwissen\n\n")
    buf.write((doc.lehrer_vorwissen_md or "").rstrip() + "\n\n")

    for ab in doc.arbeitsblaetter:
        title = ab.title or f"Arbeitsblatt {ab.position}"
        buf.write(f"# {title}\n\n")
        if ab.phase:
            buf.write(f"> {ab.phase}\n\n")
        if ab.bearbeitungshinweis_md:
            hint = ab.bearbeitungshinweis_md.strip()
            # Mehrzeilig: jede Zeile mit '> ' prefixen
            hint_lines = hint.splitlines() or [""]
            buf.write(">[!NOTE] Bearbeitungshinweis\n")
            for line in hint_lines:
                buf.write(f">{line}\n")
            buf.write("\n")
        if ab.intro_md:
            buf.write(ab.intro_md.rstrip() + "\n\n")
        for a in ab.aufgaben:
            buf.write(f"## Aufgabe {a.nummer}\n\n")
            buf.write((a.text_md or "").rstrip() + "\n\n")
            buf.write(f"## Lösungsskizze Aufgabe {a.nummer}\n\n")
            buf.write((a.loesungsskizze_md or "").rstrip() + "\n\n")

    buf.write("# Leistungsfeststellung\n\n")
    buf.write((doc.leistungsfeststellung_md or "").rstrip() + "\n")

    return buf.getvalue()


# ── Parser ──────────────────────────────────────────────────────────────


_H1_RE = re.compile(r"^# (?P<title>.+?)\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^## (?P<title>.+?)\s*$", re.MULTILINE)
_AUFG_RE = re.compile(r"^Aufgabe\s+(\d+)\b\s*:?\s*(.*)$", re.IGNORECASE)
_LOSG_RE = re.compile(r"^Lösungsskizze\s+Aufgabe\s+(\d+)\b\s*:?\s*(.*)$",
                      re.IGNORECASE)
_BILD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_CALLOUT_RE = re.compile(
    r"^>\s*\[!(?P<kind>[A-Z]+)\][^\n]*\n((?:^>.*(?:\n|$))*)",
    re.MULTILINE,
)
_QUOTE_LINE_RE = re.compile(r"^>(?!\s*\[)(.*)$", re.MULTILINE)


def _split_top_sections(md: str) -> list[tuple[str, str]]:
    """Zerlegt das MD in [(h1_titel, body), …] in Reihenfolge."""
    sections: list[tuple[str, str]] = []
    matches = list(_H1_RE.finditer(md))
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        sections.append((title, md[start:end].strip("\n")))
    return sections


def _split_h2_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return []
    # Alles vor dem ersten H2 wird verworfen — Aufrufer kümmert sich selbst
    # um den Intro-Text.
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((title, body[start:end].strip("\n")))
    return sections


def _intro_before_first_h2(body: str) -> str:
    m = _H2_RE.search(body)
    if not m:
        return body.strip("\n")
    return body[: m.start()].strip("\n")


def _parse_meta_table(body: str) -> dict[str, str]:
    """Liest die Unterrichtsinformationen-Tabelle (key|value)."""
    out: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(set(c) <= set("- :") for c in cells):  # Tabellen-Separator
            continue
        if not cells[0] or not any(cells[1:]):
            continue
        out[cells[0]] = cells[1]
    return out


def _parse_callout(body: str, kind: str) -> tuple[str, str]:
    """Findet den ersten >[!KIND]-Callout und liefert (inhalt, restlicher_body)."""
    for m in _CALLOUT_RE.finditer(body):
        if m.group("kind").upper() != kind.upper():
            continue
        block = m.group(2) or ""
        inner_lines = []
        for raw in block.splitlines():
            if raw.startswith(">"):
                inner_lines.append(raw[1:].lstrip())
        rest = body[: m.start()] + body[m.end():]
        return ("\n".join(inner_lines).strip("\n"), rest)
    return ("", body)


def _parse_phase_quote(body: str) -> tuple[str, str]:
    """Erste Blockquote-Zeile (kein Callout) als Phase nutzen."""
    m = _QUOTE_LINE_RE.search(body)
    if not m:
        return ("", body)
    phase = m.group(1).strip()
    rest = body[: m.start()] + body[m.end():]
    return (phase, rest.lstrip("\n"))


def _parse_arbeitsblatt(title: str, position: int, body: str) -> V3Arbeitsblatt:
    phase, after_phase = _parse_phase_quote(body)
    hinweis, after_hinweis = _parse_callout(after_phase, "NOTE")
    intro = _intro_before_first_h2(after_hinweis)

    aufgaben_map: dict[int, V3Aufgabe] = {}
    for h2_title, content in _split_h2_sections(after_hinweis):
        m = _LOSG_RE.match(h2_title)
        if m:
            num = int(m.group(1))
            a = aufgaben_map.setdefault(num, V3Aufgabe(nummer=num, titel="", text_md=""))
            a.loesungsskizze_md = content.strip("\n")
            continue
        m = _AUFG_RE.match(h2_title)
        if m:
            num = int(m.group(1))
            titel = m.group(2).strip()
            a = aufgaben_map.setdefault(num, V3Aufgabe(nummer=num, titel="", text_md=""))
            a.titel = titel
            a.text_md = content.strip("\n")
            continue

    return V3Arbeitsblatt(
        position=position,
        title=title.strip(),
        phase=phase,
        bearbeitungshinweis_md=hinweis,
        intro_md=intro,
        aufgaben=[aufgaben_map[k] for k in sorted(aufgaben_map.keys())],
    )


def _parse_lehrerinformationen(body: str) -> tuple[str, str, str]:
    kompetenzen = uebergreifend = vorwissen = ""
    for h2_title, content in _split_h2_sections(body):
        t = h2_title.strip().lower()
        if t.startswith("kompetenz"):
            kompetenzen = content.strip("\n")
        elif "übergreifend" in t or "uebergreifend" in t:
            uebergreifend = content.strip("\n")
        elif "vorwissen" in t:
            vorwissen = content.strip("\n")
    return kompetenzen, uebergreifend, vorwissen


def _parse_lernsituation(body: str) -> tuple[str, str]:
    """Bild-Pfad extra extrahieren UND aus dem Text-Body entfernen.

    Der Bild-Tag und die optionale `## Bild`-Headline werden gestrippt,
    damit `lernsituation_md` nur den Prosa-Text enthält. Beim Rebuild
    wird die Bild-Sektion aus `lernsituation_bild_path` neu erzeugt."""
    bild = ""
    m = _BILD_RE.search(body)
    if m:
        bild = m.group(1).strip()
    cleaned = _BILD_RE.sub("", body)
    # Optionale '## Bild'-Headline entfernen, wenn sie jetzt leer ist
    cleaned = re.sub(r"(?m)^##\s*Bild\s*$\n?", "", cleaned)
    # Mehrfache Leerzeilen reduzieren
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n")
    return bild, cleaned


def parse_v3(md: str) -> V3Document:
    """Strukturiertes Parsing der v3-MD. Robust gegen Reihenfolge der
    Hauptsektionen und gegen fehlende optionale Felder."""
    fm, body = split_frontmatter(md)
    sections = _split_top_sections(body)

    meta_dict: dict[str, str] = {}
    lernsituation_md = ""
    bild_path = ""
    kompetenzen = uebergreifend = vorwissen = ""
    arbeitsblaetter: list[V3Arbeitsblatt] = []
    leistungsfeststellung_md = ""

    ab_pos = 0
    for title, content in sections:
        tnorm = title.strip().lower()
        if tnorm.startswith("unterrichtsinfo"):
            meta_dict = _parse_meta_table(content)
        elif tnorm == "lernsituation":
            bild_path, lernsituation_md = _parse_lernsituation(content)
        elif tnorm.startswith("lehrerinfo"):
            kompetenzen, uebergreifend, vorwissen = _parse_lehrerinformationen(content)
        elif tnorm.startswith("arbeitsblatt"):
            ab_pos += 1
            arbeitsblaetter.append(_parse_arbeitsblatt(title, ab_pos, content))
        elif tnorm.startswith("leistungsfest"):
            leistungsfeststellung_md = content.strip()

    return V3Document(
        frontmatter=fm,
        meta=meta_dict,
        lernsituation_md=lernsituation_md,
        lernsituation_bild_path=bild_path,
        kompetenzen_md=kompetenzen,
        uebergreifende_aspekte_md=uebergreifend,
        lehrer_vorwissen_md=vorwissen,
        arbeitsblaetter=arbeitsblaetter,
        leistungsfeststellung_md=leistungsfeststellung_md,
    )


def detect_schema_version(md: str) -> int:
    """v3 erkennen entweder am Frontmatter-Feld oder an typischen H1-Sektionen."""
    fm, _ = split_frontmatter(md)
    try:
        sv = int(fm.get("schema_version") or 0)
        if sv == 3:
            return 3
        if sv == 2:
            return 2
    except (TypeError, ValueError):
        pass
    # Heuristik: # Unterrichtsinformationen + # Lernsituation + # Arbeitsblatt …
    h1_titles = [m.group("title").strip().lower()
                 for m in _H1_RE.finditer(md)]
    if any(t.startswith("unterrichtsinfo") for t in h1_titles) and any(
        t.startswith("arbeitsblatt") for t in h1_titles
    ):
        return 3
    # Fallback: alte Heuristik (v2 hat ## 1. Lernsituationsbeschreibung)
    if "## 1. Lernsituationsbeschreibung" in md or "## 2. Phasen der vollständigen Handlung" in md:
        return 2
    return 1
