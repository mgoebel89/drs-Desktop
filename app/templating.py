"""Geteilte Jinja-Templates-Instanz. Stellt school_name() global zur Verfügung."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.branding import get_school_name
from app.db import SessionLocal

BASE_DIR = Path(__file__).resolve().parent


def _school_name() -> str:
    db = SessionLocal()
    try:
        return get_school_name(db)
    finally:
        db.close()


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["school_name"] = _school_name
