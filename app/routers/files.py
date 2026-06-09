"""HTTP-Endpoints für die /api/files-Bilder-Bridge.

- `POST /api/files`  (multipart)   → legt eine Datei an, liefert
  {file_uuid, filename, url}.
- `GET  /api/files/<uuid>/<name>`  → liefert die Datei (Auth-pflichtig,
  nur Besitzer:in darf zugreifen).
- `DELETE /api/files/<uuid>`       → entfernt die Datei (Besitzer:in).

Diese Endpunkte sind komplementär zur SMB-Vault-Anbindung — die App
akzeptiert in Lernsituationen sowohl `/api/files/<uuid>/...`-Pfade als
auch vault-relative Pfade.
"""
from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import AppFile, User
from app.services import file_store, smb_client
from app.models import LearningSituation


router = APIRouter()


@router.post("/api/files")
async def files_upload(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    payload = await file.read()
    try:
        file_uuid, fname = file_store.store(payload, file.filename or "datei")
    except ValueError as e:
        raise HTTPException(400, str(e))
    mime = file.content_type or mimetypes.guess_type(fname)[0] or "application/octet-stream"
    db.add(AppFile(
        file_uuid=file_uuid, owner_user_id=user.id,
        filename=fname, mime=mime, size=len(payload),
    ))
    audit(db, "file_uploaded", actor=user, target=file_uuid,
          detail=f"{fname} · {len(payload)}B")
    db.commit()
    return JSONResponse({
        "ok": True,
        "file_uuid": file_uuid,
        "filename": fname,
        "url": f"/api/files/{file_uuid}/{fname}",
    })


@router.get("/api/files/{file_uuid}/{filename}")
def files_get(
    file_uuid: str,
    filename: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    af = db.query(AppFile).filter(AppFile.file_uuid == file_uuid).first()
    if not af or af.owner_user_id != user.id:
        raise HTTPException(404, "Datei nicht gefunden")
    path = file_store.resolve(file_uuid, filename)
    if path is None:
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(path, media_type=af.mime or "application/octet-stream",
                        filename=af.filename)


@router.get("/api/vault-image/{ls_id}")
def vault_image(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    p: str = "",
):
    """Streamt eine vault-relative Datei (Bild/Anhang) der angegebenen LS.

    Dient als Proxy für `![](relativer_pfad)`-Bilder in der MD, die der
    Lehrer in Obsidian gepflegt hat. Akzeptiert nur Pfade unterhalb des
    LS-Material-Ordners — keine Pfad-Traversals."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    rel = (p or "").strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(400, "Ungültiger Pfad")
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(404, "Kein SMB konfiguriert")
    # Material- oder Vault-Ordner — beides erlauben (LS-Bilder liegen
    # üblicherweise im Material-Ordner, können aber auch im Vault liegen).
    candidates = [
        smb_client.material_subpath(cfg, ls.smb_folder_name) + "/" + rel,
        cfg.vault_subpath.strip("/") + "/" + rel,
    ]
    for subpath in candidates:
        try:
            data = smb_client.read_file(user, subpath)
        except Exception:
            continue
        mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        return Response(content=data, media_type=mime)
    raise HTTPException(404, "Datei nicht gefunden")


@router.delete("/api/files/{file_uuid}")
def files_delete(
    file_uuid: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    af = db.query(AppFile).filter(AppFile.file_uuid == file_uuid).first()
    if not af or af.owner_user_id != user.id:
        raise HTTPException(404, "Datei nicht gefunden")
    file_store.delete(file_uuid)
    db.delete(af)
    audit(db, "file_deleted", actor=user, target=file_uuid, detail=af.filename)
    db.commit()
    return JSONResponse({"ok": True})
