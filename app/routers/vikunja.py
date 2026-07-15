"""Aufgaben-Modul: Backend-Proxy auf EIN Vikunja-Projekt.

Der API-Token bleibt im Server (app/services/vikunja_client.py); der Browser
spricht ausschließlich mit diesen Endpoints. Konfiguriert wird im Profil.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import User
from app.services import vikunja_client as vk
from app.templating import templates

router = APIRouter()


def _error_response(e: vk.VikunjaError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)


@router.get("/aufgaben", response_class=HTMLResponse)
def aufgaben_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
):
    """Aufgabenliste. Fehler der Vikunja-Instanz brechen die Seite nicht —
    sie werden als Hinweis angezeigt, damit der Lehrer weiterarbeiten kann."""
    tasks: list[dict] = []
    error = ""
    configured = vk.is_configured(user)
    if configured:
        try:
            tasks = vk.list_open_tasks(user)
        except vk.VikunjaError as e:
            error = str(e)

    return templates.TemplateResponse(request, "vikunja/list.html", {
        "tasks": tasks,
        "configured": configured,
        "error": error,
        "priorities": vk.PRIORITY_LABELS,
    })


@router.post("/aufgaben")
def aufgaben_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    title: str = Form(...),
    due_date: str = Form(""),
    priority: int = Form(0),
    description: str = Form(""),
    view: str = Form(""),
):
    suffix = "#board" if view == "board" else ""
    try:
        task = vk.create_task(user, title, due_date, priority, description)
    except vk.VikunjaError as e:
        return RedirectResponse(f"/aufgaben?err={str(e)[:200]}{suffix}", status_code=303)
    audit(db, "vikunja_task_created", actor=user,
          target=str(task.get("id") or ""), detail=title[:120], request=request)
    db.commit()
    return RedirectResponse(f"/aufgaben{suffix}", status_code=303)


@router.post("/api/vikunja/tasks/{task_id}/done")
def aufgaben_done(
    request: Request,
    task_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    done: bool = True,
):
    try:
        task = vk.set_done(user, task_id, done)
    except vk.VikunjaError as e:
        return _error_response(e)
    audit(db, "vikunja_task_done" if done else "vikunja_task_reopened",
          actor=user, target=str(task_id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "task": task})


@router.post("/api/vikunja/tasks/{task_id}/delete")
def aufgaben_delete(
    request: Request,
    task_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        vk.delete_task(user, task_id)
    except vk.VikunjaError as e:
        return _error_response(e)
    audit(db, "vikunja_task_deleted", actor=user, target=str(task_id),
          request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/api/dashboard/tasks")
def dashboard_tasks(
    user: Annotated[User, Depends(require_user)],
    limit: int = 6,
):
    """Karte „Offene Aufgaben" auf der Übersicht. Fehlertolerant: ist Vikunja
    nicht konfiguriert oder gerade nicht erreichbar, bleibt das Dashboard
    trotzdem heil (ok=False + Grund)."""
    if not vk.is_configured(user):
        return JSONResponse({"ok": False, "reason": "unconfigured", "tasks": []})
    try:
        tasks = vk.list_open_tasks(user)
    except vk.VikunjaError as e:
        return JSONResponse({"ok": False, "reason": str(e), "tasks": []})
    return JSONResponse({
        "ok": True,
        "total": len(tasks),
        "tasks": tasks[:max(1, min(limit, 20))],
    })


# ── Kanban-Board ──────────────────────────────────────────────────────────

@router.get("/api/vikunja/board")
def board(user: Annotated[User, Depends(require_user)]):
    """Spalten (Buckets) + Aufgaben der Kanban-View."""
    try:
        return JSONResponse({"ok": True, **vk.list_board(user)})
    except vk.VikunjaError as e:
        return _error_response(e)


@router.post("/api/vikunja/tasks/{task_id}/move")
def task_move(
    request: Request,
    task_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    """Aufgabe in einen anderen Bucket schieben (Drag & Drop im Board)."""
    try:
        bucket_id = int(payload.get("bucket_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "bucket_id fehlt."}, status_code=400)
    position = payload.get("position")
    try:
        vk.move_task(user, bucket_id, task_id,
                     float(position) if position is not None else None)
    except vk.VikunjaError as e:
        return _error_response(e)
    audit(db, "vikunja_task_moved", actor=user, target=str(task_id),
          detail=f"bucket {bucket_id}", request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/vikunja/tasks/{task_id}/update")
def task_update(
    request: Request,
    task_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    """Titel/Fälligkeit/Priorität/Beschreibung ändern (Edit-Karte)."""
    try:
        task = vk.update_task(
            user, task_id,
            title=payload.get("title"),
            due_date=payload.get("due_date"),
            priority=(int(payload["priority"]) if "priority" in payload else None),
            description=payload.get("description"),
        )
    except vk.VikunjaError as e:
        return _error_response(e)
    audit(db, "vikunja_task_updated", actor=user, target=str(task_id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "task": task})


# ── Labels ────────────────────────────────────────────────────────────────

@router.get("/api/vikunja/labels")
def labels(user: Annotated[User, Depends(require_user)]):
    try:
        return JSONResponse({"ok": True, "labels": vk.list_labels(user)})
    except vk.VikunjaError as e:
        return _error_response(e)


@router.post("/api/vikunja/tasks/{task_id}/labels")
def task_label_add(
    task_id: int,
    user: Annotated[User, Depends(require_user)],
    payload: dict = Body(...),
):
    try:
        label_id = int(payload.get("label_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "label_id fehlt."}, status_code=400)
    try:
        vk.add_label(user, task_id, label_id)
    except vk.VikunjaError as e:
        return _error_response(e)
    return JSONResponse({"ok": True})


@router.post("/api/vikunja/tasks/{task_id}/labels/{label_id}/delete")
def task_label_remove(
    task_id: int,
    label_id: int,
    user: Annotated[User, Depends(require_user)],
):
    try:
        vk.remove_label(user, task_id, label_id)
    except vk.VikunjaError as e:
        return _error_response(e)
    return JSONResponse({"ok": True})
