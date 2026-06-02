"""Branding-Service: Schulname + Logo aus der Settings-Tabelle.

Default-Werte werden beim ersten Zugriff aus dem mitgelieferten
app/static/default_school_logo.jpg geseedet."""
import base64
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Setting

DEFAULT_SCHOOL_NAME = "David-Roentgen-Schule · Neuwied"
DEFAULT_LOGO_PATH = Path(__file__).resolve().parent / "static" / "default_school_logo.jpg"


def _get(db: Session, key: str) -> Setting | None:
    return db.get(Setting, key)


def get_school_name(db: Session) -> str:
    s = _get(db, "school_name")
    return s.value if s and s.value else DEFAULT_SCHOOL_NAME


def set_school_name(db: Session, name: str) -> None:
    s = _get(db, "school_name") or Setting(key="school_name")
    s.value = name.strip()
    s.updated_at = datetime.utcnow()
    db.merge(s)


def get_logo_bytes(db: Session) -> tuple[bytes, str]:
    """Liefert (bytes, mime). Wenn keine Settings-Variante: Default-Datei."""
    s = _get(db, "school_logo")
    if s and s.blob:
        return s.blob, (s.mime or "image/jpeg")
    if DEFAULT_LOGO_PATH.exists():
        return DEFAULT_LOGO_PATH.read_bytes(), "image/jpeg"
    return b"", "image/jpeg"


def set_logo_bytes(db: Session, data: bytes, mime: str) -> None:
    s = _get(db, "school_logo") or Setting(key="school_logo")
    s.blob = data
    s.mime = mime
    s.value = ""
    s.updated_at = datetime.utcnow()
    db.merge(s)


def reset_logo(db: Session) -> None:
    s = _get(db, "school_logo")
    if s:
        db.delete(s)


def logo_data_url(db: Session) -> str:
    """Logo als 'data:image/...;base64,...' für inline-Einbettung in HTML/PDF."""
    data, mime = get_logo_bytes(db)
    if not data:
        return ""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
