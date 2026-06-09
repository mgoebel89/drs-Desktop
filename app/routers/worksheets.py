"""Konfigurationstool: Aufgabenblätter erstellen, speichern, exportieren."""
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.branding import get_school_name, logo_data_url
from app.db import get_db
from app.models import User, Worksheet, WorksheetRevision
from app.services.playwright_pdf import render_pdf
from app.templating import templates

router = APIRouter(prefix="/worksheets")


def _owned(db: Session, ws_id: int, user: User) -> Worksheet:
    ws = db.get(Worksheet, ws_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(404, "Aufgabenblatt nicht gefunden")
    return ws


def _latest_rev(db: Session, ws: Worksheet) -> WorksheetRevision | None:
    stmt = select(WorksheetRevision).where(WorksheetRevision.worksheet_id == ws.id)\
        .order_by(WorksheetRevision.id.desc()).limit(1)
    return db.execute(stmt).scalar_one_or_none()


# ── Liste ─────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def list_worksheets(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    stmt = select(Worksheet).where(Worksheet.owner_user_id == user.id)\
        .order_by(Worksheet.updated_at.desc())
    items = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(request, "worksheets/list.html",
                                      {"user": user, "items": items})


# ── Editor ────────────────────────────────────────────────────────────────
@router.get("/new", response_class=HTMLResponse)
def new_worksheet(request: Request, user: Annotated[User, Depends(require_user)]):
    return templates.TemplateResponse(request, "worksheets/editor.html",
                                      {"user": user, "ws_id": None,
                                       "title": "Neues Aufgabenblatt",
                                       "data_json": json.dumps({"meta": {}, "aufgaben": []})})


@router.get("/{ws_id}", response_class=HTMLResponse)
def edit_worksheet(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ws = _owned(db, ws_id, user)
    rev = _latest_rev(db, ws)
    payload = {
        "meta": json.loads(rev.meta_json) if rev else {},
        "aufgaben": json.loads(rev.aufgaben_json) if rev else [],
    }
    return templates.TemplateResponse(request, "worksheets/editor.html",
                                      {"user": user, "ws_id": ws.id,
                                       "title": ws.title,
                                       "data_json": json.dumps(payload)})


# ── Save (JSON) ───────────────────────────────────────────────────────────
@router.post("/save")
def save_worksheet(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    title = (body.get("title") or "Unbenanntes Aufgabenblatt").strip()[:200]
    meta = body.get("meta") or {}
    aufgaben = body.get("aufgaben") or []
    comment = (body.get("comment") or "").strip()[:255]
    ws_id = body.get("worksheet_id")

    if not isinstance(meta, dict) or not isinstance(aufgaben, list):
        raise HTTPException(400, "Ungültiges Format")

    if ws_id:
        ws = _owned(db, int(ws_id), user)
        ws.title = title
        ws.updated_at = datetime.utcnow()
    else:
        ws = Worksheet(owner_user_id=user.id, title=title)
        db.add(ws)
        db.flush()  # für ws.id

    rev = WorksheetRevision(
        worksheet_id=ws.id,
        created_by_user_id=user.id,
        comment=comment,
        meta_json=json.dumps(meta, ensure_ascii=False),
        aufgaben_json=json.dumps(aufgaben, ensure_ascii=False),
    )
    db.add(rev)
    audit(db, "worksheet_saved", actor=user, target=str(ws.id),
          detail=f"rev pending, aufgaben={len(aufgaben)}", request=request)
    db.commit()
    return JSONResponse({"worksheet_id": ws.id, "revision_id": rev.id, "title": ws.title})


# ── Revisionen ────────────────────────────────────────────────────────────
@router.get("/{ws_id}/revisions", response_class=HTMLResponse)
def revisions_list(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ws = _owned(db, ws_id, user)
    revs = ws.revisions
    return templates.TemplateResponse(request, "worksheets/revisions.html",
                                      {"user": user, "ws": ws, "revs": revs})


@router.post("/{ws_id}/revisions/{rev_id}/restore")
def revision_restore(
    ws_id: int,
    rev_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ws = _owned(db, ws_id, user)
    src = db.get(WorksheetRevision, rev_id)
    if not src or src.worksheet_id != ws.id:
        raise HTTPException(404)
    new_rev = WorksheetRevision(
        worksheet_id=ws.id,
        created_by_user_id=user.id,
        comment=f"Wiederhergestellt aus Revision #{src.id}",
        meta_json=src.meta_json,
        aufgaben_json=src.aufgaben_json,
    )
    db.add(new_rev)
    ws.updated_at = datetime.utcnow()
    audit(db, "worksheet_restored", actor=user, target=str(ws.id),
          detail=f"from_rev={src.id}", request=request)
    db.commit()
    return RedirectResponse(f"/worksheets/{ws.id}", status_code=303)


# ── Löschen ───────────────────────────────────────────────────────────────
@router.post("/{ws_id}/delete")
def delete_worksheet(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ws = _owned(db, ws_id, user)
    title = ws.title
    db.delete(ws)
    audit(db, "worksheet_deleted", actor=user, target=str(ws_id), detail=title, request=request)
    db.commit()
    return RedirectResponse("/worksheets", status_code=303)


# ── Export / Preview ──────────────────────────────────────────────────────
def _render_export_html(db: Session, ws: Worksheet, rev: WorksheetRevision,
                        with_solutions: bool = False) -> str:
    payload = {
        "meta": json.loads(rev.meta_json),
        "aufgaben": json.loads(rev.aufgaben_json),
        "withSolutions": bool(with_solutions),
    }
    title = ws.title + (" · Lehrer-Version" if with_solutions else "")
    return templates.get_template("worksheets/export.html").render({
        "ws_title": title,
        "config_json": json.dumps(payload, ensure_ascii=False),
        "school_name_value": get_school_name(db),
        "logo_data_url": logo_data_url(db),
    })


def _safe_filename(title: str, ws_id: int) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in title) or f"aufgabenblatt-{ws_id}"


def _require_rev(db: Session, ws: Worksheet) -> WorksheetRevision:
    rev = _latest_rev(db, ws)
    if not rev:
        raise HTTPException(400, "Noch keine Revision vorhanden — bitte erst speichern.")
    return rev


@router.get("/{ws_id}/export.html")
def export_html(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    with_solutions: int = 0,
):
    ws = _owned(db, ws_id, user)
    rendered = _render_export_html(db, ws, _require_rev(db, ws), bool(with_solutions))
    suffix = "_loesungen" if with_solutions else ""
    safe = _safe_filename(ws.title, ws.id) + suffix
    return Response(content=rendered, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.html"'})


@router.get("/{ws_id}/preview.html", response_class=HTMLResponse)
def preview_html(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    with_solutions: int = 0,
):
    ws = _owned(db, ws_id, user)
    return HTMLResponse(content=_render_export_html(
        db, ws, _require_rev(db, ws), bool(with_solutions)))


@router.get("/{ws_id}/export.pdf")
async def export_pdf(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    with_solutions: int = 0,
):
    ws = _owned(db, ws_id, user)
    rendered = _render_export_html(db, ws, _require_rev(db, ws), bool(with_solutions))
    pdf_bytes = await render_pdf(rendered)
    audit(db, "worksheet_exported_pdf", actor=user, target=str(ws.id),
          detail="loesungen" if with_solutions else "", request=request)
    db.commit()
    suffix = "_loesungen" if with_solutions else ""
    safe = _safe_filename(ws.title, ws.id) + suffix
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})


@router.get("/{ws_id}/preview.pdf")
async def preview_pdf(
    ws_id: int,
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    with_solutions: int = 0,
):
    ws = _owned(db, ws_id, user)
    rendered = _render_export_html(db, ws, _require_rev(db, ws), bool(with_solutions))
    pdf_bytes = await render_pdf(rendered)
    suffix = "_loesungen" if with_solutions else ""
    safe = _safe_filename(ws.title, ws.id) + suffix
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'})
