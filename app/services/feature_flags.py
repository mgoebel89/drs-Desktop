"""Globale Feature-Flags (DB-gestützt über Setting-Tabelle).

Aktuell nur `ai_enabled` — schaltet KI-Bestandteile (Wizard, Fobizz-/
Claude-Tabs, Material-Generierung) sichtbar/unsichtbar. Default ist
`False`, damit das System im rein manuellen Modus läuft. Admin kann
unter Einstellungen umschalten.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Setting


def _get(db: Session, key: str) -> Setting | None:
    return db.get(Setting, key)


def is_ai_enabled(db: Session) -> bool:
    s = _get(db, "ai_enabled")
    return bool(s and (s.value or "").lower() in ("1", "true", "yes", "on"))


def set_ai_enabled(db: Session, value: bool) -> None:
    s = _get(db, "ai_enabled") or Setting(key="ai_enabled")
    s.value = "1" if value else "0"
    s.updated_at = datetime.utcnow()
    db.merge(s)
