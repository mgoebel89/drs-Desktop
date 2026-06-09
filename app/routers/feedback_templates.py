"""Verwaltung wiederverwendbarer Feedbackpunkt-Sets (Vorlagen)."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import FeedbackTemplate, User
from app.templating import templates

router = APIRouter()


def _clean_points(raw: list) -> list[dict]:
    out: list[dict] = []
    for p in raw or []:
        try:
            name = str(p.get("name", "")).strip()
        except AttributeError:
            continue
        if not name:
            continue
        stages = []
        for st in (p.get("stages") or []):
            try:
                lbl = str(st.get("label", "")).strip()
                if not lbl:
                    continue
                stages.append({"label": lbl[:40], "points": float(st.get("points", 0))})
            except (AttributeError, TypeError, ValueError):
                continue
        scope = p.get("scope") if p.get("scope") in ("individual", "group") else "individual"
        eval_type = p.get("eval_type") if p.get("eval_type") in ("punkte", "note", "stufen") else "punkte"
        out.append({
            "name": name[:200],
            "max_points": float(p.get("max_points", 0) or 0),
            "scope": scope,
            "eval_type": eval_type,
            "weight_pct": float(p.get("weight_pct", 0) or 0),
            "stages": stages,
        })
    return out


@router.get("/feedback-templates", response_class=HTMLResponse)
def ft_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(FeedbackTemplate).where(FeedbackTemplate.owner_user_id == user.id)
        .order_by(FeedbackTemplate.name)
    ).all()
    views = []
    for t in rows:
        try:
            pts = json.loads(t.payload_json) or []
        except Exception:
            pts = []
        views.append({"t": t, "n": len(pts)})
    return templates.TemplateResponse(request, "feedback_templates/list.html", {
        "items": views,
    })


@router.get("/feedback-templates/new", response_class=HTMLResponse)
def ft_new(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return templates.TemplateResponse(request, "feedback_templates/edit.html", {
        "tmpl": None, "name": "", "points": [],
    })


@router.post("/feedback-templates")
def ft_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    name = (body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(400, "Name fehlt")
    pts = _clean_points(body.get("points") or [])
    t = FeedbackTemplate(
        owner_user_id=user.id, name=name,
        payload_json=json.dumps(pts, ensure_ascii=False),
    )
    db.add(t)
    db.flush()
    audit(db, "feedback_template_created", actor=user, target=str(t.id),
          detail=name, request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": t.id})


@router.get("/feedback-templates/{tid}", response_class=HTMLResponse)
def ft_edit(
    request: Request,
    tid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    t = db.get(FeedbackTemplate, tid)
    if not t or t.owner_user_id != user.id:
        raise HTTPException(404)
    try:
        pts = json.loads(t.payload_json) or []
    except Exception:
        pts = []
    return templates.TemplateResponse(request, "feedback_templates/edit.html", {
        "tmpl": t, "name": t.name, "points": pts,
    })


@router.post("/feedback-templates/{tid}")
def ft_update(
    request: Request,
    tid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    t = db.get(FeedbackTemplate, tid)
    if not t or t.owner_user_id != user.id:
        raise HTTPException(404)
    name = (body.get("name") or "").strip()[:120]
    if name:
        t.name = name
    t.payload_json = json.dumps(_clean_points(body.get("points") or []),
                                ensure_ascii=False)
    audit(db, "feedback_template_updated", actor=user, target=str(t.id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/feedback-templates/{tid}/delete")
def ft_delete(
    request: Request,
    tid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    t = db.get(FeedbackTemplate, tid)
    if not t or t.owner_user_id != user.id:
        raise HTTPException(404)
    name = t.name
    db.delete(t)
    audit(db, "feedback_template_deleted", actor=user, target=str(tid),
          detail=name, request=request)
    db.commit()
    return RedirectResponse("/feedback-templates", status_code=303)


@router.get("/api/feedback-templates")
def ft_api_list(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Für das 'aus Vorlage laden'-Dropdown im Exam-Tab."""
    rows = db.scalars(
        select(FeedbackTemplate).where(FeedbackTemplate.owner_user_id == user.id)
        .order_by(FeedbackTemplate.name)
    ).all()
    out = []
    for t in rows:
        try:
            pts = json.loads(t.payload_json) or []
        except Exception:
            pts = []
        out.append({"id": t.id, "name": t.name, "points": pts})
    return JSONResponse({"ok": True, "templates": out})
