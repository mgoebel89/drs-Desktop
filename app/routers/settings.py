"""Admin-Bereich: globale Einstellungen (Branding)."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import audit, require_admin
from app.branding import (
    get_logo_bytes, get_school_name, reset_logo, set_logo_bytes, set_school_name,
)
from app.db import get_db
from app.models import User
from app.templating import templates

router = APIRouter()

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/svg+xml", "image/webp"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


# Branding-Logo ist öffentlich (in WebUI-Nav und exportierten Arbeitsblättern eingebettet).
@router.get("/branding/logo")
def branding_logo(db: Annotated[Session, Depends(get_db)]):
    data, mime = get_logo_bytes(db)
    if not data:
        raise HTTPException(404)
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "no-cache"})


@router.get("/admin/settings", response_class=HTMLResponse)
def settings_view(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    return templates.TemplateResponse(request, "admin/settings.html",
                                      {"user": admin, "flash": None})


@router.post("/admin/settings/school-name")
def settings_school_name(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    school_name: str = Form(...),
):
    name = school_name.strip()
    if not name or len(name) > 200:
        raise HTTPException(400, "Schulname leer oder zu lang.")
    set_school_name(db, name)
    audit(db, "branding_school_name", actor=admin, detail=name, request=request)
    db.commit()
    return RedirectResponse("/admin/settings", status_code=303)


@router.post("/admin/settings/logo")
async def settings_logo_upload(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    logo: UploadFile = File(...),
):
    if logo.content_type not in _ALLOWED_MIME:
        raise HTTPException(400, f"Bildformat nicht unterstützt ({logo.content_type}).")
    data = await logo.read()
    if not data:
        raise HTTPException(400, "Leere Datei.")
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(400, f"Datei zu groß (max. {_MAX_LOGO_BYTES // 1024} KB).")
    set_logo_bytes(db, data, logo.content_type)
    audit(db, "branding_logo_set", actor=admin, detail=f"{logo.content_type} {len(data)}B", request=request)
    db.commit()
    return RedirectResponse("/admin/settings", status_code=303)


@router.post("/admin/settings/logo/reset")
def settings_logo_reset(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    reset_logo(db)
    audit(db, "branding_logo_reset", actor=admin, request=request)
    db.commit()
    return RedirectResponse("/admin/settings", status_code=303)
