from typing import Annotated
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth import attempt_login, create_session, set_session_cookie, clear_session_cookie, get_current_user
from app.models import UserSession
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    from app.models import User
    if db.query(User.id).first() is None:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    user, err = attempt_login(db, username.strip(), password, request)
    if err:
        return templates.TemplateResponse(request, "login.html", {"error": err}, status_code=400)
    sess = create_session(db, user, request)
    db.commit()
    target = "/change-password" if user.must_change_pw else "/"
    resp = RedirectResponse(url=target, status_code=303)
    set_session_cookie(resp, sess.id)
    return resp


@router.post("/logout")
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    sid = request.cookies.get("drs_session")
    if sid:
        sess = db.get(UserSession, sid)
        if sess:
            db.delete(sess)
            db.commit()
    resp = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(resp)
    return resp


@router.get("/change-password", response_class=HTMLResponse)
def change_pw_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "change_password.html",
                                      {"user": user, "error": None, "forced": user.must_change_pw})


@router.post("/change-password")
def change_pw_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current: str = Form(...),
    new1: str = Form(...),
    new2: str = Form(...),
):
    from app.crypto import verify_password, hash_password
    from app.auth import audit

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if new1 != new2:
        return templates.TemplateResponse(request, "change_password.html",
                                          {"user": user, "error": "Neue Passwörter stimmen nicht überein.",
                                           "forced": user.must_change_pw}, status_code=400)
    if len(new1) < 10:
        return templates.TemplateResponse(request, "change_password.html",
                                          {"user": user, "error": "Mindestens 10 Zeichen.",
                                           "forced": user.must_change_pw}, status_code=400)
    if not verify_password(current, user.password_hash):
        return templates.TemplateResponse(request, "change_password.html",
                                          {"user": user, "error": "Aktuelles Passwort falsch.",
                                           "forced": user.must_change_pw}, status_code=400)

    user.password_hash = hash_password(new1)
    user.must_change_pw = False
    audit(db, "password_changed", actor=user, target=user.username, request=request)
    db.commit()
    return RedirectResponse("/", status_code=303)
