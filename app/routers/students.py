"""Schüler-Verwaltung pro Lehrer + Klasse."""
from __future__ import annotations

from typing import Annotated

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import Student, User
from app.services import moodle_csv
from app.templating import templates

router = APIRouter()


@router.get("/students", response_class=HTMLResponse)
def students_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    klasse: str = "",
):
    klassen = [
        row[0] for row in db.execute(
            select(Student.klassen_key)
            .where(Student.owner_user_id == user.id,
                   Student.klassen_key != "")
            .distinct()
            .order_by(Student.klassen_key)
        ).all()
    ]
    # Moodle-Importe haben klassen_key="" und tauchen hier nicht auf —
    # sie hängen ausschließlich an ihrer jeweiligen Prüfung.
    q = select(Student).where(Student.owner_user_id == user.id,
                              Student.klassen_key != "")
    if klasse:
        q = q.where(Student.klassen_key == klasse)
    q = q.order_by(Student.klassen_key, Student.nachname, Student.vorname)
    rows = db.scalars(q).all()

    return templates.TemplateResponse(request, "students/list.html", {
        "students": rows,
        "klassen": klassen,
        "filter_klasse": klasse,
    })


@router.post("/students")
def students_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    klassen_key: str = Form(...),
    nachname: str = Form(...),
    vorname: str = Form(""),
    email: str = Form(""),
):
    nachname = nachname.strip()[:120]
    if not nachname:
        raise HTTPException(400, "Nachname fehlt")
    s = Student(
        owner_user_id=user.id,
        klassen_key=klassen_key.strip()[:255],
        nachname=nachname,
        vorname=vorname.strip()[:120],
        email=email.strip()[:255],
    )
    db.add(s)
    audit(db, "student_added", actor=user, target=str(s.klassen_key),
          detail=f"{nachname}, {vorname}", request=request)
    db.commit()
    return RedirectResponse(
        f"/students?klasse={s.klassen_key}", status_code=303,
    )


@router.post("/students/import")
async def students_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    klassen_key: str = Form(...),
    file: UploadFile = File(...),
    overwrite: str = Form(""),
):
    klassen_key = klassen_key.strip()[:255]
    if not klassen_key:
        raise HTTPException(400, "Klasse fehlt")

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except Exception:
            raise HTTPException(400, "Datei konnte nicht als UTF-8 oder CP1252 gelesen werden")

    parsed, fmt = moodle_csv.parse_csv(text)
    if not parsed:
        return RedirectResponse(
            f"/students?klasse={klassen_key}&import_err=keine+Eintr%C3%A4ge+erkannt",
            status_code=303,
        )

    if overwrite == "1":
        # alte Klasse leeren
        db.query(Student).filter(
            Student.owner_user_id == user.id,
            Student.klassen_key == klassen_key,
        ).delete(synchronize_session=False)

    added = 0
    for p in parsed:
        # Duplikat-Schutz: gleicher Name in gleicher Klasse
        exists = db.query(Student.id).filter(
            Student.owner_user_id == user.id,
            Student.klassen_key == klassen_key,
            Student.nachname == p.nachname,
            Student.vorname == p.vorname,
        ).first()
        if exists:
            continue
        s = Student(
            owner_user_id=user.id,
            klassen_key=klassen_key,
            nachname=p.nachname[:120],
            vorname=p.vorname[:120],
            email=p.email[:255],
            moodle_id=p.moodle_id[:64],
        )
        db.add(s)
        added += 1

    audit(db, "students_imported", actor=user, target=klassen_key,
          detail=f"{added} hinzugefügt, format={fmt}", request=request)
    db.commit()
    return RedirectResponse(
        f"/students?klasse={klassen_key}&import_ok={added}&format={fmt}",
        status_code=303,
    )


@router.post("/students/{sid}/delete")
def students_delete(
    request: Request,
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = db.get(Student, sid)
    if not s or s.owner_user_id != user.id:
        raise HTTPException(404)
    klasse = s.klassen_key
    detail = f"{s.nachname}, {s.vorname}"
    db.delete(s)
    audit(db, "student_deleted", actor=user, target=klasse, detail=detail, request=request)
    db.commit()
    return RedirectResponse(f"/students?klasse={klasse}", status_code=303)
