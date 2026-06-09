"""Zwei-Wege-Synchronisation App ↔ Obsidian-Vault für v3-Lernsituationen.

Architektur
-----------
Quelle ist die MD-Datei im Vault. Die App-Datenbank spiegelt die
Sektionen (Lernsituation, Lehrerinformationen, Arbeitsblätter,
Leistungsfeststellung) zur Inline-Bearbeitung und für strukturierte
Queries (z. B. Stundenplan-Aufgaben-Picker).

Drei Datenflüsse:

1. **Pull**  (`load_from_vault`)
   Liest die MD, schreibt die Sektionsinhalte in die DB, aktualisiert
   `content_hash` + `content_mtime`. Wird beim Öffnen des LS-Details und
   bei externem File-Change aufgerufen.

2. **Push**  (`save_to_vault`)
   Baut die MD aus den aktuellen DB-Inhalten, schreibt sie in den Vault,
   aktualisiert `content_hash` + `content_mtime`. Wird nach jedem
   Inline-Edit aus der App aufgerufen.

3. **Konflikt-Detection**  (`detect_conflict`)
   Vergleicht den aktuellen Datei-Hash mit dem zuletzt gespeicherten
   `ls.content_hash`. Stimmt er nicht überein, hat seit dem letzten
   App-Lese-/Schreib-Vorgang jemand (in der Regel Obsidian) die Datei
   geändert. Liefert sektions-granularen Diff für die Merge-UI.

Konflikt-Auflösung läuft sektionsweise: für jede Sektion entscheidet der
Lehrer "Obsidian behalten" oder "App-Wert behalten". `apply_resolution`
schreibt die gewählten Werte in die DB und ruft `save_to_vault`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import LearningSituation, LsArbeitsblatt, LsAufgabe, User
from app.services import obsidian_writer, obsidian_writer_v3 as v3, smb_client


# ── Datentransport ──────────────────────────────────────────────────────


@dataclass
class SectionDiff:
    """Pro Sektion: App-Wert (DB) und Obsidian-Wert (Datei). Wenn beide
    identisch sind, taucht die Sektion nicht im Diff auf."""
    key: str                 # interner Identifier z. B. 'lernsituation', 'arbeitsblatt:2'
    label: str               # menschlich lesbarer Sektionsname
    app_value: str           # aktueller DB-Inhalt
    vault_value: str         # aktueller Datei-Inhalt


@dataclass
class ConflictReport:
    ls_id: int
    file_hash: str
    db_hash: str
    sections: list[SectionDiff] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return bool(self.sections)


# ── Helpers ─────────────────────────────────────────────────────────────


def _doc_from_db(db: Session, ls: LearningSituation) -> v3.V3Document:
    """Baut ein V3Document aus DB-Inhalten. Aufgaben werden aus
    ls_aufgaben pro Arbeitsblatt zusammengetragen."""
    abs_rows = db.scalars(
        select(LsArbeitsblatt)
        .where(LsArbeitsblatt.learning_situation_id == ls.id)
        .order_by(LsArbeitsblatt.position)
    ).all()
    arbeitsblaetter: list[v3.V3Arbeitsblatt] = []
    for ab in abs_rows:
        aufg = db.scalars(
            select(LsAufgabe)
            .where(LsAufgabe.arbeitsblatt_id == ab.id)
            .order_by(LsAufgabe.nummer)
        ).all()
        arbeitsblaetter.append(v3.V3Arbeitsblatt(
            position=ab.position,
            title=ab.title or f"Arbeitsblatt {ab.position}",
            phase=ab.phase,
            bearbeitungshinweis_md=ab.bearbeitungshinweis_md,
            intro_md="",  # Intro nicht separat gespeichert
            aufgaben=[
                v3.V3Aufgabe(
                    nummer=a.nummer, titel=a.titel,
                    text_md="",  # Aufgaben-Body wird unten aus content_md gezogen
                    loesungsskizze_md="",
                )
                for a in aufg
            ],
        ))
    return v3.V3Document(
        frontmatter={},
        meta={},
        lernsituation_md=ls.lernsituation_md,
        lernsituation_bild_path=ls.lernsituation_bild_path,
        kompetenzen_md=ls.kompetenzen_md,
        uebergreifende_aspekte_md=ls.uebergreifende_aspekte_md,
        lehrer_vorwissen_md=ls.lehrer_vorwissen_md,
        arbeitsblaetter=arbeitsblaetter,
        leistungsfeststellung_md=ls.leistungsfeststellung_md,
    )


def _read_md(user: User, ls: LearningSituation) -> tuple[str, str, datetime | None]:
    """Liest MD aus Vault, liefert (text, hash, mtime). Mtime ist derzeit
    nicht aus SMB ermittelbar — wird auf utcnow gesetzt, wenn gelesen."""
    raw = obsidian_writer.read_note(user, ls) or ""
    return raw, v3.content_hash(raw) if raw else "", datetime.utcnow() if raw else None


# ── Pull (Vault → DB) ───────────────────────────────────────────────────


def load_from_vault(db: Session, user: User, ls: LearningSituation) -> bool:
    """Liest die MD und überträgt die Sektionen in die DB. Aufgaben werden
    sektionsweise (pro Arbeitsblatt) ersetzt. Liefert True, wenn etwas in
    die DB geschrieben wurde."""
    raw, file_hash, mtime = _read_md(user, ls)
    if not raw:
        return False
    doc = v3.parse_v3(raw)

    # Top-Level-Felder
    ls.lernsituation_md = doc.lernsituation_md
    ls.lernsituation_bild_path = doc.lernsituation_bild_path
    ls.kompetenzen_md = doc.kompetenzen_md
    ls.uebergreifende_aspekte_md = doc.uebergreifende_aspekte_md
    ls.lehrer_vorwissen_md = doc.lehrer_vorwissen_md
    ls.leistungsfeststellung_md = doc.leistungsfeststellung_md
    if doc.meta.get("Dauer in Stunden", "").isdigit():
        ls.dauer_stunden = int(doc.meta["Dauer in Stunden"])
    if doc.meta.get("Version", "").isdigit():
        ls.version_no = int(doc.meta["Version"])
    if not ls.schema_version or ls.schema_version < 3:
        ls.schema_version = 3

    # Arbeitsblätter komplett ersetzen (Reihenfolge + Inhalt aus MD)
    db.execute(delete(LsArbeitsblatt).where(
        LsArbeitsblatt.learning_situation_id == ls.id))
    db.flush()
    for ab in doc.arbeitsblaetter:
        row = LsArbeitsblatt(
            learning_situation_id=ls.id,
            position=ab.position,
            title=ab.title,
            phase=ab.phase,
            bearbeitungshinweis_md=ab.bearbeitungshinweis_md,
            content_md=ab.intro_md,
        )
        db.add(row)
        db.flush()
        for a in ab.aufgaben:
            db.add(LsAufgabe(
                learning_situation_id=ls.id,
                arbeitsblatt_id=row.id,
                nummer=a.nummer,
                titel=a.titel or "",
                anchor=f"aufgabe-{a.nummer}",
                phasen=ab.phase or "",
            ))

    ls.content_hash = file_hash
    ls.content_mtime = mtime
    return True


# ── Push (DB → Vault) ───────────────────────────────────────────────────


def save_to_vault(user: User, ls: LearningSituation, db: Session) -> str:
    """Baut MD aus DB-Inhalten und schreibt sie in den Vault. Aktualisiert
    `content_hash` + `content_mtime`. Liefert den geschriebenen MD-Text."""
    doc = _doc_from_db(db, ls)
    md = v3.build_markdown_v3(ls, doc)
    obsidian_writer.write_note(user, ls, md)
    ls.content_hash = v3.content_hash(md)
    ls.content_mtime = datetime.utcnow()
    if not ls.schema_version or ls.schema_version < 3:
        ls.schema_version = 3
    return md


# ── Konflikt-Detection ──────────────────────────────────────────────────


def detect_conflict(db: Session, user: User, ls: LearningSituation) -> ConflictReport:
    """Vergleicht aktuellen Datei-Hash mit dem in der DB gespeicherten.

    Wenn die Hashes übereinstimmen, ist nichts zu tun (leerer Report).
    Sonst werden die Sektionen verglichen, in denen sich App- und Vault-
    Stand unterscheiden — diese kommen in den `sections`-Diff."""
    raw, file_hash, _ = _read_md(user, ls)
    rep = ConflictReport(ls_id=ls.id, file_hash=file_hash, db_hash=ls.content_hash or "")
    if not raw or file_hash == (ls.content_hash or ""):
        return rep
    vault_doc = v3.parse_v3(raw)

    def push(key: str, label: str, app_v: str, vault_v: str) -> None:
        if (app_v or "").strip() != (vault_v or "").strip():
            rep.sections.append(SectionDiff(
                key=key, label=label,
                app_value=app_v or "", vault_value=vault_v or "",
            ))

    push("lernsituation", "Lernsituation",
         ls.lernsituation_md, vault_doc.lernsituation_md)
    push("kompetenzen", "Kompetenzen",
         ls.kompetenzen_md, vault_doc.kompetenzen_md)
    push("uebergreifende_aspekte", "Übergreifende Aspekte",
         ls.uebergreifende_aspekte_md, vault_doc.uebergreifende_aspekte_md)
    push("lehrer_vorwissen", "Vorwissen (Lehrerinfo)",
         ls.lehrer_vorwissen_md, vault_doc.lehrer_vorwissen_md)
    push("leistungsfeststellung", "Leistungsfeststellung",
         ls.leistungsfeststellung_md, vault_doc.leistungsfeststellung_md)

    # Arbeitsblätter sektionsweise vergleichen (Position als Key).
    db_abs = {ab.position: ab for ab in db.scalars(
        select(LsArbeitsblatt)
        .where(LsArbeitsblatt.learning_situation_id == ls.id)
    ).all()}
    seen = set()
    for vab in vault_doc.arbeitsblaetter:
        seen.add(vab.position)
        dbab = db_abs.get(vab.position)
        if dbab is None:
            rep.sections.append(SectionDiff(
                key=f"arbeitsblatt:{vab.position}",
                label=f"Arbeitsblatt {vab.position} (in Obsidian neu)",
                app_value="",
                vault_value=_arbeitsblatt_as_md(vab),
            ))
            continue
        vault_str = _arbeitsblatt_as_md(vab)
        app_vab = v3.V3Arbeitsblatt(
            position=dbab.position, title=dbab.title, phase=dbab.phase,
            bearbeitungshinweis_md=dbab.bearbeitungshinweis_md,
            intro_md=dbab.content_md, aufgaben=[],
        )
        # Aufgaben aus DB ergänzen
        for a in db.scalars(
            select(LsAufgabe)
            .where(LsAufgabe.arbeitsblatt_id == dbab.id)
            .order_by(LsAufgabe.nummer)
        ).all():
            app_vab.aufgaben.append(v3.V3Aufgabe(
                nummer=a.nummer, titel=a.titel, text_md="", loesungsskizze_md="",
            ))
        app_str = _arbeitsblatt_as_md(app_vab)
        if app_str.strip() != vault_str.strip():
            rep.sections.append(SectionDiff(
                key=f"arbeitsblatt:{vab.position}",
                label=vab.title or f"Arbeitsblatt {vab.position}",
                app_value=app_str, vault_value=vault_str,
            ))
    for pos in db_abs.keys() - seen:
        rep.sections.append(SectionDiff(
            key=f"arbeitsblatt:{pos}",
            label=f"Arbeitsblatt {pos} (in Obsidian gelöscht)",
            app_value=_arbeitsblatt_as_md_from_db(db, db_abs[pos]),
            vault_value="",
        ))
    return rep


def _arbeitsblatt_as_md(ab: v3.V3Arbeitsblatt) -> str:
    """Hilft beim Diff: ein V3Arbeitsblatt als kompakte MD für den Compare."""
    buf = [f"# {ab.title}"]
    if ab.phase:
        buf.append(f"> {ab.phase}")
    if ab.bearbeitungshinweis_md:
        buf.append(f">[!NOTE] {ab.bearbeitungshinweis_md.strip()}")
    if ab.intro_md:
        buf.append(ab.intro_md.strip())
    for a in ab.aufgaben:
        buf.append(f"## Aufgabe {a.nummer}")
        if a.titel:
            buf[-1] += f": {a.titel}"
        if a.text_md:
            buf.append(a.text_md.strip())
        if a.loesungsskizze_md:
            buf.append(f"## Lösungsskizze Aufgabe {a.nummer}")
            buf.append(a.loesungsskizze_md.strip())
    return "\n\n".join(buf)


def _arbeitsblatt_as_md_from_db(db: Session, dbab: LsArbeitsblatt) -> str:
    auf = [v3.V3Aufgabe(nummer=a.nummer, titel=a.titel, text_md="", loesungsskizze_md="")
           for a in db.scalars(
               select(LsAufgabe)
               .where(LsAufgabe.arbeitsblatt_id == dbab.id)
               .order_by(LsAufgabe.nummer)
           ).all()]
    return _arbeitsblatt_as_md(v3.V3Arbeitsblatt(
        position=dbab.position, title=dbab.title, phase=dbab.phase,
        bearbeitungshinweis_md=dbab.bearbeitungshinweis_md,
        intro_md=dbab.content_md, aufgaben=auf,
    ))


# ── Konflikt-Auflösung ──────────────────────────────────────────────────


def apply_resolution(
    db: Session, user: User, ls: LearningSituation,
    choices: dict[str, str],
) -> None:
    """Wendet die Lehrer-Entscheidungen pro Sektion an.

    `choices`: { section_key: 'app' | 'vault' }. Für alle Keys mit Wert
    'vault' wird der Vault-Inhalt in die DB gehoben, dann werden alle
    DB-Felder in die MD geschrieben (Push). Damit gewinnt die App nach
    der Auflösung — die Datei spiegelt den vom Lehrer gewählten Mix."""
    raw, _, _ = _read_md(user, ls)
    if not raw:
        return
    vault_doc = v3.parse_v3(raw)

    field_map = {
        "lernsituation": "lernsituation_md",
        "kompetenzen": "kompetenzen_md",
        "uebergreifende_aspekte": "uebergreifende_aspekte_md",
        "lehrer_vorwissen": "lehrer_vorwissen_md",
        "leistungsfeststellung": "leistungsfeststellung_md",
    }
    vault_attrs = {
        "lernsituation": vault_doc.lernsituation_md,
        "kompetenzen": vault_doc.kompetenzen_md,
        "uebergreifende_aspekte": vault_doc.uebergreifende_aspekte_md,
        "lehrer_vorwissen": vault_doc.lehrer_vorwissen_md,
        "leistungsfeststellung": vault_doc.leistungsfeststellung_md,
    }

    for key, choice in choices.items():
        if choice != "vault":
            continue
        if key in field_map:
            setattr(ls, field_map[key], vault_attrs[key])
        elif key.startswith("arbeitsblatt:"):
            try:
                pos = int(key.split(":", 1)[1])
            except ValueError:
                continue
            vab = next((a for a in vault_doc.arbeitsblaetter if a.position == pos), None)
            db.execute(delete(LsArbeitsblatt).where(
                LsArbeitsblatt.learning_situation_id == ls.id,
                LsArbeitsblatt.position == pos,
            ))
            db.flush()
            if vab is None:
                continue
            row = LsArbeitsblatt(
                learning_situation_id=ls.id,
                position=vab.position,
                title=vab.title,
                phase=vab.phase,
                bearbeitungshinweis_md=vab.bearbeitungshinweis_md,
                content_md=vab.intro_md,
            )
            db.add(row)
            db.flush()
            for a in vab.aufgaben:
                db.add(LsAufgabe(
                    learning_situation_id=ls.id,
                    arbeitsblatt_id=row.id,
                    nummer=a.nummer,
                    titel=a.titel or "",
                    anchor=f"aufgabe-{a.nummer}",
                    phasen=vab.phase or "",
                ))

    save_to_vault(user, ls, db)
