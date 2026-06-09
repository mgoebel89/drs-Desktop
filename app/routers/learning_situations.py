"""CRUD und Detail-Ansicht für Lernsituationen."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.auth import audit, require_user
from app.db import get_db
from app.models import LearningSituation, LsArbeitsblatt, LsAufgabe, User, Worksheet
from app.services import (aufgabe_sync, ls_sync, obsidian_writer, smb_client,
                          wizard_helpers, worksheet_from_ls)
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


# ─────────────────────── Schema v3: Sync-Endpoints ─────────────────────


_SECTION_FIELDS = {
    "lernsituation": "lernsituation_md",
    "kompetenzen": "kompetenzen_md",
    "uebergreifende_aspekte": "uebergreifende_aspekte_md",
    "lehrer_vorwissen": "lehrer_vorwissen_md",
    "leistungsfeststellung": "leistungsfeststellung_md",
}


def _require_v3(db: Session, user: User, ls_id: int) -> LearningSituation:
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if (ls.schema_version or 2) < 3:
        raise HTTPException(409, "Lernsituation ist noch Schema v2 — bitte migrieren")
    return ls


@router.get("/ls/{ls_id}/sync/status")
def ls_sync_status(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Liefert den Konflikt-Report (leeres `sections`-Array = in sync)."""
    ls = _require_v3(db, user, ls_id)
    rep = ls_sync.detect_conflict(db, user, ls)
    return JSONResponse({
        "ok": True,
        "in_sync": not rep.has_conflict,
        "file_hash": rep.file_hash,
        "db_hash": rep.db_hash,
        "sections": [
            {"key": s.key, "label": s.label,
             "app_value": s.app_value, "vault_value": s.vault_value}
            for s in rep.sections
        ],
    })


@router.post("/ls/{ls_id}/sync/pull")
def ls_sync_pull(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Vault → DB. Überschreibt DB-Sektionen mit den Werten aus der MD."""
    ls = _require_v3(db, user, ls_id)
    changed = ls_sync.load_from_vault(db, user, ls)
    audit(db, "ls_sync_pull", actor=user, target=str(ls.id),
          detail="changed" if changed else "noop", request=request)
    db.commit()
    return JSONResponse({"ok": True, "applied": changed})


@router.post("/ls/{ls_id}/sync/push")
def ls_sync_push(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """DB → Vault. Baut MD aus dem aktuellen DB-Stand und schreibt sie."""
    ls = _require_v3(db, user, ls_id)
    try:
        ls_sync.save_to_vault(user, ls, db)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    audit(db, "ls_sync_push", actor=user, target=str(ls.id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/section/{section_key}")
def ls_section_save(
    request: Request,
    ls_id: int,
    section_key: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Inline-Edit pro Sektion. Erwartet `{value, expected_hash?}`.

    Wenn `expected_hash` mitgesendet wird, prüft die App, dass die
    Datei zwischenzeitlich nicht extern geändert wurde — bei Mismatch
    409 Conflict (Client sollte auf den Konflikt-Banner umschalten)."""
    ls = _require_v3(db, user, ls_id)
    value = (body.get("value") or "")
    expected = body.get("expected_hash")
    if expected and (ls.content_hash or "") != expected:
        rep = ls_sync.detect_conflict(db, user, ls)
        if rep.has_conflict:
            raise HTTPException(409, "Konflikt mit externer Änderung")

    if section_key in _SECTION_FIELDS:
        setattr(ls, _SECTION_FIELDS[section_key], value[:200000])
    elif section_key.startswith("arbeitsblatt:"):
        try:
            pos = int(section_key.split(":", 1)[1])
        except ValueError:
            raise HTTPException(400, "Ungültiger Sektions-Key")
        ab = db.query(LsArbeitsblatt).filter(
            LsArbeitsblatt.learning_situation_id == ls.id,
            LsArbeitsblatt.position == pos,
        ).first()
        if not ab:
            ab = LsArbeitsblatt(
                learning_situation_id=ls.id, position=pos,
                title=f"Arbeitsblatt {pos}",
            )
            db.add(ab)
            db.flush()
        # Sub-Felder via field-Suffix: arbeitsblatt:N:phase|hinweis|content
        sub = (body.get("field") or "content").strip()
        if sub == "phase":
            ab.phase = value[:255]
        elif sub == "hinweis":
            ab.bearbeitungshinweis_md = value[:10000]
        elif sub == "title":
            ab.title = value[:255]
        else:
            ab.content_md = value[:200000]
    else:
        raise HTTPException(400, "Unbekannte Sektion")

    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_section_saved", actor=user, target=str(ls.id),
          detail=section_key, request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/sync/resolve")
def ls_sync_resolve(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Konflikt auflösen. Body: `{choices: {section_key: 'app'|'vault'}}`.

    Für jeden Key mit 'vault' wird der Vault-Stand in die DB übernommen,
    danach wird die MD aus dem (jetzt vom Lehrer gemixten) DB-Stand neu
    geschrieben."""
    ls = _require_v3(db, user, ls_id)
    choices = body.get("choices") or {}
    if not isinstance(choices, dict):
        raise HTTPException(400, "Ungültige Auswahl")
    ls_sync.apply_resolution(db, user, ls, {k: str(v) for k, v in choices.items()})
    audit(db, "ls_sync_resolved", actor=user, target=str(ls.id),
          detail=f"{sum(1 for v in choices.values() if v == 'vault')} sektionen geholt",
          request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


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
