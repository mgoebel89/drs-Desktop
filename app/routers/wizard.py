"""Planungs-Wizard — 5-stufiger Flow.

Schritte:
  1  Kontext           Klasse, Lernfeld, LS auswählen oder neu anlegen
  2  Ziele & Inhalte   Lernziele, Vorwissen
  3  Fobizz-Prompt     generierter Kontext-Prompt zum Kopieren
  4  Fobizz-Output     Markdown-Output einfügen, in Vault speichern
  5  Materialien       Upload + Vorschau
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import LearningSituation, User
from app.services import obsidian_writer, smb_client, wizard_helpers
from app.templating import templates

router = APIRouter()


def _get_ls(db: Session, user: User, ls_id: int) -> LearningSituation:
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    return ls


# ── Einstieg ──────────────────────────────────────────────────────────────
@router.get("/wizard", response_class=HTMLResponse)
def wizard_start(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    existing = (
        db.query(LearningSituation)
        .filter(LearningSituation.user_id == user.id)
        .order_by(LearningSituation.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "wizard/start.html", {
        "items": existing,
        "smb_configured": bool(user.smb_creds_enc),
    })


# ── Schritt 1: Kontext / LS anlegen ───────────────────────────────────────
@router.post("/wizard/new")
def wizard_new(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(...),
    klassen_key: str = Form(""),
    lernfeld: str = Form(""),
):
    display_name = display_name.strip()[:200]
    if not display_name:
        raise HTTPException(400, "Bezeichnung fehlt")
    slug = wizard_helpers.make_slug(display_name)

    # Slug eindeutig pro User: Suffix anhängen falls Kollision
    base_slug = slug
    n = 2
    while db.query(LearningSituation.id).filter(
        LearningSituation.user_id == user.id, LearningSituation.slug == slug,
    ).first():
        slug = f"{base_slug}-{n}"
        n += 1

    ls = LearningSituation(
        user_id=user.id,
        slug=slug,
        display_name=display_name,
        klassen_key=klassen_key.strip(),
        lernfeld=lernfeld.strip(),
    )
    db.add(ls)
    db.flush()  # ID fixieren für folder_name
    ls.smb_folder_name = wizard_helpers.folder_name(ls.id, ls.slug)
    ls.obsidian_note_path = obsidian_writer.note_filename(ls)
    audit(db, "ls_created", actor=user, target=str(ls.id), detail=display_name, request=request)
    db.commit()

    # SMB-Ordner anlegen (best-effort)
    cfg = smb_client.load_config(user)
    if cfg:
        try:
            base = smb_client.material_subpath(cfg, ls.smb_folder_name)
            smb_client.ensure_folder(user, base)
        except Exception:
            pass  # Nutzer kriegt den Fehler später in der Detail-Ansicht
    return RedirectResponse(f"/wizard/{ls.id}/step/2", status_code=303)


@router.get("/wizard/{ls_id}/step/{n}", response_class=HTMLResponse)
def wizard_step(
    request: Request,
    ls_id: int,
    n: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if n < 1 or n > 5:
        raise HTTPException(404)
    ls = _get_ls(db, user, ls_id)
    ctx = {"ls": ls, "step": n, "total": 5}

    if n == 1:
        return templates.TemplateResponse(request, "wizard/step1_kontext.html", ctx)
    if n == 2:
        return templates.TemplateResponse(request, "wizard/step2_ziele.html", ctx)
    if n == 3:
        # Prompt frisch bauen, in DB cachen
        prompt = wizard_helpers.build_fobizz_prompt(ls)
        ls.last_fobizz_prompt = prompt
        db.commit()
        ctx["prompt"] = prompt
        return templates.TemplateResponse(request, "wizard/step3_prompt.html", ctx)
    if n == 4:
        ctx["output"] = ls.last_fobizz_output
        return templates.TemplateResponse(request, "wizard/step4_output.html", ctx)
    if n == 5:
        cfg = smb_client.load_config(user)
        files: list[dict] = []
        smb_error = ""
        if cfg:
            base = smb_client.material_subpath(cfg, ls.smb_folder_name)
            try:
                files = smb_client.list_folder(user, base)
            except Exception as e:
                smb_error = str(e)
        ctx["files"] = files
        ctx["smb_error"] = smb_error
        ctx["smb_configured"] = bool(cfg)
        return templates.TemplateResponse(request, "wizard/step5_material.html", ctx)


# ── POST-Handler pro Schritt ──────────────────────────────────────────────
@router.post("/wizard/{ls_id}/step/1")
def wizard_save_1(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(...),
    klassen_key: str = Form(""),
    lernfeld: str = Form(""),
):
    ls = _get_ls(db, user, ls_id)
    ls.display_name = display_name.strip()[:200] or ls.display_name
    ls.klassen_key = klassen_key.strip()
    ls.lernfeld = lernfeld.strip()
    db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/step/2", status_code=303)


@router.post("/wizard/{ls_id}/step/2")
def wizard_save_2(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    lernziele: str = Form(""),
    vorwissen: str = Form(""),
):
    ls = _get_ls(db, user, ls_id)
    ls.lernziele = lernziele.strip()
    ls.vorwissen = vorwissen.strip()
    db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/step/3", status_code=303)


@router.post("/wizard/{ls_id}/step/4")
def wizard_save_4(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    fobizz_output: str = Form(""),
):
    ls = _get_ls(db, user, ls_id)
    ls.last_fobizz_output = fobizz_output

    # Materialliste für Vault-Notiz holen (best-effort)
    cfg = smb_client.load_config(user)
    material_files: list[str] = []
    if cfg:
        try:
            entries = smb_client.list_folder(
                user, smb_client.material_subpath(cfg, ls.smb_folder_name))
            material_files = [e["name"] for e in entries if not e["is_dir"]]
        except Exception:
            pass

    md = obsidian_writer.build_markdown(
        ls=ls,
        theme=ls.display_name,
        lernziele=ls.lernziele,
        fobizz_output=fobizz_output,
        material_files=material_files,
    )
    if cfg:
        try:
            obsidian_writer.write_note(user, ls, md)
        except Exception as e:
            audit(db, "ls_vault_write_failed", actor=user, target=str(ls.id),
                  detail=str(e), request=request)

    audit(db, "wizard_output_saved", actor=user, target=str(ls.id), request=request)
    db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/step/5", status_code=303)


@router.post("/wizard/{ls_id}/step/5")
async def wizard_save_5(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    files: list[UploadFile] = File(default=[]),
):
    ls = _get_ls(db, user, ls_id)
    cfg = smb_client.load_config(user)
    if cfg and files:
        base = smb_client.material_subpath(cfg, ls.smb_folder_name)
        smb_client.ensure_folder(user, base)
        for f in files:
            name = (f.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if not name or name.startswith("."):
                continue
            data = await f.read()
            smb_client.write_file(user, f"{base}/{name}", data)
        audit(db, "wizard_files_uploaded", actor=user, target=str(ls.id),
              detail=f"{len(files)} Datei(en)", request=request)
        db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/done", status_code=303)


@router.get("/wizard/{ls_id}/done", response_class=HTMLResponse)
def wizard_done(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = _get_ls(db, user, ls_id)
    return templates.TemplateResponse(request, "wizard/done.html", {"ls": ls})
