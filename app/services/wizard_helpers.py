"""Hilfsfunktionen für den Planungs-Wizard."""
from __future__ import annotations

from slugify import slugify

from app.models import LearningSituation


def make_slug(display_name: str) -> str:
    s = slugify(display_name, lowercase=True, max_length=80)
    return s or "lernsituation"


def folder_name(ls_id: int, slug: str) -> str:
    """Stabiler Ordnername. Pattern: 'LS-{id:04d}_{slug}'."""
    return f"LS-{ls_id:04d}_{slug}"


def build_fobizz_prompt(ls: LearningSituation, letzte_stunde: str = "") -> str:
    """Erzeugt den Kontext-Prompt für den vorab konfigurierten Fobizz-Agenten."""
    parts = [
        "Plane bitte die nächste Unterrichtseinheit zur folgenden Lernsituation.",
        "",
        f"**Klasse:** {ls.klassen_key or '(nicht gesetzt)'}",
        f"**Lernfeld:** {ls.lernfeld or '(nicht gesetzt)'}",
        f"**Lernsituation:** {ls.display_name}",
        "",
    ]
    if ls.lernziele.strip():
        parts.append("**Lernziele:**")
        parts.append(ls.lernziele.strip())
        parts.append("")
    if ls.vorwissen.strip():
        parts.append("**Vorwissen / Anknüpfung:**")
        parts.append(ls.vorwissen.strip())
        parts.append("")
    if letzte_stunde.strip():
        parts.append("**Stand aus der letzten Stunde:**")
        parts.append(letzte_stunde.strip())
        parts.append("")
    parts.extend([
        "Bitte erzeuge:",
        "1. einen kurzen didaktischen Kommentar (Einstieg, Phasierung, Sicherung)",
        "2. konkrete Aufgaben mit Erwartungshorizont",
        "3. eine Liste vorgeschlagener Materialien (Arbeitsblatt, Tafelbild, Simulation, …)",
        "",
        "Antworte in deutschem Markdown. Halte dich an die Struktur, die im "
        "Agenten-Systemprompt definiert ist.",
    ])
    return "\n".join(parts)
