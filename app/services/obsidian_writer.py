"""Obsidian-Vault-Pflege: pro Lernsituation eine .md-Datei.

Schreibt YAML-Frontmatter + strukturierte Sektionen in den Vault-Unterordner
des SMB-Shares. Liest existierende Notizen für die App-Anzeige.
"""
from __future__ import annotations

import io
from datetime import datetime

import yaml

from app.models import LearningSituation, User
from app.services import smb_client


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
