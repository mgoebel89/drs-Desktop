"""Geteilte Jinja-Templates-Instanz. Stellt school_name() global zur Verfügung
und injiziert den aktuellen User per Context-Processor in jedes Template,
damit die Navigationsleiste in base.html immer korrekt erscheint."""
from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.branding import get_school_name
from app.config import settings
from app.db import SessionLocal
from app.models import User, UserSession
from app.services.feature_flags import is_ai_enabled

BASE_DIR = Path(__file__).resolve().parent


def _school_name() -> str:
    db = SessionLocal()
    try:
        return get_school_name(db)
    finally:
        db.close()


def _inject_user(request: Request) -> dict:
    """Liest die Session aus dem Cookie und liefert den User für base.html.
    Robust gegen fehlende Cookies / abgelaufene Sessions — gibt dann None."""
    sid = request.cookies.get(settings.session_cookie_name)
    if not sid:
        return {"user": None}
    db = SessionLocal()
    try:
        sess = db.get(UserSession, sid)
        if not sess or sess.expires_at < datetime.utcnow():
            return {"user": None}
        user = db.get(User, sess.user_id)
        if not user or not user.active:
            return {"user": None}
        # Detach from session damit das Template-Render nicht in Session-Klemmen kommt
        db.expunge(user)
        return {"user": user}
    except Exception:
        return {"user": None}
    finally:
        db.close()


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"),
    context_processors=[_inject_user],
)
templates.env.globals["school_name"] = _school_name


def _ai_enabled() -> bool:
    db = SessionLocal()
    try:
        return is_ai_enabled(db)
    finally:
        db.close()


templates.env.globals["ai_enabled"] = _ai_enabled
