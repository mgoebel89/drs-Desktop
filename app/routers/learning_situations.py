"""CRUD und Detail-Ansicht für Lernsituationen."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import LearningSituation, User
from app.services import obsidian_writer, smb_client, wizard_helpers
from app.templating import templates

router = APIRouter()


@router.get("/learning-situations", response_class=HTMLResponse)
def ls_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = (
        db.query(LearningSituation)
        .filter(LearningSituation.user_id == user.id)
        .order_by(LearningSituation.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "learning_situations/list.html", {
        "items": rows,
        "smb_configured": bool(user.smb_creds_enc),
    })


@router.get("/ls/{ls_id}", response_class=HTMLResponse)
def ls_detail(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    files: list[dict] = []
    smb_error = ""
    if cfg:
        subpath = smb_client.material_subpath(cfg, ls.smb_folder_name)
        try:
            files = smb_client.list_folder(user, subpath)
        except Exception as e:
            smb_error = str(e)
    has_note = bool(obsidian_writer.read_note(user, ls)) if cfg else False
    return templates.TemplateResponse(request, "learning_situations/detail.html", {
        "ls": ls,
        "files": files,
        "smb_configured": bool(cfg),
        "smb_error": smb_error,
        "has_note": has_note,
    })


@router.post("/ls/{ls_id}/rename")
def ls_rename(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(...),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    display_name = display_name.strip()[:200]
    if not display_name:
        raise HTTPException(400, "Name darf nicht leer sein")
    ls.display_name = display_name  # slug + folder bleiben stabil
    audit(db, "ls_renamed", actor=user, target=str(ls.id), detail=display_name, request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)


@router.post("/ls/{ls_id}/upload")
async def ls_upload(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    files: list[UploadFile] = File(...),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    base = smb_client.material_subpath(cfg, ls.smb_folder_name)
    smb_client.ensure_folder(user, base)

    saved = []
    for f in files:
        name = (f.filename or "datei").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not name or name.startswith("."):
            continue
        data = await f.read()
        smb_client.write_file(user, f"{base}/{name}", data)
        saved.append(name)
    audit(db, "ls_upload", actor=user, target=str(ls.id),
          detail=", ".join(saved), request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)


@router.post("/ls/{ls_id}/files/{filename}/delete")
def ls_delete_file(
    request: Request,
    ls_id: int,
    filename: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400)
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    subpath = smb_client.material_subpath(cfg, ls.smb_folder_name) + "/" + filename
    try:
        smb_client.delete_file(user, subpath)
    except Exception as e:
        raise HTTPException(502, f"SMB-Fehler: {e}")
    audit(db, "ls_file_deleted", actor=user, target=str(ls.id), detail=filename, request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)
