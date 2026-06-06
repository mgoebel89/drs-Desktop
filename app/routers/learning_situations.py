"""CRUD und Detail-Ansicht für Lernsituationen."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.auth import audit, require_user
from app.db import get_db
from app.models import LearningSituation, User, Worksheet
from app.services import aufgabe_sync, obsidian_writer, smb_client, wizard_helpers, worksheet_from_ls
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

    aufgaben = []
    if cfg and has_note:
        try:
            aufgaben = aufgabe_sync.sync_from_md(db, user, ls)
            db.commit()
        except Exception:
            db.rollback()

    return templates.TemplateResponse(request, "learning_situations/detail.html", {
        "ls": ls,
        "files": files,
        "smb_configured": bool(cfg),
        "smb_error": smb_error,
        "has_note": has_note,
        "aufgaben": aufgaben,
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


@router.post("/ls/{ls_id}/worksheet")
def ls_create_worksheet(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    role: str = Form("student"),
    aufgabe_nummern: str = Form(""),
):
    """Erzeugt direkt aus der LS-MD ein Worksheet (ohne Wizard).
    role: 'student' oder 'teacher'.
    aufgabe_nummern: CSV von Nummern (optional) — wenn leer, alle Aufgaben."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if role not in ("student", "teacher"):
        raise HTTPException(400, "Ungültige Rolle")

    nummer_filter: list[int] | None = None
    if aufgabe_nummern.strip():
        try:
            nummer_filter = [int(n) for n in aufgabe_nummern.split(",") if n.strip()]
        except ValueError:
            raise HTTPException(400, "aufgabe_nummern muss eine Zahlenliste sein")

    try:
        ws = worksheet_from_ls.create_worksheet_from_ls(
            db, user, ls, role=role, nummer_filter=nummer_filter,  # type: ignore[arg-type]
        )
    except ValueError as e:
        # Z. B. keine MD, oder Schema v1
        return RedirectResponse(
            f"/ls/{ls_id}?ws_error={str(e).replace(' ', '+')}",
            status_code=303,
        )

    audit(db, "worksheet_from_ls", actor=user, target=str(ws.id),
          detail=f"role={role}, ls={ls_id}", request=request)
    db.commit()
    return RedirectResponse(f"/worksheets/{ws.id}", status_code=303)


@router.get("/ls/{ls_id}/delete", response_class=HTMLResponse)
def ls_delete_confirm(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)

    file_count = 0
    smb_error = ""
    has_note = False
    if cfg:
        try:
            file_count = smb_client.count_files(
                user, smb_client.material_subpath(cfg, ls.smb_folder_name))
        except Exception as e:
            smb_error = str(e)
        try:
            has_note = bool(obsidian_writer.read_note(user, ls))
        except Exception:
            pass

    linked_worksheets = db.scalars(
        select(Worksheet).where(Worksheet.learning_situation_id == ls.id)
    ).all()

    return templates.TemplateResponse(request, "learning_situations/confirm_delete.html", {
        "ls": ls,
        "file_count": file_count,
        "has_note": has_note,
        "smb_error": smb_error,
        "smb_configured": bool(cfg),
        "linked_worksheets": linked_worksheets,
    })


@router.post("/ls/{ls_id}/delete")
def ls_delete_exec(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    confirm: str = Form(""),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if confirm != "1":
        raise HTTPException(400, "Bestätigungs-Checkbox nicht gesetzt")

    display_name = ls.display_name
    folder = ls.smb_folder_name
    cfg = smb_client.load_config(user)

    smb_errors: list[str] = []
    deleted_files = 0
    if cfg:
        # 1) Material-Ordner rekursiv löschen
        try:
            deleted_files = smb_client.delete_folder_recursive(
                user, smb_client.material_subpath(cfg, ls.smb_folder_name))
        except Exception as e:
            smb_errors.append(f"Material-Ordner: {e}")
        # 2) Vault-MD löschen
        try:
            smb_client.delete_file(
                user, smb_client.vault_subpath(cfg, obsidian_writer.note_filename(ls)))
        except Exception as e:
            smb_errors.append(f"Vault-MD: {e}")

    # 3) DB löschen — FKs in worksheets/lesson_notes sind ON DELETE SET NULL
    db.delete(ls)
    audit(db, "ls_deleted", actor=user, target=str(ls_id),
          detail=f"{display_name} · {folder} · {deleted_files} Datei(en)"
                 + (f" · Fehler: {'; '.join(smb_errors)}" if smb_errors else ""),
          request=request)
    db.commit()
    return RedirectResponse("/learning-situations", status_code=303)


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
