"""Admin-Bereich: Nutzerverwaltung."""
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import audit, require_admin
from app.crypto import hash_password
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _temp_password() -> str:
    # gut lesbares Initial-PW: 4 Wörter aus einfacher Liste reicht für Init.
    alpha = "abcdefghjkmnpqrstuvwxyz"
    nums = "23456789"
    return (
        "".join(secrets.choice(alpha) for _ in range(4))
        + "-"
        + "".join(secrets.choice(alpha) for _ in range(4))
        + "-"
        + "".join(secrets.choice(nums) for _ in range(4))
    )


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "admin/users.html",
                                      {"user": admin, "users": users, "new_user": None, "error": None})


@router.post("/users/create")
def users_create(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("teacher"),
):
    username = username.strip().lower()
    if not username or len(username) > 64:
        raise HTTPException(400, "Benutzername ungültig")
    if role not in ("admin", "teacher"):
        role = "teacher"
    if db.query(User).filter(User.username == username).first():
        users = db.query(User).order_by(User.username).all()
        return templates.TemplateResponse(request, "admin/users.html",
                                          {"user": admin, "users": users, "new_user": None,
                                           "error": f"Benutzer '{username}' existiert bereits."},
                                          status_code=400)
    initial = _temp_password()
    u = User(username=username, full_name=full_name.strip(), role=role,
             password_hash=hash_password(initial), must_change_pw=True, active=True)
    db.add(u)
    audit(db, "user_created", actor=admin, target=username, detail=f"role={role}", request=request)
    db.commit()
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "admin/users.html",
                                      {"user": admin, "users": users,
                                       "new_user": {"username": username, "password": initial},
                                       "error": None})


@router.post("/users/{user_id}/reset")
def users_reset(
    request: Request,
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404)
    initial = _temp_password()
    u.password_hash = hash_password(initial)
    u.must_change_pw = True
    u.failed_attempts = 0
    u.locked_until = None
    audit(db, "user_password_reset", actor=admin, target=u.username, request=request)
    db.commit()
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "admin/users.html",
                                      {"user": admin, "users": users,
                                       "new_user": {"username": u.username, "password": initial},
                                       "error": None})


@router.post("/users/{user_id}/toggle")
def users_toggle_active(
    request: Request,
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404)
    if u.id == admin.id:
        raise HTTPException(400, "Eigenes Konto kann nicht deaktiviert werden.")
    u.active = not u.active
    audit(db, "user_active_toggle", actor=admin, target=u.username,
          detail=f"active={u.active}", request=request)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)
