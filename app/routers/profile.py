"""Profil: eigenes PW + eigene API-/WebUntis-Credentials."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.crypto import decrypt_secret, encrypt_secret, mask_key
from app.db import get_db
from app.models import User
from app.services.webuntis_client import test_connection as untis_test
from app.templating import templates

router = APIRouter()


def _view_ctx(user: User, flash: str | None = None, flash_kind: str = "ok") -> dict:
    anth = decrypt_secret(user.anthropic_key_enc) if user.anthropic_key_enc else ""
    untis_raw = decrypt_secret(user.untis_creds_enc) if user.untis_creds_enc else ""
    untis = json.loads(untis_raw) if untis_raw else {}
    return {
        "user": user,
        "anthropic_masked": mask_key(anth) if anth else "",
        "anthropic_set": bool(anth),
        "untis": untis,
        "untis_pw_set": bool(untis.get("password")),
        "flash": flash,
        "flash_kind": flash_kind,
    }


@router.get("/profile", response_class=HTMLResponse)
def profile_view(request: Request, user: Annotated[User, Depends(require_user)]):
    return templates.TemplateResponse(request, "profile.html", _view_ctx(user))


@router.post("/profile/anthropic")
def profile_anthropic(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    api_key: str = Form(""),
    clear: str = Form(""),
):
    if clear:
        user.anthropic_key_enc = None
        audit(db, "anthropic_key_cleared", actor=user, request=request)
    elif api_key.strip():
        user.anthropic_key_enc = encrypt_secret(api_key.strip())
        audit(db, "anthropic_key_set", actor=user, request=request)
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/untis")
def profile_untis(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    server: str = Form(""),
    school: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    clear: str = Form(""),
):
    if clear:
        user.untis_creds_enc = None
        audit(db, "untis_creds_cleared", actor=user, request=request)
    else:
        # vorhandenes PW behalten, wenn Feld leer
        existing_raw = decrypt_secret(user.untis_creds_enc) if user.untis_creds_enc else ""
        existing = json.loads(existing_raw) if existing_raw else {}
        creds = {
            "server": server.strip() or existing.get("server", ""),
            "school": school.strip() or existing.get("school", ""),
            "username": username.strip() or existing.get("username", ""),
            "password": password or existing.get("password", ""),
        }
        if not all([creds["server"], creds["school"], creds["username"], creds["password"]]):
            return RedirectResponse("/profile?untis_err=1", status_code=303)
        user.untis_creds_enc = encrypt_secret(json.dumps(creds))
        audit(db, "untis_creds_set", actor=user, request=request)
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/untis/test")
def profile_untis_test(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ok, msg = untis_test(user)
    audit(db, "untis_test", actor=user,
          detail=("ok" if ok else "fail") + f": {msg}", request=request)
    db.commit()
    return JSONResponse({"ok": ok, "message": msg})
