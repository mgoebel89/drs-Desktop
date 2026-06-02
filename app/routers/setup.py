"""First-Run-Setup: solange noch kein Nutzer in der DB ist, kann hier
über das Browser-Formular der erste Admin angelegt werden."""
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, create_session, set_session_cookie
from app.crypto import hash_password
from app.db import get_db
from app.models import User
from app.templating import templates

router = APIRouter()


def has_any_user(db: Session) -> bool:
    return db.query(User.id).first() is not None


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    if has_any_user(db):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup")
def setup_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
    password2: str = Form(...),
):
    if has_any_user(db):
        # Schon initialisiert — keine zweite Anlage erlauben
        return RedirectResponse("/login", status_code=303)

    username = username.strip().lower()
    err = None
    if not username or len(username) > 64 or not username.replace("_", "").replace("-", "").isalnum():
        err = "Benutzername: Buchstaben/Zahlen/_/- erlaubt, max. 64 Zeichen."
    elif password != password2:
        err = "Passwörter stimmen nicht überein."
    elif len(password) < 10:
        err = "Passwort muss mindestens 10 Zeichen haben."

    if err:
        return templates.TemplateResponse(request, "setup.html", {"error": err}, status_code=400)

    admin = User(
        username=username,
        full_name=full_name.strip(),
        role="admin",
        password_hash=hash_password(password),
        must_change_pw=False,
        active=True,
    )
    db.add(admin)
    db.flush()
    audit(db, "first_run_setup", actor=admin, target=username, request=request)

    # Auto-Login: Session anlegen + Cookie setzen
    sess = create_session(db, admin, request)
    db.commit()
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, sess.id)
    return resp
