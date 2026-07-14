"""Stammdaten: Klassen und Fächer für den manuellen Stundenplan.

Der technische Schlüssel (`klassen_key` / `subjects_key`) ist nach dem Anlegen
UNVERÄNDERLICH — er ist Teil des key4, an dem die Stundennotizen hängen. Wer ihn
nachträglich ändert, hängt alle Notizen dieser Klasse/dieses Fachs ab. Deshalb
gibt es `/api/stammdaten/suggest-keys`: Es liest die tatsächlich im Bestand
vorhandenen Keys aus und bietet sie zur 1:1-Übernahme an.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (Exam, LessonNote, LessonSeriesOverride, Student,
                        TtFach, TtKlasse, TtRow, User)
from app.templating import templates

router = APIRouter()


# ── Vorschläge aus dem Bestand ───────────────────────────────────────────

def _suggest_klassen(db: Session, user: User) -> list[dict]:
    """Distinct klassen_key aus Notizen, Schülern und Prüfungen, mit Trefferzahl."""
    counts: dict[str, int] = {}
    sources: dict[str, set[str]] = {}

    def add(key: str, quelle: str, n: int = 1) -> None:
        key = (key or "").strip()
        if not key:
            return
        counts[key] = counts.get(key, 0) + n
        sources.setdefault(key, set()).add(quelle)

    for kk, n in db.execute(
        select(LessonNote.klassen_key, func.count())
        .where(LessonNote.user_id == user.id)
        .group_by(LessonNote.klassen_key)
    ).all():
        add(kk, "Notizen", n)
    for kk, n in db.execute(
        select(Student.klassen_key, func.count())
        .where(Student.owner_user_id == user.id)
        .group_by(Student.klassen_key)
    ).all():
        add(kk, "Schüler", n)
    for kk, n in db.execute(
        select(Exam.klassen_key, func.count())
        .where(Exam.owner_user_id == user.id)
        .group_by(Exam.klassen_key)
    ).all():
        add(kk, "Prüfungen", n)

    vorhanden = {
        k for (k,) in db.execute(
            select(TtKlasse.klassen_key).where(TtKlasse.user_id == user.id)
        ).all()
    }
    return [
        {"key": k, "count": counts[k], "sources": sorted(sources[k]),
         "exists": k in vorhanden}
        for k in sorted(counts)
    ]


def _suggest_faecher(db: Session, user: User) -> list[dict]:
    """Distinct subjects_key aus Notizen + Reihen-Overrides. Der Override liefert
    gleich einen brauchbaren Anzeigenamen mit."""
    counts: dict[str, int] = {}
    namen: dict[str, str] = {}

    for sk, n in db.execute(
        select(LessonNote.subjects_key, func.count())
        .where(LessonNote.user_id == user.id)
        .group_by(LessonNote.subjects_key)
    ).all():
        if (sk or "").strip():
            counts[sk] = counts.get(sk, 0) + n

    for so in db.query(LessonSeriesOverride).filter(
        LessonSeriesOverride.user_id == user.id,
    ).all():
        if so.subjects_key and so.display_name.strip():
            counts.setdefault(so.subjects_key, 0)
            namen[so.subjects_key] = so.display_name.strip()

    vorhanden = {
        k for (k,) in db.execute(
            select(TtFach.subjects_key).where(TtFach.user_id == user.id)
        ).all()
    }
    return [
        {"key": k, "count": counts[k], "vorschlag_name": namen.get(k, k),
         "exists": k in vorhanden}
        for k in sorted(counts)
    ]


@router.get("/api/stammdaten/suggest-keys")
def suggest_keys(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return JSONResponse({
        "klassen": _suggest_klassen(db, user),
        "faecher": _suggest_faecher(db, user),
    })


# ── Klassen ──────────────────────────────────────────────────────────────

@router.get("/stammdaten/klassen", response_class=HTMLResponse)
def klassen_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(TtKlasse).where(TtKlasse.user_id == user.id)
        .order_by(TtKlasse.position, TtKlasse.klassen_key)
    ).all()
    return templates.TemplateResponse(request, "stammdaten/klassen.html", {
        "klassen": rows,
        "suggest": [s for s in _suggest_klassen(db, user) if not s["exists"]],
    })


@router.post("/stammdaten/klassen")
def klassen_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    klassen_key: str = Form(...),
    display_name: str = Form(""),
    kuerzel: str = Form(""),
):
    key = klassen_key.strip()[:255]
    if not key:
        raise HTTPException(400, "Schlüssel fehlt.")
    exists = db.scalar(select(TtKlasse.id).where(
        TtKlasse.user_id == user.id, TtKlasse.klassen_key == key))
    if exists:
        return RedirectResponse(
            "/stammdaten/klassen?err=Diese+Klasse+gibt+es+schon", status_code=303)
    pos = db.scalar(select(func.count()).select_from(TtKlasse)
                    .where(TtKlasse.user_id == user.id)) or 0
    db.add(TtKlasse(
        user_id=user.id, klassen_key=key,
        display_name=(display_name.strip() or key)[:200],
        kuerzel=kuerzel.strip()[:40], position=pos,
    ))
    audit(db, "tt_klasse_added", actor=user, target=key, request=request)
    db.commit()
    return RedirectResponse("/stammdaten/klassen", status_code=303)


@router.post("/stammdaten/klassen/import")
def klassen_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Übernimmt alle noch fehlenden Bestands-Keys auf einen Schlag."""
    offen = [s for s in _suggest_klassen(db, user) if not s["exists"]]
    pos = db.scalar(select(func.count()).select_from(TtKlasse)
                    .where(TtKlasse.user_id == user.id)) or 0
    for i, s in enumerate(offen):
        db.add(TtKlasse(user_id=user.id, klassen_key=s["key"],
                        display_name=s["key"], position=pos + i))
    audit(db, "tt_klassen_imported", actor=user,
          detail=f"{len(offen)} übernommen", request=request)
    db.commit()
    return RedirectResponse(
        f"/stammdaten/klassen?ok={len(offen)}", status_code=303)


