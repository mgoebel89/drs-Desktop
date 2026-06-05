"""Profil: eigenes PW + eigene API-/WebUntis-Credentials + iCal-Kalender."""
import json
import re
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.crypto import decrypt_secret, encrypt_secret, mask_key
from app.db import get_db
from app.models import IcalCalendar, User
from app.services import smb_client
from app.services.ical_client import test_url as ical_test_url
from app.services.webuntis_client import test_connection as untis_test
from app.templating import templates

router = APIRouter()


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 40:
        return url[:20] + "…"
    return url[:30] + "…" + url[-10:]


def _view_ctx(user: User, db: Session, flash: str | None = None, flash_kind: str = "ok") -> dict:
    anth = decrypt_secret(user.anthropic_key_enc) if user.anthropic_key_enc else ""
    untis_raw = decrypt_secret(user.untis_creds_enc) if user.untis_creds_enc else ""
    untis = json.loads(untis_raw) if untis_raw else {}
    smb_cfg = smb_client.load_config(user)
    smb_view = {
        "host": smb_cfg.host if smb_cfg else "",
        "share": smb_cfg.share if smb_cfg else "",
        "username": smb_cfg.username if smb_cfg else "",
        "vault_subpath": smb_cfg.vault_subpath if smb_cfg else "/vault",
        "material_subpath": smb_cfg.material_subpath if smb_cfg else "/lernsituationen",
        "pw_set": bool(smb_cfg and smb_cfg.password),
    }
    cals = db.query(IcalCalendar).filter(IcalCalendar.user_id == user.id)\
        .order_by(IcalCalendar.id).all()
    cal_views = []
    for c in cals:
        try:
            url = decrypt_secret(c.url_enc)
        except Exception:
            url = ""
        cal_views.append({
            "id": c.id, "label": c.label, "color": c.color,
            "url_masked": _mask_url(url),
            "enabled": c.enabled,
            "last_error": c.last_error or "",
        })
    return {
        "user": user,
        "anthropic_masked": mask_key(anth) if anth else "",
        "anthropic_set": bool(anth),
        "untis": untis,
        "untis_pw_set": bool(untis.get("password")),
        "smb": smb_view,
        "ical_calendars": cal_views,
        "flash": flash,
        "flash_kind": flash_kind,
    }


@router.get("/profile", response_class=HTMLResponse)
def profile_view(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return templates.TemplateResponse(request, "profile.html", _view_ctx(user, db))


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


@router.post("/profile/smb")
def profile_smb(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    host: str = Form(""),
    share: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    vault_subpath: str = Form("/vault"),
    material_subpath: str = Form("/lernsituationen"),
    clear: str = Form(""),
):
    if clear:
        smb_client.clear_config(user)
        audit(db, "smb_creds_cleared", actor=user, request=request)
    else:
        existing = smb_client.load_config(user)
        cfg = smb_client.SmbConfig(
            host=host.strip() or (existing.host if existing else ""),
            share=share.strip() or (existing.share if existing else ""),
            username=username.strip() or (existing.username if existing else ""),
            password=password or (existing.password if existing else ""),
            vault_subpath=vault_subpath.strip() or "/vault",
            material_subpath=material_subpath.strip() or "/lernsituationen",
        )
        if not all([cfg.host, cfg.share, cfg.username, cfg.password]):
            return RedirectResponse("/profile?smb_err=1", status_code=303)
        smb_client.save_config(user, cfg)
        audit(db, "smb_creds_set", actor=user, request=request)
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/smb/test")
def profile_smb_test(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ok, msg = smb_client.test_connection(user)
    audit(db, "smb_test", actor=user,
          detail=("ok" if ok else "fail") + f": {msg}", request=request)
    db.commit()
    return JSONResponse({"ok": ok, "message": msg})


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


# ── iCal-Kalender ─────────────────────────────────────────────────────────
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@router.post("/profile/ical/add")
def ical_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    label: str = Form(...),
    color: str = Form("#7B61FF"),
    url: str = Form(...),
):
    label = label.strip()[:80] or "Kalender"
    color = color.strip()
    if not _COLOR_RE.match(color):
        color = "#7B61FF"
    url = url.strip()
    if not url:
        raise HTTPException(400, "URL fehlt.")
    cal = IcalCalendar(
        user_id=user.id, label=label, color=color,
        url_enc=encrypt_secret(url), enabled=True,
    )
    db.add(cal)
    audit(db, "ical_added", actor=user, detail=label, request=request)
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/ical/{cal_id}/delete")
def ical_delete(
    request: Request,
    cal_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    cal = db.get(IcalCalendar, cal_id)
    if not cal or cal.user_id != user.id:
        raise HTTPException(404)
    label = cal.label
    db.delete(cal)
    audit(db, "ical_deleted", actor=user, detail=label, request=request)
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/ical/{cal_id}/toggle")
def ical_toggle(
    request: Request,
    cal_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    cal = db.get(IcalCalendar, cal_id)
    if not cal or cal.user_id != user.id:
        raise HTTPException(404)
    cal.enabled = not cal.enabled
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/ical/{cal_id}/test")
def ical_test(
    cal_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    cal = db.get(IcalCalendar, cal_id)
    if not cal or cal.user_id != user.id:
        raise HTTPException(404)
    try:
        url = decrypt_secret(cal.url_enc)
    except Exception:
        return JSONResponse({"ok": False, "message": "URL kann nicht entschlüsselt werden."})
    ok, msg = ical_test_url(url)
    cal.last_error = "" if ok else msg
    db.commit()
    return JSONResponse({"ok": ok, "message": msg})
