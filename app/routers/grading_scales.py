"""Verwaltung benutzerdefinierter Notenskalen (Typ MSS Punkte / MSS Noten)."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import GradingScale, User
from app.services import grading
from app.templating import templates

router = APIRouter()


@router.get("/grading-scales", response_class=HTMLResponse)
def scales_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(GradingScale).where(GradingScale.owner_user_id == user.id)
        .order_by(GradingScale.name)
    ).all()
    builtins = [
        {"key": k, "label": v["label"], "type": v["type"],
         "n_stufen": len(v["stufen"])}
        for k, v in grading.BUILTINS.items()
    ]
    return templates.TemplateResponse(request, "grading_scales/list.html", {
        "scales": rows,
        "builtins": builtins,
        "scale_types": grading.list_scale_types(),
    })


@router.get("/grading-scales/new", response_class=HTMLResponse)
def scales_new(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    type: str = "mss_noten",
    copy_from: str = "",
):
    if type not in grading.SCALE_TYPES:
        type = "mss_noten"
    # Vorbelegung: Built-in-Vorlage kopieren oder Default des Typs
    if copy_from and copy_from in grading.BUILTINS:
        bt = grading.BUILTINS[copy_from]
        type = bt["type"]
        stufen = [{"label": l, "min_pct": lo, "max_pct": hi}
                  for l, lo, hi in bt["stufen"]]
        name = bt["label"] + " (Kopie)"
    else:
        stufen = grading.default_stufen_for(type)
        name = ""
    return templates.TemplateResponse(request, "grading_scales/edit.html", {
        "scale": None,
        "scale_type": type,
        "type_label": grading.SCALE_TYPES[type]["label"],
        "name": name,
        "stufen": stufen,
    })


@router.post("/grading-scales")
def scales_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    name = (body.get("name") or "").strip()[:120]
    scale_type = body.get("scale_type") or "mss_noten"
    if scale_type not in grading.SCALE_TYPES:
        scale_type = "mss_noten"
    if not name:
        raise HTTPException(400, "Name fehlt")
    stufen = _clean_stufen(body.get("stufen") or [])
    gs = GradingScale(
        owner_user_id=user.id, name=name, scale_type=scale_type,
        payload_json=json.dumps(stufen, ensure_ascii=False),
    )
    db.add(gs)
    db.flush()
    audit(db, "grading_scale_created", actor=user, target=str(gs.id),
          detail=name, request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": gs.id})


@router.get("/grading-scales/{scale_id}", response_class=HTMLResponse)
def scales_edit(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    try:
        stufen = json.loads(gs.payload_json) or []
    except Exception:
        stufen = []
    return templates.TemplateResponse(request, "grading_scales/edit.html", {
        "scale": gs,
        "scale_type": gs.scale_type,
        "type_label": grading.SCALE_TYPES.get(gs.scale_type, {}).get("label", gs.scale_type),
        "name": gs.name,
        "stufen": stufen,
    })


@router.post("/grading-scales/{scale_id}")
def scales_update(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    name = (body.get("name") or "").strip()[:120]
    if name:
        gs.name = name
    gs.payload_json = json.dumps(_clean_stufen(body.get("stufen") or []),
                                 ensure_ascii=False)
    audit(db, "grading_scale_updated", actor=user, target=str(gs.id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/grading-scales/{scale_id}/delete")
def scales_delete(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    name = gs.name
    db.delete(gs)
    audit(db, "grading_scale_deleted", actor=user, target=str(scale_id),
          detail=name, request=request)
    db.commit()
    return RedirectResponse("/grading-scales", status_code=303)


def _clean_stufen(raw: list) -> list[dict]:
    out: list[dict] = []
    for row in raw:
        try:
            label = str(row.get("label", "")).strip()
            if not label:
                continue
            out.append({
                "label": label[:16],
                "min_pct": float(row.get("min_pct", 0)),
                "max_pct": float(row.get("max_pct", 0)),
            })
        except (AttributeError, TypeError, ValueError):
            continue
    return out
