"""Vorschau und Datei-Streaming für LS-Materialien.

Routen:
  GET  /ls/{ls_id}/files/{filename}           — authentifizierter Download/Stream
  GET  /ls/{ls_id}/preview/{filename}         — HTML-Wrapper mit passender Vorschau
  GET  /onlyoffice/file/{token}/{filename}    — von OnlyOffice-Server abgerufen
                                                  (token-basiert, kein Cookie)

Dateityp-Routing in /preview:
  pdf, png, jpg, jpeg, gif, webp, svg  → Inline im Browser
  doc(x), xls(x), ppt(x), odt, ods, …   → OnlyOffice-Iframe
  alles andere                          → Download-Link
"""
from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import LearningSituation, User
from app.services import onlyoffice_client, smb_client
from app.templating import templates

router = APIRouter()

INLINE_EXT = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "svg"}
MIME = {
    "pdf": "application/pdf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _get_ls(db: Session, user: User, ls_id: int) -> LearningSituation:
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404, "Lernsituation nicht gefunden")
    return ls


def _check_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400, "Ungültiger Dateiname")


def _stream(user: User, subpath: str, filename: str, content_type: str) -> StreamingResponse:
    try:
        gen = smb_client.stream_file(user, subpath)
    except Exception as e:
        raise HTTPException(502, f"SMB-Fehler: {e}")
    headers = {
        "Content-Disposition": f'inline; filename="{quote(filename)}"',
        "Cache-Control": "private, max-age=60",
    }
    return StreamingResponse(gen, media_type=content_type, headers=headers)


@router.get("/ls/{ls_id}/files/{filename}")
def ls_file(
    ls_id: int,
    filename: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _check_filename(filename)
    ls = _get_ls(db, user, ls_id)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    subpath = smb_client.material_subpath(cfg, ls.smb_folder_name) + "/" + filename
    ext = _ext(filename)
    ctype = MIME.get(ext, "application/octet-stream")
    return _stream(user, subpath, filename, ctype)


@router.get("/ls/{ls_id}/preview/{filename}", response_class=HTMLResponse)
def ls_preview(
    request: Request,
    ls_id: int,
    filename: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = _get_ls(db, user, ls_id)
    ext = _ext(filename)
    ctx = {
        "ls": ls,
        "filename": filename,
        "ext": ext,
        "file_url": f"/ls/{ls_id}/files/{quote(filename)}",
        "onlyoffice": None,
    }

    if ext in INLINE_EXT or ext in ("txt", "md"):
        ctx["mode"] = "inline"
    elif onlyoffice_client.doc_type_for(filename) and onlyoffice_client.is_configured():
        token = onlyoffice_client.issue_file_token(user.id, ls.id, filename)
        # OnlyOffice ruft die Datei über öffentlichen Host der App ab. Im LXC
        # ist das die Container-IP (z.B. 192.168.5.1). Wir konstruieren absolute URL
        # aus dem Request.
        base = f"{request.url.scheme}://{request.url.netloc}"
        file_url_for_oo = f"{base}/onlyoffice/file/{token}/{quote(filename)}"
        doc_key = f"ls{ls.id}-{filename}-{int(ls.updated_at.timestamp())}"
        from app.config import settings as app_settings
        ctx["onlyoffice"] = {
            "server_url": app_settings.onlyoffice_url.rstrip("/") + "/web-apps/apps/api/documents/api.js",
            "config": onlyoffice_client.build_editor_config(
                public_base_url=base,
                file_url=file_url_for_oo,
                filename=filename,
                document_key=doc_key,
                user_id=user.id,
                user_name=user.full_name or user.username,
                mode="view",
            ),
        }
        ctx["mode"] = "onlyoffice"
    else:
        ctx["mode"] = "download"

    return templates.TemplateResponse(request, "preview.html", ctx)


@router.get("/onlyoffice/file/{token}/{filename}")
def onlyoffice_file(token: str, filename: str, db: Annotated[Session, Depends(get_db)]):
    _check_filename(filename)
    info = onlyoffice_client.consume_file_token(token)
    if not info or info["filename"] != filename:
        raise HTTPException(404)
    user = db.get(User, info["user_id"])
    ls = db.get(LearningSituation, info["ls_id"])
    if not user or not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    subpath = smb_client.material_subpath(cfg, ls.smb_folder_name) + "/" + filename
    ext = _ext(filename)
    ctype = MIME.get(ext, "application/octet-stream")
    return _stream(user, subpath, filename, ctype)
