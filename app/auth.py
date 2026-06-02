"""Auth-Dependencies und Session-Helpers."""
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserSession, AuditLog


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, user: User, request: Request) -> UserSession:
    sess = UserSession(
        id=_new_token(),
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=settings.session_max_age_days),
        user_agent=(request.headers.get("user-agent") or "")[:255],
        ip=(request.client.host if request.client else "")[:64],
    )
    db.add(sess)
    return sess


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_max_age_days * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # in Produktion via Caddy HTTPS terminiert; Cookie bleibt auf HTTP-Backend
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def audit(db: Session, action: str, *, actor: User | None = None, target: str = "",
          detail: str = "", request: Request | None = None) -> None:
    db.add(AuditLog(
        action=action,
        actor_user_id=(actor.id if actor else None),
        target=target,
        detail=detail,
        ip=(request.client.host if request and request.client else "")[:64],
    ))


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    sid = request.cookies.get(settings.session_cookie_name)
    if not sid:
        return None
    sess = db.get(UserSession, sid)
    if not sess or sess.expires_at < datetime.utcnow():
        return None
    user = db.get(User, sess.user_id)
    if not user or not user.active:
        return None
    return user


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin-Rolle erforderlich")
    return user


# ── Login-Logik ────────────────────────────────────────────────────────────
def attempt_login(db: Session, username: str, password: str, request: Request) -> tuple[User | None, str | None]:
    """Liefert (user, error_msg). user nur bei Erfolg gesetzt."""
    from app.crypto import verify_password, needs_rehash, hash_password

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.active:
        audit(db, "login_fail", target=username, detail="unknown_or_inactive", request=request)
        db.commit()
        return None, "Benutzername oder Passwort falsch."

    if user.locked_until and user.locked_until > datetime.utcnow():
        mins = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        audit(db, "login_fail", actor=user, target=username, detail="locked", request=request)
        db.commit()
        return None, f"Konto gesperrt. Versuche es in {mins} Minuten erneut."

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.max_failed_attempts:
            user.locked_until = datetime.utcnow() + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
            audit(db, "login_lockout", actor=user, target=username, request=request)
        else:
            audit(db, "login_fail", actor=user, target=username,
                  detail=f"attempt {user.failed_attempts}", request=request)
        db.commit()
        return None, "Benutzername oder Passwort falsch."

    # Erfolg
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    audit(db, "login_ok", actor=user, target=username, request=request)
    return user, None
