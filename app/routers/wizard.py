"""Planungs-Wizard v2 — 4-stufiger Flow auf Basis der Inhalts-MD.

Schritte:
  1  LS & Inhalts-MD  LS auswählen, Validierung der Pflichtsektionen,
                      optional Vorlage in den Vault schreiben.
  2  Material-Typ      Karten-Grid, Extras-Textfeld.
  3  Prompt            Tabs Fobizz + Claude.
  4  Output            Markdown einfügen, als WIZARD-BLOCK an MD anhängen,
                      optional als Worksheet anlegen.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import LearningSituation, User, Worksheet, WorksheetRevision
from app.services import material_prompts, obsidian_writer, smb_client, wizard_helpers
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


# ── LS anlegen ────────────────────────────────────────────────────────────
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

    base_slug = slug
    n = 2
    while db.query(LearningSituation.id).filter(
        LearningSituation.user_id == user.id, LearningSituation.slug == slug,
    ).first():
        slug = f"{base_slug}-{n}"
        n += 1

    ls = LearningSituation(
        user_id=user.id, slug=slug, display_name=display_name,
        klassen_key=klassen_key.strip(), lernfeld=lernfeld.strip(),
    )
    db.add(ls)
    db.flush()
    ls.smb_folder_name = wizard_helpers.folder_name(ls.id, ls.slug)
    ls.obsidian_note_path = obsidian_writer.note_filename(ls)
    audit(db, "ls_created", actor=user, target=str(ls.id), detail=display_name, request=request)
    db.commit()

    cfg = smb_client.load_config(user)
    if cfg:
        try:
            smb_client.ensure_folder(user, smb_client.material_subpath(cfg, ls.smb_folder_name))
        except Exception:
            pass
    return RedirectResponse(f"/wizard/{ls.id}/step/1", status_code=303)


# ── Vorlage in den Vault schreiben ───────────────────────────────────────
@router.post("/wizard/{ls_id}/template")
def wizard_create_template(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = _get_ls(db, user, ls_id)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    md = obsidian_writer.build_template_md(ls)
    obsidian_writer.write_note(user, ls, md)
    ls.content_md_present = True
    audit(db, "wizard_template_created", actor=user, target=str(ls.id), request=request)
    db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/step/1?vorlage=1", status_code=303)


# ── Schritte (GET) ────────────────────────────────────────────────────────
@router.get("/wizard/{ls_id}/step/{n}", response_class=HTMLResponse)
def wizard_step(
    request: Request,
    ls_id: int, n: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if n < 1 or n > 4:
        raise HTTPException(404)
    ls = _get_ls(db, user, ls_id)
    cfg = smb_client.load_config(user)
    ctx = {"ls": ls, "step": n, "total": 4, "smb_configured": bool(cfg)}

    if n == 1:
        md_present = False
        missing: list[str] = []
        md_body = ""
        smb_error = ""
        if cfg:
            try:
                raw = obsidian_writer.read_note(user, ls)
                md_present = bool(raw.strip())
                if md_present:
                    missing = obsidian_writer.missing_pflicht(raw)
                    md_body = obsidian_writer.content_md_body(raw)
            except Exception as e:
                smb_error = str(e)
        # Cache aktualisieren
        if ls.content_md_present != md_present:
            ls.content_md_present = md_present
            db.commit()
        ctx.update({
            "md_present": md_present,
            "missing": missing,
            "md_body": md_body,
            "smb_error": smb_error,
            "vorlage_flash": request.query_params.get("vorlage") == "1",
        })
        return templates.TemplateResponse(request, "wizard/step1_md.html", ctx)

    if n == 2:
        ctx.update({
            "catalog": material_prompts.CATALOG,
            "selected": ls.last_material_type,
            "extras": ls.last_extras,
        })
        return templates.TemplateResponse(request, "wizard/step2_typ.html", ctx)

    if n == 3:
        # Inhalts-MD laden, Prompts bauen
        md_body = ""
        if cfg:
            try:
                raw = obsidian_writer.read_note(user, ls)
                md_body = obsidian_writer.content_md_body(raw)
            except Exception:
                pass
        if not ls.last_material_type:
            return RedirectResponse(f"/wizard/{ls_id}/step/2", status_code=303)
        try:
            prompts = material_prompts.build_prompts(
                ls=ls,
                content_md_body=md_body,
                material_type_key=ls.last_material_type,
                extras=ls.last_extras,
            )
        except ValueError:
            return RedirectResponse(f"/wizard/{ls_id}/step/2", status_code=303)
        ls.last_fobizz_prompt = prompts["fobizz"]
        db.commit()
        ctx.update({
            "material_type": prompts["material_type"],
            "fobizz_prompt": prompts["fobizz"],
            "claude_prompt": prompts["claude"],
        })
        return templates.TemplateResponse(request, "wizard/step3_prompt.html", ctx)

    if n == 4:
        mt = material_prompts.get(ls.last_material_type) if ls.last_material_type else None
        ctx.update({
            "output": ls.last_fobizz_output,
            "material_type": mt,
        })
        return templates.TemplateResponse(request, "wizard/step4_output.html", ctx)


# ── Schritte (POST) ───────────────────────────────────────────────────────
@router.post("/wizard/{ls_id}/step/2")
def wizard_save_2(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    material_type: str = Form(...),
    extras: str = Form(""),
):
    ls = _get_ls(db, user, ls_id)
    if not material_prompts.get(material_type):
        raise HTTPException(400, "Unbekannter Material-Typ")
    ls.last_material_type = material_type
    ls.last_extras = extras.strip()
    db.commit()
    return RedirectResponse(f"/wizard/{ls_id}/step/3", status_code=303)


@router.post("/wizard/{ls_id}/step/4")
def wizard_save_4(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    output: str = Form(""),
    as_worksheet: str = Form(""),
):
    ls = _get_ls(db, user, ls_id)
    ls.last_fobizz_output = output

    mt = material_prompts.get(ls.last_material_type)
    if not mt:
        raise HTTPException(400, "Kein Material-Typ ausgewählt")

    # 1) MD-Block in die Vault-Notiz anhängen
    cfg = smb_client.load_config(user)
    if cfg and output.strip():
        try:
            obsidian_writer.append_output_block(user, ls, mt.label, output)
        except Exception as e:
            audit(db, "wizard_vault_append_failed", actor=user,
                  target=str(ls.id), detail=str(e), request=request)

    audit(db, "wizard_generated", actor=user, target=str(ls.id),
          detail=mt.key, request=request)

    new_ws_id: int | None = None
    if as_worksheet and output.strip():
        ws = Worksheet(
            owner_user_id=user.id,
            title=f"{ls.display_name} · {mt.label}",
            learning_situation_id=ls.id,
        )
        db.add(ws)
        db.flush()
        rev = WorksheetRevision(
            worksheet_id=ws.id,
            created_by_user_id=user.id,
            comment=f"Aus Wizard ({mt.label})",
            meta_json=json.dumps({"source": "wizard", "material_type": mt.key}),
            aufgaben_json="[]",
            markdown_source=output,
        )
        db.add(rev)
        audit(db, "worksheet_created_from_wizard", actor=user,
              target=str(ws.id), detail=mt.label, request=request)
        new_ws_id = ws.id

    db.commit()

    if new_ws_id:
        return RedirectResponse(f"/worksheets/{new_ws_id}", status_code=303)
    return RedirectResponse(f"/wizard/{ls_id}/done", status_code=303)


@router.get("/wizard/{ls_id}/done", response_class=HTMLResponse)
def wizard_done(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = _get_ls(db, user, ls_id)
    mt = material_prompts.get(ls.last_material_type) if ls.last_material_type else None
    return templates.TemplateResponse(request, "wizard/done.html", {
        "ls": ls, "material_type": mt,
    })
