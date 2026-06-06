"""Direkte Worksheet-Erzeugung aus der Inhalts-MD einer Lernsituation.

Kein KI-Umweg — die Aufgaben sind in der MD bereits ausformuliert. Wir
parsen sie und bauen daraus die Worksheet-Struktur, die der bestehende
Editor (Worksheet.aufgaben_json + meta_json) erwartet.

Rollen:
- "student" → Schüler-Version, Lösungsskizze geht NICHT auf das Blatt.
- "teacher" → Lehrer-Version, Lösungsskizze landet in 'musterloesungText'.
"""
from __future__ import annotations

import json
from typing import Literal

from sqlalchemy.orm import Session

from app.models import LearningSituation, User, Worksheet, WorksheetRevision
from app.services import obsidian_writer

Role = Literal["student", "teacher"]


def _szenario_text(sections: dict) -> str:
    """Setzt die Lernsituationsbeschreibung als Vorspann zusammen."""
    parts = []
    if sections.get("szenario"):
        parts.append(sections["szenario"].strip())
    if sections.get("lernziele"):
        parts.append("**Lernziele:**\n" + sections["lernziele"].strip())
    return "\n\n".join(parts).strip()


def build_worksheet_payload(
    ls: LearningSituation,
    md: str,
    role: Role,
    nummer_filter: list[int] | None = None,
) -> tuple[dict, list[dict], str]:
    """Liefert (meta, aufgaben, role_suffix) bereit zum Speichern.
    nummer_filter (optional): nur diese Aufgaben-Nummern übernehmen."""
    sections = obsidian_writer.parse_content_sections_v2(md)
    aufgaben_md = obsidian_writer.parse_aufgaben(md)

    if nummer_filter is not None:
        wanted = set(nummer_filter)
        aufgaben_md = [a for a in aufgaben_md if a["nummer"] in wanted]

    label = "lernfeld" if ls.lernfeld else "fach"
    header_value = ls.lernfeld or ls.klassen_key or ""

    role_suffix = "Lehrer-Version" if role == "teacher" else "Schüler-Version"
    meta = {
        "headerLabel": label,
        "headerValue": header_value,
        "lernsituationTitel": ls.display_name,
        "lernsituationText": _szenario_text(sections),
        "lernsituationBild": "",
        "role": role,
        "source": "ls",
        "ls_id": ls.id,
    }

    aufgaben_out: list[dict] = []
    for a in aufgaben_md:
        title = f"Aufgabe {a['nummer']}: {a['titel']}".strip()
        phasen_val = a.get("phasen") or []
        if isinstance(phasen_val, list):
            phasen_str = ", ".join(phasen_val)
        else:
            phasen_str = str(phasen_val)
        phasen = f"_Phase(n): {phasen_str}_\n\n" if phasen_str else ""
        body = a.get("body", "").strip()
        text = f"**{title}**\n\n{phasen}{body}".strip()

        aufgabe = {
            "id": a["nummer"],
            "text": text,
            "kriterien": "",
            "musterloesungText": "" if role == "student" else (a.get("loesungsskizze") or "").strip(),
            "musterloesungBild": "",
            "upload": True,
            "uploadPDF": False,
        }
        aufgaben_out.append(aufgabe)

    return meta, aufgaben_out, role_suffix


def create_worksheet_from_ls(
    db: Session, user: User, ls: LearningSituation,
    role: Role, nummer_filter: list[int] | None = None,
) -> Worksheet:
    """Erzeugt Worksheet + erste WorksheetRevision. Liefert das Worksheet."""
    md = obsidian_writer.read_note(user, ls)
    if not md.strip():
        raise ValueError("Keine Inhalts-MD vorhanden")

    schema = obsidian_writer.detect_schema_version(md)
    if schema < 2:
        raise ValueError("Schema v1 — bitte erst auf v2 migrieren (Wizard Schritt 1)")

    meta, aufgaben, role_suffix = build_worksheet_payload(ls, md, role, nummer_filter)

    title = f"{ls.display_name} · {role_suffix}"
    if nummer_filter:
        title += f" (Aufg. {', '.join(str(n) for n in sorted(nummer_filter))})"

    ws = Worksheet(
        owner_user_id=user.id,
        title=title[:200],
        learning_situation_id=ls.id,
    )
    db.add(ws)
    db.flush()

    rev = WorksheetRevision(
        worksheet_id=ws.id,
        created_by_user_id=user.id,
        comment=f"Aus Lernsituation ({role_suffix})",
        meta_json=json.dumps(meta, ensure_ascii=False),
        aufgaben_json=json.dumps(aufgaben, ensure_ascii=False),
        markdown_source="",
    )
    db.add(rev)
    return ws
