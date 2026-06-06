"""Sync von Aufgaben aus der LS-Inhalts-MD in die DB-Tabelle ls_aufgaben.

Wird automatisch beim Öffnen relevanter Seiten aufgerufen — idempotent,
schnell. Die MD bleibt die Quelle, die DB ist nur ein Index für
Verknüpfungen und Anzeige.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LearningSituation, LsAufgabe, User
from app.services import obsidian_writer


def sync_from_md(db: Session, user: User, ls: LearningSituation) -> list[LsAufgabe]:
    """Liest LS-MD, parst Aufgaben, upsert per (ls_id, nummer), löscht stale.
    Liefert die aktuelle Liste der DB-Records (sortiert nach nummer)."""
    try:
        md = obsidian_writer.read_note(user, ls)
    except Exception:
        md = ""
    if not md.strip():
        # Keine MD → alle Aufgaben für diese LS löschen
        existing = db.query(LsAufgabe).filter(LsAufgabe.learning_situation_id == ls.id).all()
        for a in existing:
            db.delete(a)
        db.flush()
        return []

    schema = obsidian_writer.detect_schema_version(md)
    if schema < 2:
        # v1-LS hat keine Aufgaben-Struktur — leeren Index halten
        existing = db.query(LsAufgabe).filter(LsAufgabe.learning_situation_id == ls.id).all()
        for a in existing:
            db.delete(a)
        db.flush()
        return []

    parsed = obsidian_writer.parse_aufgaben(md)
    parsed_nummern = {p["nummer"] for p in parsed}

    existing = {
        a.nummer: a for a in
        db.query(LsAufgabe).filter(LsAufgabe.learning_situation_id == ls.id).all()
    }

    # Stale löschen (Cascade nimmt M2M mit)
    for nummer, a in existing.items():
        if nummer not in parsed_nummern:
            db.delete(a)

    # Upsert
    for p in parsed:
        phasen_csv = ", ".join(p["phasen"]) if p["phasen"] else ""
        a = existing.get(p["nummer"])
        if a is None:
            a = LsAufgabe(
                learning_situation_id=ls.id,
                nummer=p["nummer"],
                titel=p["titel"],
                anchor=p["anchor"],
                phasen=phasen_csv,
            )
            db.add(a)
        else:
            a.titel = p["titel"]
            a.anchor = p["anchor"]
            a.phasen = phasen_csv

    db.flush()

    rows = (
        db.query(LsAufgabe)
        .filter(LsAufgabe.learning_situation_id == ls.id)
        .order_by(LsAufgabe.nummer)
        .all()
    )
    return rows


def get_aufgabe_md(user: User, ls: LearningSituation, nummer: int) -> dict | None:
    """Holt eine bestimmte Aufgabe aus der MD inklusive Body + Lösungsskizze.
    On-demand für Block-Panel-Anzeige."""
    try:
        md = obsidian_writer.read_note(user, ls)
    except Exception:
        return None
    for p in obsidian_writer.parse_aufgaben(md):
        if p["nummer"] == nummer:
            return p
    return None
