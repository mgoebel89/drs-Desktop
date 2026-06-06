"""Obsidian-Vault-Pflege: pro Lernsituation eine .md-Datei.

Schreibt YAML-Frontmatter + strukturierte Sektionen in den Vault-Unterordner
des SMB-Shares. Liest existierende Notizen für die App-Anzeige.

Schema-Version 1 (siehe docs/lerninhalt-md-schema.md):
- Inhalts-MD pflegt der Lehrer in Obsidian Desktop (Pflicht: Lernziele,
  Sachanalyse, Inhalt).
- Wizard hängt erzeugte Materialien als WIZARD-BLOCK an die Output-Sektion.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

import yaml

from app.models import LearningSituation, User
from app.services import smb_client


SCHEMA_VERSION = 2  # neuer Default für neue Vorlagen
OUTPUT_SECTION_HEADER = "## Erzeugte Materialien"
WIZARD_BLOCK_PREFIX = "<!-- WIZARD-BLOCK"

# Schema v2 — Pflichtsektionen (## und ###)
V2_TOP_SECTIONS = {
    "lernsituationsbeschreibung": ["1. lernsituationsbeschreibung",
                                   "lernsituationsbeschreibung"],
    "phasen": ["2. phasen der vollständigen handlung",
               "phasen der vollständigen handlung",
               "phasen der vollstaendigen handlung"],
    "anmerkungen": ["3. anmerkungen", "anmerkungen"],
}
V2_BESCHREIBUNG_SUB = {
    "szenario": ["szenario / auftrag", "szenario", "auftrag"],
    "lernziele": ["lernziele"],
    "vorwissen": ["vorwissen / anknüpfung", "vorwissen / anknuepfung",
                  "vorwissen", "anknüpfung", "anknuepfung"],
}
PHASEN_NAMEN = ["informieren", "planen", "entscheiden",
                "ausführen", "ausfuehren", "kontrollieren", "bewerten"]

# Pflicht- und optionale Sektionen. Schlüssel = interner Name,
# Wert = Liste akzeptierter Header-Texte (case-insensitive).
PFLICHT_SEKTIONEN = {
    "lernziele": ["lernziele"],
    "sachanalyse": ["sachanalyse"],
    "inhalt": ["inhalt"],
}
OPTIONAL_SEKTIONEN = {
    "vorwissen": ["vorwissen", "vorwissen / anknüpfung", "vorwissen / anknuepfung",
                  "anknüpfung", "anknuepfung"],
    "didaktik": ["didaktischer schwerpunkt", "didaktik"],
    "aufgabenideen": ["aufgabenideen", "aufgaben"],
    "materialhinweise": ["materialhinweise", "material"],
    "quellen": ["quellen"],
}


def note_filename(ls: LearningSituation) -> str:
    return f"{ls.smb_folder_name}.md"


def build_markdown(
    *,
    ls: LearningSituation,
    theme: str = "",
    lernziele: str = "",
    fobizz_output: str = "",
    material_files: list[str] | None = None,
    verknuepfte_stunden: list[str] | None = None,
) -> str:
    """Erzeugt den vollständigen Markdown-Text mit YAML-Frontmatter."""
    fm = {
        "ls_id": ls.id,
        "slug": ls.slug,
        "display_name": ls.display_name,
        "klasse": ls.klassen_key,
        "lernfeld": ls.lernfeld,
        "created": ls.created_at.date().isoformat() if ls.created_at else "",
        "updated": datetime.utcnow().date().isoformat(),
        "smb_folder": ls.smb_folder_name,
    }
    buf = io.StringIO()
    buf.write("---\n")
    buf.write(yaml.safe_dump(fm, allow_unicode=True, sort_keys=False))
    buf.write("---\n\n")
    buf.write(f"# {ls.display_name}\n\n")

    buf.write("## Theme / Lernziele\n\n")
    if theme:
        buf.write(f"**Theme:** {theme}\n\n")
    if lernziele:
        buf.write(lernziele.rstrip() + "\n\n")
    if not (theme or lernziele):
        buf.write("_Noch nichts erfasst._\n\n")

    buf.write("## Inhalte (aus Fobizz)\n\n")
    buf.write(fobizz_output.rstrip() + "\n\n" if fobizz_output else "_Noch nichts erfasst._\n\n")

    buf.write("## Material\n\n")
    if material_files:
        for fname in material_files:
            # Relativer Link auf den Material-Ordner im selben Share.
            buf.write(f"- [[../{ls.smb_folder_name}/{fname}|{fname}]]\n")
        buf.write("\n")
    else:
        buf.write("_Keine Dateien._\n\n")

    buf.write("## Verknüpfte Stunden\n\n")
    if verknuepfte_stunden:
        for s in verknuepfte_stunden:
            buf.write(f"- {s}\n")
    else:
        buf.write("_Noch keine._\n")

    return buf.getvalue()


def write_note(user: User, ls: LearningSituation, markdown: str) -> str:
    """Schreibt die Notiz in die Vault. Gibt relativen Pfad zurück."""
    cfg = smb_client.load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    fname = note_filename(ls)
    subpath = smb_client.vault_subpath(cfg, fname)
    # Vault-Ordner sicherstellen
    smb_client.ensure_folder(user, cfg.vault_subpath.strip("/"))
    smb_client.write_file(user, subpath, markdown.encode("utf-8"))
    return subpath


def read_note(user: User, ls: LearningSituation) -> str:
    cfg = smb_client.load_config(user)
    if not cfg:
        return ""
    subpath = smb_client.vault_subpath(cfg, note_filename(ls))
    try:
        return smb_client.read_file(user, subpath).decode("utf-8")
    except Exception:
        return ""


def split_frontmatter(md: str) -> tuple[dict, str]:
    """Trennt YAML-Frontmatter vom Body."""
    if not md.startswith("---\n"):
        return {}, md
    end = md.find("\n---\n", 4)
    if end < 0:
        return {}, md
    fm_raw = md[4:end]
    body = md[end + 5:]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except Exception:
        fm = {}
    return fm, body


# ── Schema v1: Inhalts-MD ─────────────────────────────────────────────────

def _normalize_header(text: str) -> str:
    """Header-Text für Vergleich normalisieren."""
    return text.strip().lower().replace("ä", "ae").replace("ö", "oe") \
        .replace("ü", "ue").replace("ß", "ss")


def _section_match(header_text: str, accepted: list[str]) -> bool:
    norm = _normalize_header(header_text)
    return any(_normalize_header(a) == norm for a in accepted)


def parse_content_sections(md: str) -> dict[str, str]:
    """Findet alle `## …`-Sektionen im Body und liefert ein Dict
    {schluessel: body_text}. Schlüssel sind die internen Namen aus
    PFLICHT_SEKTIONEN + OPTIONAL_SEKTIONEN. Unbekannte Sektionen werden
    übersprungen. Body ist roh (inkl. Subheader)."""
    _, body = split_frontmatter(md)
    result: dict[str, str] = {}
    lines = body.splitlines()

    # Sektionen finden: Liste (start_idx, header_text)
    sections: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            sections.append((i, m.group(1)))
    sections.append((len(lines), ""))  # Sentinel

    catalog = {**PFLICHT_SEKTIONEN, **OPTIONAL_SEKTIONEN}

    for idx in range(len(sections) - 1):
        start, header = sections[idx]
        end, _ = sections[idx + 1]
        if not header:
            continue
        # Erzeugte-Materialien-Block überspringen
        if _normalize_header(header) == _normalize_header("Erzeugte Materialien"):
            continue
        # Welches interne Feld?
        for key, accepted in catalog.items():
            if _section_match(header, accepted):
                content = "\n".join(lines[start + 1:end]).strip()
                result[key] = content
                break
    return result


def validate_pflicht(md: str) -> dict[str, bool]:
    """Liefert {key: vorhanden_und_nicht_leer} für alle Pflichtsektionen.
    Eine Sektion gilt als leer, wenn ihr Body nur aus Leerzeilen oder
    HTML-Kommentaren besteht."""
    sections = parse_content_sections(md)
    result: dict[str, bool] = {}
    for key in PFLICHT_SEKTIONEN:
        body = sections.get(key, "")
        # HTML-Kommentare entfernen
        stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
        result[key] = bool(stripped)
    return result


def missing_pflicht(md: str) -> list[str]:
    """Pflichtsektionen, die fehlen oder leer sind (interne Schlüssel)."""
    val = validate_pflicht(md)
    return [k for k, ok in val.items() if not ok]


def build_template_md(ls: LearningSituation) -> str:
    """Erzeugt das Schema-v1-Skeleton für eine neue Inhalts-MD.
    Frontmatter aus LS-Werten, leere Sektionen mit Hilfekommentaren."""
    fm = {
        "ls_id": ls.id,
        "slug": ls.slug,
        "display_name": ls.display_name,
        "klasse": ls.klassen_key or "",
        "lernfeld": ls.lernfeld or "",
        "created": (ls.created_at.date().isoformat()
                    if ls.created_at else datetime.utcnow().date().isoformat()),
        "updated": datetime.utcnow().date().isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    buf = io.StringIO()
    buf.write("---\n")
    buf.write(yaml.safe_dump(fm, allow_unicode=True, sort_keys=False))
    buf.write("---\n\n")
    buf.write(f"# {ls.display_name}\n\n")

    buf.write("## Lernziele\n")
    buf.write("<!-- Pflicht: operationalisierte Lernziele, eines pro Zeile -->\n")
    buf.write("- Die SuS können …\n\n")

    buf.write("## Sachanalyse\n")
    buf.write("<!-- Pflicht: fachlicher Kern, Begriffe, Zusammenhänge, typische Fehlvorstellungen -->\n\n")

    buf.write("## Inhalt\n")
    buf.write("<!-- Pflicht: was konkret unterrichtet wird, Stoffabfolge, Kernbeispiele -->\n\n")

    buf.write("## Vorwissen / Anknüpfung\n")
    buf.write("<!-- optional -->\n\n")

    buf.write("## Didaktischer Schwerpunkt\n")
    buf.write("<!-- optional: Methodenwahl, Phasierung, Sozialformen -->\n\n")

    buf.write("## Aufgabenideen\n")
    buf.write("<!-- optional: Stichpunkte oder ausformulierte Aufgaben-Drafts -->\n\n")

    buf.write("## Materialhinweise\n")
    buf.write("<!-- optional: Realbauteile, Tools, Software, Datenblätter -->\n\n")

    buf.write("## Quellen\n")
    buf.write("<!-- optional: Lehrwerke, DIN-Normen, Datenblätter, Lehrplan-Bezug -->\n\n")

    buf.write("---\n\n")
    buf.write(f"{OUTPUT_SECTION_HEADER}\n\n")
    buf.write("*Vom Wizard automatisch befüllt — pro Generierung ein Block.*\n")
    return buf.getvalue()


def ensure_content_md(user: User, ls: LearningSituation) -> tuple[bool, str]:
    """Stellt sicher, dass die Inhalts-MD im Vault existiert.
    Liefert (was_created, path)."""
    cfg = smb_client.load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    existing = read_note(user, ls)
    if existing.strip():
        return False, smb_client.vault_subpath(cfg, note_filename(ls))
    md = build_template_md(ls)
    path = write_note(user, ls, md)
    return True, path


def append_output_block(
    user: User, ls: LearningSituation,
    material_type_label: str, output_md: str,
) -> str:
    """Liest die aktuelle Inhalts-MD, hängt einen WIZARD-BLOCK an die
    Output-Sektion (legt sie an, wenn fehlt) und schreibt zurück."""
    md = read_note(user, ls)
    if not md.strip():
        # Keine MD da? → Vorlage anlegen, dann Block anhängen.
        md = build_template_md(ls)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n\n<!-- WIZARD-BLOCK · {ts} · {material_type_label} -->\n{output_md.rstrip()}\n"

    if OUTPUT_SECTION_HEADER in md:
        # An's Ende anhängen — die Output-Sektion ist immer der letzte Abschnitt.
        new_md = md.rstrip() + block + "\n"
    else:
        # Sektion ergänzen
        new_md = md.rstrip() + f"\n\n---\n\n{OUTPUT_SECTION_HEADER}\n\n" \
                 + "*Vom Wizard automatisch befüllt — pro Generierung ein Block.*\n" \
                 + block + "\n"

    write_note(user, ls, new_md)
    return md


# ── Schema v2: Phasen der vollständigen Handlung ─────────────────────────

def detect_schema_version(md: str) -> int:
    """Liefert 1 oder 2. Liest Frontmatter, sonst Heuristik."""
    fm, body = split_frontmatter(md)
    v = fm.get("schema_version") if isinstance(fm, dict) else None
    if isinstance(v, int) and v in (1, 2):
        return v
    # Heuristik: v2-Marker im Body suchen
    for line in body.splitlines():
        if line.startswith("## "):
            norm = _normalize_header(line[3:])
            if any(_normalize_header(s) == norm for s in V2_TOP_SECTIONS["phasen"]):
                return 2
    return 1


def _parse_h2_sections(md: str) -> dict[str, tuple[int, int, str]]:
    """Findet ## Sektionen. Liefert {key: (start_line, end_line, header)}.
    end_line ist exklusiv (Anfang der nächsten Sektion oder EOF).
    Erkennt nur Sektionen aus V2_TOP_SECTIONS (oder Output-Sektion ignoriert)."""
    _, body = split_frontmatter(md)
    lines = body.splitlines()
    positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            positions.append((i, m.group(1)))
    positions.append((len(lines), ""))

    catalog = V2_TOP_SECTIONS
    result: dict[str, tuple[int, int, str]] = {}
    for i in range(len(positions) - 1):
        start, header = positions[i]
        end, _ = positions[i + 1]
        if not header:
            continue
        for key, accepted in catalog.items():
            if any(_normalize_header(a) == _normalize_header(header) for a in accepted):
                result[key] = (start, end, header)
                break
    # Body als Strings speichern wir nicht hier — wir liefern Indizes.
    # Helfer-Caller braucht das body-Array. Geben es global ungespeichert raus:
    result["__lines__"] = lines  # type: ignore
    return result


def parse_content_sections_v2(md: str) -> dict[str, str]:
    """Liefert {key: text} für die Top-Sektionen und die Untersektionen
    der Lernsituationsbeschreibung."""
    sections = _parse_h2_sections(md)
    lines: list[str] = sections.pop("__lines__")  # type: ignore
    result: dict[str, str] = {}

    for key, (start, end, _) in sections.items():
        result[key] = "\n".join(lines[start + 1:end]).strip()

    # Lernsituationsbeschreibung in Untersektionen auflösen
    if "lernsituationsbeschreibung" in sections:
        s, e, _ = sections["lernsituationsbeschreibung"]
        sub_positions: list[tuple[int, str]] = []
        for i in range(s + 1, e):
            m = re.match(r"^###\s+(.+?)\s*$", lines[i])
            if m:
                sub_positions.append((i, m.group(1)))
        sub_positions.append((e, ""))
        for i in range(len(sub_positions) - 1):
            s_start, header = sub_positions[i]
            s_end, _ = sub_positions[i + 1]
            for sub_key, accepted in V2_BESCHREIBUNG_SUB.items():
                if any(_normalize_header(a) == _normalize_header(header) for a in accepted):
                    result[sub_key] = "\n".join(lines[s_start + 1:s_end]).strip()
                    break
    return result


def validate_pflicht_v2(md: str) -> dict[str, bool]:
    """Liefert {key: vorhanden_und_nicht_leer} für v2-Pflichtsektionen."""
    sec = parse_content_sections_v2(md)
    aufgaben = parse_aufgaben(md)

    def filled(text: str) -> bool:
        stripped = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL).strip()
        return bool(stripped)

    return {
        "szenario": filled(sec.get("szenario", "")),
        "lernziele": filled(sec.get("lernziele", "")),
        "vorwissen": filled(sec.get("vorwissen", "")),
        "aufgaben_min_1": len(aufgaben) >= 1,
    }


def missing_pflicht_v2(md: str) -> list[str]:
    val = validate_pflicht_v2(md)
    labels = {
        "szenario": "Szenario / Auftrag",
        "lernziele": "Lernziele",
        "vorwissen": "Vorwissen / Anknüpfung",
        "aufgaben_min_1": "mindestens eine Aufgabe",
    }
    return [labels[k] for k, ok in val.items() if not ok]


_AUFGABE_HEADER_RE = re.compile(r"^###\s+Aufgabe\s+(\d+)\s*[:\.\-–]\s*(.+?)\s*$",
                                re.IGNORECASE)
_PHASE_LINE_RE = re.compile(r"^[\*_]+\s*(?:Phasen?|Phase)\s*:[\*_]*\s*(.+?)\s*$",
                            re.IGNORECASE)


def parse_aufgaben(md: str) -> list[dict]:
    """Findet alle ### Aufgabe N: Titel-Sektionen innerhalb von
    '## 2. Phasen der vollständigen Handlung'. Liefert Liste mit
    {nummer, titel, anchor, phasen (list[str]), body, loesungsskizze}."""
    sections = _parse_h2_sections(md)
    lines: list[str] = sections.pop("__lines__")  # type: ignore
    if "phasen" not in sections:
        return []
    start, end, _ = sections["phasen"]

    # Aufgaben-Headers in diesem Bereich
    headers: list[tuple[int, int, str]] = []  # (line_idx, nummer, titel)
    for i in range(start + 1, end):
        m = _AUFGABE_HEADER_RE.match(lines[i])
        if m:
            try:
                nummer = int(m.group(1))
            except ValueError:
                continue
            titel = m.group(2).strip()
            headers.append((i, nummer, titel))
    headers.append((end, -1, ""))  # Sentinel

    out: list[dict] = []
    for i in range(len(headers) - 1):
        h_line, nummer, titel = headers[i]
        next_line, _, _ = headers[i + 1]
        block_lines = lines[h_line + 1:next_line]

        # Phasen-Zeile suchen (erste nicht-leere Zeile)
        phasen: list[str] = []
        body_start = 0
        for j, ln in enumerate(block_lines):
            if not ln.strip():
                continue
            pm = _PHASE_LINE_RE.match(ln)
            if pm:
                raw = pm.group(1)
                # Tags aufsplitten an Komma/Slash
                parts = re.split(r"[,/]", raw)
                for p in parts:
                    pn = _normalize_header(p)
                    if pn in PHASEN_NAMEN:
                        # nett-formatiert zurück: Capitalized original
                        phasen.append(p.strip().title())
                body_start = j + 1
            break

        # Lösungsskizze (#### Lösungsskizze) im Block
        body_chunk = block_lines[body_start:]
        loesungsskizze = ""
        body = "\n".join(body_chunk).strip()
        for j, ln in enumerate(body_chunk):
            m = re.match(r"^####\s+(.+?)\s*$", ln)
            if m and _normalize_header(m.group(1)) in (
                _normalize_header("Lösungsskizze"),
                _normalize_header("Loesungsskizze"),
            ):
                body = "\n".join(body_chunk[:j]).strip()
                loesungsskizze = "\n".join(body_chunk[j + 1:]).strip()
                break

        anchor = f"aufgabe-{nummer}"
        out.append({
            "nummer": nummer,
            "titel": titel,
            "anchor": anchor,
            "phasen": phasen,
            "body": body,
            "loesungsskizze": loesungsskizze,
        })
    out.sort(key=lambda a: a["nummer"])
    return out


def build_template_md_v2(ls: LearningSituation) -> str:
    """Schema-v2-Skeleton mit Frontmatter + Pflicht-Sektionen + 1 Beispiel-Aufgabe."""
    fm = {
        "ls_id": ls.id,
        "slug": ls.slug,
        "display_name": ls.display_name,
        "klasse": ls.klassen_key or "",
        "lernfeld": ls.lernfeld or "",
        "created": (ls.created_at.date().isoformat()
                    if ls.created_at else datetime.utcnow().date().isoformat()),
        "updated": datetime.utcnow().date().isoformat(),
        "schema_version": 2,
    }
    buf = io.StringIO()
    buf.write("---\n")
    buf.write(yaml.safe_dump(fm, allow_unicode=True, sort_keys=False))
    buf.write("---\n\n")
    buf.write(f"# {ls.display_name}\n\n")

    buf.write("## 1. Lernsituationsbeschreibung\n\n")
    buf.write("### Szenario / Auftrag\n")
    buf.write("<!-- Pflicht: berufstypischer Einstieg, „Du bist Mechatroniker:in im Unternehmen …" -->\n\n")
    buf.write("### Lernziele\n")
    buf.write("<!-- Pflicht: operationalisiert -->\n")
    buf.write("- Die SuS können …\n\n")
    buf.write("### Vorwissen / Anknüpfung\n")
    buf.write("<!-- Pflicht: was bringen die SuS mit, was ist noch neu -->\n\n")

    buf.write("## 2. Phasen der vollständigen Handlung\n\n")
    buf.write("### Aufgabe 1: Titel\n")
    buf.write("*Phasen:* Informieren, Planen\n\n")
    buf.write("<!-- Auftragstext im Imperativ, Material, Sozialform -->\n\n")
    buf.write("#### Lösungsskizze\n")
    buf.write("<!-- Erwartungshorizont, typische Fehler -->\n\n")

    buf.write("## 3. Anmerkungen\n")
    buf.write("<!-- optional: Erfahrungen aus dem Lauf, Material-Tipps -->\n\n")

    buf.write("---\n\n")
    buf.write(f"{OUTPUT_SECTION_HEADER}\n\n")
    buf.write("*Vom Wizard automatisch befüllt — pro Generierung ein Block.*\n")
    return buf.getvalue()


def content_md_body(md: str) -> str:
    """Gibt den Body OHNE Frontmatter und OHNE Output-Sektion zurück.
    Wird als Kontext-Block in die Material-Prompts eingebettet."""
    _, body = split_frontmatter(md)
    # Output-Sektion (und horizontaler Trenner davor) abschneiden
    idx = body.find(OUTPUT_SECTION_HEADER)
    if idx >= 0:
        body = body[:idx]
        # Trenner-Linie davor entfernen
        body = re.sub(r"\n---\s*\n\s*$", "\n", body)
    return body.strip()
