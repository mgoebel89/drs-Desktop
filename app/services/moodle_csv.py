"""CSV-Parser für Schülerlisten mit Auto-Erkennung des Formats.

Unterstützt zwei Formate:
- **Klassisch**: `Nachname;Vorname[;Email]` (kein Header)
- **Moodle-Teilnehmer-Export**: Komma-getrennt mit Header, Spalten
  meist `Vorname,Nachname,ID-Nummer,E-Mail-Adresse,…`.

Die Erkennung läuft über die erste Zeile: enthält sie Header-Wörter
wie 'Vorname'/'Nachname'/'E-Mail', greift der Moodle-Parser; sonst
der Semikolon-Parser.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass


@dataclass
class ParsedStudent:
    nachname: str
    vorname: str
    email: str = ""
    moodle_id: str = ""


_HEADER_KEYS_NACHNAME = ("nachname", "lastname", "last name", "surname")
_HEADER_KEYS_VORNAME = ("vorname", "firstname", "first name", "given name")
_HEADER_KEYS_EMAIL = ("email", "e-mail", "e-mail-adresse", "e-mailadresse", "mail")
_HEADER_KEYS_ID = ("id-nummer", "moodle-id", "moodle id", "id", "user id")


def _norm(s: str) -> str:
    return s.strip().strip('"').strip("'").lower()


def _looks_like_moodle_header(line: str) -> bool:
    """Erste Zeile als Header? — wenn 'Vorname' UND 'Nachname' drin."""
    n = _norm(line)
    has_vor = any(k in n for k in _HEADER_KEYS_VORNAME)
    has_nach = any(k in n for k in _HEADER_KEYS_NACHNAME)
    return has_vor and has_nach


def _detect_delimiter(line: str) -> str:
    """Heuristik: häufigster Trenner zwischen ; , und \\t."""
    counts = {",": line.count(","), ";": line.count(";"), "\t": line.count("\t")}
    return max(counts, key=lambda k: counts[k]) if max(counts.values()) > 0 else ";"


def _parse_with_header(text: str) -> list[ParsedStudent]:
    """Parsing mit Header-Erkennung (Moodle-Format)."""
    text = text.lstrip("﻿")  # BOM entfernen
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    delim = _detect_delimiter(lines[0])
    reader = csv.reader(io.StringIO(text), delimiter=delim, quotechar='"')
    rows = list(reader)
    if not rows:
        return []
    header = [_norm(h) for h in rows[0]]

    def col_idx(keys: tuple[str, ...]) -> int | None:
        for i, h in enumerate(header):
            if any(k == h or k in h for k in keys):
                return i
        return None

    i_nach = col_idx(_HEADER_KEYS_NACHNAME)
    i_vor = col_idx(_HEADER_KEYS_VORNAME)
    i_mail = col_idx(_HEADER_KEYS_EMAIL)
    i_id = col_idx(_HEADER_KEYS_ID)

    if i_nach is None or i_vor is None:
        return []

    out: list[ParsedStudent] = []
    for row in rows[1:]:
        if not row or all(not c.strip() for c in row):
            continue
        nachname = (row[i_nach] if i_nach < len(row) else "").strip()
        vorname = (row[i_vor] if i_vor < len(row) else "").strip()
        if not nachname:
            continue
        email = (row[i_mail].strip() if i_mail is not None and i_mail < len(row) else "")
        moodle_id = (row[i_id].strip() if i_id is not None and i_id < len(row) else "")
        out.append(ParsedStudent(nachname=nachname, vorname=vorname,
                                 email=email, moodle_id=moodle_id))
    return out


def _parse_simple(text: str) -> list[ParsedStudent]:
    """Klassischer Parser: pro Zeile Nachname;Vorname[;Email]."""
    out: list[ParsedStudent] = []
    for line in text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line:
            continue
        parts = re.split(r"[;\t,]", line)
        nachname = parts[0].strip() if parts else ""
        if not nachname:
            continue
        vorname = parts[1].strip() if len(parts) > 1 else ""
        email = parts[2].strip() if len(parts) > 2 else ""
        out.append(ParsedStudent(nachname=nachname, vorname=vorname, email=email))
    return out


def parse_csv(text: str) -> tuple[list[ParsedStudent], str]:
    """Auto-Erkennung. Liefert (Liste, format_label)."""
    text = text.lstrip("﻿")
    first_line = next((l for l in text.splitlines() if l.strip()), "")
    if _looks_like_moodle_header(first_line):
        return _parse_with_header(text), "moodle"
    return _parse_simple(text), "simple"
