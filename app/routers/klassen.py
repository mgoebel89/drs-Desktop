"""Klassen — die tägliche Arbeitsansicht: Übersicht, Klasse, Schüler.

Bewusst getrennt von den Stammdaten (`routers/students.py`): Dort wird
verwaltet (anlegen, importieren, versetzen, austragen), hier wird gearbeitet.
Die Schülerliste einer Klasse gibt es deshalb an beiden Stellen — mit
unterschiedlichem Zweck und unterschiedlichen Spalten. Die Daten sind
dieselben.

Die Notiz-Endpoints hängen an `/api/schueler/{sid}/notizen`, passend zu den
bestehenden Schüler-Endpoints in `routers/students.py`.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import Student, StudentNotiz, TtSchulklasse, User
from app.services import klassen as kl
from app.templating import templates

router = APIRouter()


def _klasse(db: Session, user: User, kid: int) -> TtSchulklasse:
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    return k


def _schueler(db: Session, user: User, sid: int) -> Student:
    s = db.get(Student, sid)
    if not s or s.owner_user_id != user.id:
        raise HTTPException(404)
    return s


def _notiz(db: Session, user: User, nid: int) -> StudentNotiz:
    n = db.get(StudentNotiz, nid)
    if not n or n.owner_user_id != user.id:
        raise HTTPException(404)
    return n


# ── Seiten ────────────────────────────────────────────────────────────────

@router.get("/klassen", response_class=HTMLResponse)
def klassen_uebersicht(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return templates.TemplateResponse(request, "klassen/index.html", {
        "kacheln": kl.uebersicht(db, user),
        "heute": date.today().isoformat(),
    })


# Diese Route MUSS vor `/klassen/{kid}` stehen — sonst versucht FastAPI,
# „schueler" als Klassen-ID zu lesen, und antwortet mit 422 statt der Seite.
@router.get("/klassen/schueler/{sid}", response_class=HTMLResponse)
def schueler_detail(
    request: Request,
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = _schueler(db, user, sid)
    klasse = db.get(TtSchulklasse, s.schulklasse_id) if s.schulklasse_id else None
    return templates.TemplateResponse(request, "klassen/schueler.html", {
        "s": s,
        "klasse": klasse,
        "notizen": [kl.notiz_dict(n) for n in kl.notizen(db, user, s.id)],
        "bewertungen": kl.bewertungen(db, user, s),
        "kategorien": kl.KATEGORIEN,
        "heute": date.today().isoformat(),
    })


@router.get("/klassen/{kid}", response_class=HTMLResponse)
def klasse_ansicht(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, kid)
    schueler = list(db.scalars(
        select(Student)
        .where(Student.owner_user_id == user.id, Student.schulklasse_id == k.id)
        .order_by(Student.nachname, Student.vorname)
    ).all())
    kennzahlen = kl.notiz_kennzahlen(db, user, [s.id for s in schueler])
    return templates.TemplateResponse(request, "klassen/klasse.html", {
        "k": k,
        "jahrgang": k.jahrgang,
        "zeilen": [{"s": s, "notizen": kennzahlen.get(s.id, {})}
                   for s in schueler],
        "lerngruppen": kl.lerngruppen_der_klasse(db, user, k.id),
        "kategorien": kl.KATEGORIEN,
        "heute": date.today().isoformat(),
    })


# ── Notizen ───────────────────────────────────────────────────────────────

@router.get("/api/schueler/{sid}/notizen")
def notizen_liste(
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = _schueler(db, user, sid)
    return JSONResponse({
        "ok": True,
        "notizen": [kl.notiz_dict(n) for n in kl.notizen(db, user, s.id)],
    })


@router.post("/api/schueler/{sid}/notizen")
def notiz_anlegen(
    request: Request,
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    s = _schueler(db, user, sid)
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Die Notiz braucht einen Text.")
    n = StudentNotiz(
        student_id=s.id,
        owner_user_id=user.id,
        datum=(payload.get("datum") or date.today().isoformat())[:10],
        kategorie=kl.normalize_kategorie(payload.get("kategorie")),
        text=text,
    )
    db.add(n)
    audit(db, "student_note_created", actor=user, target=str(s.id),
          detail=f"{s.nachname}, {s.vorname}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "notiz": kl.notiz_dict(n)})


@router.post("/api/schueler-notizen/{nid}/save")
def notiz_speichern(
    nid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    n = _notiz(db, user, nid)
    # Nur anfassen, was auch mitgeschickt wurde — sonst leert ein Teil-Update
    # die übrigen Felder (dieselbe Falle wie im Prüfungsformular).
    if "text" in payload:
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Die Notiz braucht einen Text.")
        n.text = text
    if "datum" in payload:
        n.datum = (payload.get("datum") or "")[:10]
    if "kategorie" in payload:
        n.kategorie = kl.normalize_kategorie(payload.get("kategorie"))
    db.commit()
    return JSONResponse({"ok": True, "notiz": kl.notiz_dict(n)})


@router.post("/api/schueler-notizen/{nid}/delete")
def notiz_loeschen(
    nid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    n = _notiz(db, user, nid)
    db.delete(n)
    db.commit()
    return JSONResponse({"ok": True})
