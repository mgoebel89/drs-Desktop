"""Stammdaten Lernfelder (Schema v4): pro User editierbare Tabelle
mit Nummer/Titel/Beruf. Werden via M2M an LearningSituation gehängt."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import Lernfeld, LsLernfeld, User
from app.templating import templates

router = APIRouter()


def _ser(lf: Lernfeld) -> dict:
    return {
        "id": lf.id,
        "beruf_key": lf.beruf_key or "",
        "nummer": lf.nummer or 0,
        "titel": lf.titel or "",
        "stunden_lehrplan": lf.stunden_lehrplan,
    }


@router.get("/lernfelder", response_class=HTMLResponse)
def lernfelder_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(Lernfeld).where(Lernfeld.user_id == user.id)
        .order_by(Lernfeld.beruf_key, Lernfeld.nummer)
    ).all()
    # Verknüpfungs-Count pro Lernfeld (für 'X LS verknüpft'-Anzeige)
    from sqlalchemy import func
    counts: dict[int, int] = {}
    for lf_id, n in db.execute(
        select(LsLernfeld.lernfeld_id, func.count())
        .group_by(LsLernfeld.lernfeld_id)
    ).all():
        counts[int(lf_id)] = int(n)
    return templates.TemplateResponse(request, "lernfelder/list.html", {
        "items": rows,
        "counts": counts,
    })


@router.post("/lernfelder")
def lernfelder_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    beruf_key: str = Form(""),
    nummer: int = Form(0),
    titel: str = Form(...),
    stunden_lehrplan: str = Form(""),
):
    titel = titel.strip()[:255]
    if not titel:
        raise HTTPException(400, "Titel fehlt")
    try:
        nummer = max(0, int(nummer))
    except (TypeError, ValueError):
        nummer = 0
    sl: int | None = None
    if stunden_lehrplan.strip():
        try:
            sl = max(0, int(stunden_lehrplan))
        except (TypeError, ValueError):
            sl = None
    lf = Lernfeld(
        user_id=user.id,
        beruf_key=beruf_key.strip()[:64],
        nummer=nummer,
        titel=titel,
        stunden_lehrplan=sl,
    )
    db.add(lf)
    audit(db, "lernfeld_created", actor=user, target=titel, request=request)
    db.commit()
    return RedirectResponse("/lernfelder", status_code=303)


@router.post("/api/lernfelder/{lf_id}")
def lernfeld_update(
    request: Request,
    lf_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    lf = db.get(Lernfeld, lf_id)
    if not lf or lf.user_id != user.id:
        raise HTTPException(404)
    field = (body.get("field") or "").strip()
    value = body.get("value")
    if field == "beruf_key":
        lf.beruf_key = str(value or "").strip()[:64]
    elif field == "nummer":
        try:
            lf.nummer = max(0, int(value))
        except (TypeError, ValueError):
            raise HTTPException(400, "Nummer muss eine Zahl sein")
    elif field == "titel":
        v = str(value or "").strip()[:255]
        if not v:
            raise HTTPException(400, "Titel darf nicht leer sein")
        lf.titel = v
    elif field == "stunden_lehrplan":
        v = str(value or "").strip()
        if not v:
            lf.stunden_lehrplan = None
        else:
            try:
                lf.stunden_lehrplan = max(0, int(v))
            except (TypeError, ValueError):
                raise HTTPException(400, "Stunden muss eine Zahl sein")
    else:
        raise HTTPException(400, "Unbekanntes Feld")
    audit(db, "lernfeld_updated", actor=user, target=str(lf.id),
          detail=f"{field}={value}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "item": _ser(lf)})


@router.post("/lernfelder/{lf_id}/delete")
def lernfeld_delete(
    request: Request,
    lf_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lf = db.get(Lernfeld, lf_id)
    if not lf or lf.user_id != user.id:
        raise HTTPException(404)
    # Verknüpfung prüfen
    n = db.scalar(select(LsLernfeld).where(
        LsLernfeld.lernfeld_id == lf_id).limit(1))
    if n is not None:
        raise HTTPException(400, "Lernfeld ist noch mit Lernsituationen verknüpft")
    titel = lf.titel
    db.delete(lf)
    audit(db, "lernfeld_deleted", actor=user, target=titel, request=request)
    db.commit()
    return RedirectResponse("/lernfelder", status_code=303)


@router.get("/api/lernfelder")
def lernfeld_list_json(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    beruf: str = "",
):
    """JSON-Liste für Dropdowns (z. B. im LS-Detail-Multi-Select).
    Wenn `beruf` gesetzt, sortiert passende Lernfelder nach oben."""
    rows = db.scalars(
        select(Lernfeld).where(Lernfeld.user_id == user.id)
        .order_by(Lernfeld.beruf_key, Lernfeld.nummer)
    ).all()
    beruf_norm = (beruf or "").strip()
    items = [_ser(lf) for lf in rows]
    if beruf_norm:
        items.sort(key=lambda x: (0 if x["beruf_key"] == beruf_norm else 1))
    return JSONResponse({"ok": True, "items": items})
