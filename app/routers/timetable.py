"""Stundenplan-Seite: zeigt die Lessons des Lehrers aus WebUntis.
Inklusive Lehrer-Notizen pro Stunde und iCal-Termine."""
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import IcalCalendar, LessonNote, User
from app.services import ical_client, webuntis_client
from app.templating import templates

router = APIRouter()


def _parse_iso_date(s: str | None) -> date:
    if not s:
        return date.today()
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return date.today()


@router.get("/timetable", response_class=HTMLResponse)
def timetable_view(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    week: str | None = None,
):
    if not user.untis_creds_enc:
        return templates.TemplateResponse(request, "timetable.html", {
            "user": user, "error": "Bitte hinterlege zuerst WebUntis-Zugangsdaten im Profil.",
            "grid": None, "prev_week": None, "next_week": None,
        })

    ref = _parse_iso_date(week)
    # iCal-Events aller aktiven Kalender vorab einsammeln
    ical_events: list[dict] = []
    ical_errors: list[str] = []
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    for cal in db.query(IcalCalendar).filter(
        IcalCalendar.user_id == user.id, IcalCalendar.enabled == True).all():  # noqa: E712
        evs, err_msg = ical_client.get_events_for_calendar(cal, monday, friday)
        if err_msg:
            ical_errors.append(f"{cal.label}: {err_msg}")
            cal.last_error = err_msg
        else:
            cal.last_error = ""
            ical_events.extend(evs)
    db.commit()

    try:
        grid = webuntis_client.get_week_grid(user, ref, ical_events=ical_events)
        err = None
    except Exception as e:
        grid = None
        err = f"{type(e).__name__}: {e}"
    if ical_errors and not err:
        err = " · ".join(ical_errors)

    # Notiz-Indikator: existieren Notizen für die Stunden dieser Woche?
    notes_present: set[tuple[str, str, str]] = set()
    if grid:
        keys_to_check = set()
        for (slot_start, day_idx), lessons in grid["cells"].items():
            d = grid["days"][day_idx]["date"].isoformat()
            for l in lessons:
                kk, sk = webuntis_client.lesson_key_parts(l)
                if kk or sk:
                    keys_to_check.add((d, kk, sk))
        if keys_to_check:
            rows = db.query(LessonNote.lesson_date, LessonNote.klassen_key,
                            LessonNote.subjects_key).filter(
                LessonNote.user_id == user.id,
                LessonNote.lesson_date >= monday.isoformat(),
                LessonNote.lesson_date <= friday.isoformat(),
            ).all()
            for d, kk, sk in rows:
                key = (d, kk or "", sk or "")
                # nur wenn überhaupt Inhalt vorhanden? Wir markieren wenn der
                # Datensatz existiert; leere Notizen löschen wir spätestens beim
                # Speichern wenn alle Felder leer sind.
                if key in keys_to_check:
                    notes_present.add(key)
        grid["notes_present"] = notes_present

    return templates.TemplateResponse(request, "timetable.html", {
        "user": user, "error": err, "grid": grid,
        "prev_week": (ref - timedelta(days=7)).isoformat(),
        "next_week": (ref + timedelta(days=7)).isoformat(),
        "this_week": date.today().isoformat(),
    })


@router.get("/timetable/diagnose", response_class=HTMLResponse)
def timetable_diagnose(
    request: Request,
    user: Annotated[User, Depends(require_user)],
):
    results = webuntis_client.diagnose(user)
    return templates.TemplateResponse(request, "timetable_diagnose.html",
                                      {"user": user, "results": results})


# ── Lehrer-Notizen pro Stunde ──────────────────────────────────────────────
def _note_dict(n: LessonNote | None) -> dict:
    if not n:
        return {"theme": "", "notes": "", "material": "", "remarks": ""}
    return {
        "theme": n.theme or "",
        "notes": n.notes or "",
        "material": n.material or "",
        "remarks": n.remarks or "",
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("/api/lesson-note")
def api_get_note(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    date: str,
    klassen: str = "",
    subjects: str = "",
):
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date == date,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
    ).first()
    return JSONResponse({"ok": True, "note": _note_dict(n)})


@router.post("/api/lesson-note")
def api_save_note(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    d = (body.get("date") or "").strip()
    if len(d) != 10:
        raise HTTPException(400, "Ungültiges Datum (YYYY-MM-DD).")
    kk = (body.get("klassen") or "")[:255]
    sk = (body.get("subjects") or "")[:255]
    theme = (body.get("theme") or "")[:500]
    notes = body.get("notes") or ""
    material = body.get("material") or ""
    remarks = body.get("remarks") or ""

    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id, LessonNote.lesson_date == d,
        LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
    ).first()

    # Wenn alle Felder leer → existierenden Datensatz löschen
    if not any([theme.strip(), notes.strip(), material.strip(), remarks.strip()]):
        if n:
            db.delete(n)
            db.commit()
        return JSONResponse({"ok": True, "deleted": True})

    if not n:
        n = LessonNote(
            user_id=user.id, lesson_date=d, klassen_key=kk, subjects_key=sk,
        )
        db.add(n)
    n.theme = theme
    n.notes = notes
    n.material = material
    n.remarks = remarks
    n.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "saved_at": n.updated_at.isoformat()})


@router.get("/api/lesson-note/previous")
def api_previous_note(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    before: str,
    klassen: str = "",
    subjects: str = "",
):
    """Letzte Notiz zur selben Klassen+Fach-Kombi vor dem 'before'-Datum."""
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
        LessonNote.lesson_date < before,
    ).order_by(LessonNote.lesson_date.desc()).first()
    if not n:
        return JSONResponse({"ok": True, "note": None})
    return JSONResponse({"ok": True, "note": {
        "date": n.lesson_date, **_note_dict(n),
    }})


@router.get("/api/timetable/today")
def api_today(
    user: Annotated[User, Depends(require_user)],
):
    """JSON-Endpoint für Editor: heutige Stunden des Nutzers."""
    if not user.untis_creds_enc:
        return JSONResponse({"ok": False, "error": "Keine WebUntis-Credentials hinterlegt."},
                            status_code=400)
    try:
        lessons = webuntis_client.get_current_day(user)
        return JSONResponse({"ok": True, "lessons": lessons})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=502)