@router.post("/stammdaten/klassen/{kid}")
def klassen_edit(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    k = db.get(TtKlasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    # klassen_key bleibt bewusst unangetastet — er ist Teil des key4.
    k.display_name = (display_name.strip() or k.klassen_key)[:200]
    k.kuerzel = kuerzel.strip()[:40]
    k.active = active == "1"
    db.commit()
    return RedirectResponse("/stammdaten/klassen", status_code=303)


@router.post("/stammdaten/klassen/{kid}/delete")
def klassen_delete(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = db.get(TtKlasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    benutzt = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.klasse_id == k.id))
    if benutzt:
        # Nicht löschen — Stundenplan-Zeilen hängen dran (CASCADE würde sie
        # mitreißen). Stattdessen stilllegen.
        k.active = False
        db.commit()
        return RedirectResponse(
            "/stammdaten/klassen?err=Klasse+wird+im+Stundenplan+benutzt+"
            "und+wurde+nur+stillgelegt", status_code=303)
    key = k.klassen_key
    db.delete(k)
    audit(db, "tt_klasse_deleted", actor=user, target=key, request=request)
    db.commit()
    return RedirectResponse("/stammdaten/klassen", status_code=303)


# ── Fächer ───────────────────────────────────────────────────────────────

@router.get("/stammdaten/faecher", response_class=HTMLResponse)
def faecher_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(TtFach).where(TtFach.user_id == user.id)
        .order_by(TtFach.position, TtFach.subjects_key)
    ).all()
    return templates.TemplateResponse(request, "stammdaten/faecher.html", {
        "faecher": rows,
        "suggest": [s for s in _suggest_faecher(db, user) if not s["exists"]],
    })


@router.post("/stammdaten/faecher")
def faecher_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    subjects_key: str = Form(...),
    display_name: str = Form(""),
    kuerzel: str = Form(""),
):
    key = subjects_key.strip()[:255]
    if not key:
        raise HTTPException(400, "Schlüssel fehlt.")
    exists = db.scalar(select(TtFach.id).where(
        TtFach.user_id == user.id, TtFach.subjects_key == key))
    if exists:
        return RedirectResponse(
            "/stammdaten/faecher?err=Dieses+Fach+gibt+es+schon", status_code=303)
    pos = db.scalar(select(func.count()).select_from(TtFach)
                    .where(TtFach.user_id == user.id)) or 0
    db.add(TtFach(
        user_id=user.id, subjects_key=key,
        display_name=(display_name.strip() or key)[:200],
        kuerzel=kuerzel.strip()[:40], position=pos,
    ))
    audit(db, "tt_fach_added", actor=user, target=key, request=request)
    db.commit()
    return RedirectResponse("/stammdaten/faecher", status_code=303)


@router.post("/stammdaten/faecher/import")
def faecher_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    offen = [s for s in _suggest_faecher(db, user) if not s["exists"]]
    pos = db.scalar(select(func.count()).select_from(TtFach)
                    .where(TtFach.user_id == user.id)) or 0
    for i, s in enumerate(offen):
        db.add(TtFach(user_id=user.id, subjects_key=s["key"],
                      display_name=s["vorschlag_name"], position=pos + i))
    audit(db, "tt_faecher_imported", actor=user,
          detail=f"{len(offen)} übernommen", request=request)
    db.commit()
    return RedirectResponse(f"/stammdaten/faecher?ok={len(offen)}", status_code=303)


@router.post("/stammdaten/faecher/{fid}")
def faecher_edit(
    request: Request,
    fid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    f = db.get(TtFach, fid)
    if not f or f.user_id != user.id:
        raise HTTPException(404)
    f.display_name = (display_name.strip() or f.subjects_key)[:200]
    f.kuerzel = kuerzel.strip()[:40]
    f.active = active == "1"
    db.commit()
    return RedirectResponse("/stammdaten/faecher", status_code=303)


@router.post("/stammdaten/faecher/{fid}/delete")
def faecher_delete(
    request: Request,
    fid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    f = db.get(TtFach, fid)
    if not f or f.user_id != user.id:
        raise HTTPException(404)
    benutzt = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.fach_id == f.id))
    if benutzt:
        f.active = False
        db.commit()
        return RedirectResponse(
            "/stammdaten/faecher?err=Fach+wird+im+Stundenplan+benutzt+"
            "und+wurde+nur+stillgelegt", status_code=303)
    key = f.subjects_key
    db.delete(f)
    audit(db, "tt_fach_deleted", actor=user, target=key, request=request)
    db.commit()
    return RedirectResponse("/stammdaten/faecher", status_code=303)
