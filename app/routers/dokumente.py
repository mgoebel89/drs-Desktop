"""Dokumente-Modul: Backend-Proxy auf Paperless-ngx.

Der API-Token bleibt im Server (`app/services/paperless_client.py`); der
Browser spricht ausschließlich mit diesen Endpoints. Eingerichtet wird im
Profil — dort werden auch die Anzeige-Tags, der Upload-Tag und der
Speicherpfad aus den in Paperless vorhandenen Listen ausgewählt.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import User
from app.services import paperless_client as pl
from app.templating import templates

router = APIRouter()

# Uploads aus dem Browser deckeln — Paperless selbst nimmt mehr, aber ein
# versehentlich gewähltes Video soll nicht den Container-Speicher füllen.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _err(e: pl.PaperlessError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)


@router.get("/dokumente", response_class=HTMLResponse)
def dokumente_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
):
    """Die Seite selbst lädt nichts — Liste und Stammlisten holt das Frontend
    parallel nach. Ein hängendes Paperless blockiert so nicht den Seitenaufbau."""
    cfg = pl.load_config(user)
    return templates.TemplateResponse(request, "dokumente/list.html", {
        "configured": pl.is_configured(user),
        "orderings": pl.ORDERINGS,
        "has_view_filter": bool(cfg and cfg.view_tag_ids),
    })


# ── Listen ───────────────────────────────────────────────────────────────

@router.get("/api/dokumente/stammlisten")
def dokumente_stammlisten(user: Annotated[User, Depends(require_user)]):
    try:
        return JSONResponse({"ok": True, **pl.stammlisten(user)})
    except pl.PaperlessError as e:
        return _err(e)


@router.get("/api/dokumente/liste")
def dokumente_liste(
    user: Annotated[User, Depends(require_user)],
    query: str = "",
    tags: str = "",
    correspondent: int = 0,
    document_type: int = 0,
    ordering: str = "-created",
    page: int = 1,
):
    tag_ids = [t for t in (tags or "").split(",") if t.strip()]
    try:
        d = pl.search_documents(
            user, query=query, tag_ids=tag_ids, correspondent=correspondent,
            document_type=document_type, ordering=ordering, page=page)
        return JSONResponse({"ok": True, **d})
    except pl.PaperlessError as e:
        return _err(e)


# ── Upload ───────────────────────────────────────────────────────────────
# Vor den generischen /{doc_id}-Routen, sonst schluckt die den Pfad.

@router.post("/api/dokumente/upload")
async def dokumente_upload(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    datei: UploadFile = File(...),
    title: str = Form(""),
    created: str = Form(""),
    correspondent: int = Form(0),
    document_type: int = Form(0),
    tags: str = Form(""),
):
    """Nimmt die Datei entgegen und reicht sie an Paperless weiter.

    Upload-Tag und Speicherpfad kommen aus der Konfiguration und werden im
    Client gesetzt — hier landen nur die zusätzlich gewählten Tags.
    """
    content = await datei.read()
    if not content:
        return JSONResponse({"ok": False, "error": "Die Datei ist leer."},
                            status_code=400)
    if len(content) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"ok": False, "error": "Die Datei ist größer als 50 MB."},
            status_code=413)

    extra = [t for t in (tags or "").split(",") if t.strip()]
    try:
        task_id = pl.upload_document(
            user, filename=datei.filename or "dokument.pdf", content=content,
            mimetype=datei.content_type or "application/octet-stream",
            title=title, created=created, correspondent=correspondent,
            document_type=document_type, extra_tag_ids=extra)
    except pl.PaperlessError as e:
        return _err(e)

    audit(db, "paperless_upload", actor=user,
          detail=(datei.filename or "")[:120], request=request)
    db.commit()
    return JSONResponse({"ok": True, "task_id": task_id})


@router.get("/api/dokumente/task/{task_id}")
def dokumente_task(task_id: str, user: Annotated[User, Depends(require_user)]):
    """Polling nach dem Upload — Paperless verarbeitet (OCR) asynchron."""
    try:
        return JSONResponse({"ok": True, **pl.get_task(user, task_id)})
    except pl.PaperlessError as e:
        return _err(e)


# ── Einzelnes Dokument ───────────────────────────────────────────────────

@router.get("/dokumente/{doc_id}/datei/{kind}")
def dokumente_datei(
    doc_id: int, kind: str,
    user: Annotated[User, Depends(require_user)],
):
    """Vorschau/Thumbnail/Original — gestreamt über den Server, damit der
    Token nicht in den Browser muss."""
    try:
        content, ctype = pl.fetch_file(user, doc_id, kind)
    except pl.PaperlessError as e:
        return Response(str(e), status_code=e.status, media_type="text/plain")
    headers = {"Cache-Control": "private, max-age=300"}
    if kind == "download":
        headers["Content-Disposition"] = f'attachment; filename="dokument-{doc_id}"'
    return Response(content, media_type=ctype, headers=headers)


@router.get("/api/dokumente/{doc_id}/notizen")
def dokumente_notizen(doc_id: int, user: Annotated[User, Depends(require_user)]):
    try:
        return JSONResponse({"ok": True, "notes": pl.list_notes(user, doc_id)})
    except pl.PaperlessError as e:
        return _err(e)


@router.post("/api/dokumente/{doc_id}/notizen")
def dokumente_notiz_neu(
    doc_id: int,
    user: Annotated[User, Depends(require_user)],
    payload: dict = Body(...),
):
    text = (payload.get("note") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "Die Notiz ist leer."},
                            status_code=400)
    try:
        return JSONResponse({"ok": True, "notes": pl.add_note(user, doc_id, text)})
    except pl.PaperlessError as e:
        return _err(e)


@router.post("/api/dokumente/{doc_id}/notizen/{note_id}/delete")
def dokumente_notiz_weg(
    doc_id: int, note_id: int,
    user: Annotated[User, Depends(require_user)],
):
    try:
        return JSONResponse(
            {"ok": True, "notes": pl.delete_note(user, doc_id, note_id)})
    except pl.PaperlessError as e:
        return _err(e)


@router.post("/api/dokumente/{doc_id}/save")
def dokumente_save(
    request: Request,
    doc_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    try:
        doc = pl.update_document(user, doc_id, payload)
    except pl.PaperlessError as e:
        return _err(e)
    audit(db, "paperless_update", actor=user, target=str(doc_id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "doc": doc})


@router.get("/api/dokumente/{doc_id}")
def dokumente_detail(doc_id: int, user: Annotated[User, Depends(require_user)]):
    try:
        return JSONResponse({"ok": True, "doc": pl.get_document(user, doc_id)})
    except pl.PaperlessError as e:
        return _err(e)
