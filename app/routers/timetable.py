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
from app.models import IcalCalendar, LessonNote, LessonSeriesOverride, User
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

    # Notiz-Status + Subject-Override für die Stunden dieser Woche aufbauen
    # Key nun mit block_start: (date, klassen_key, subjects_key, block_start)
    notes_present: set[tuple[str, str, str, str]] = set()
    exams: set[tuple[str, str, str, str]] = set()
    session_override: dict[tuple[str, str, str, str], str] = {}
    series_override: dict[tuple[str, str], str] = {}

    if grid:
        keys_series = set()
        for (slot_start, day_idx), lessons in grid["cells"].items():
            for l in lessons:
                kk, sk = webuntis_client.lesson_key_parts(l)
                if kk or sk:
                    keys_series.add((kk, sk))
        if keys_series:
            for so in db.query(LessonSeriesOverride).filter(
                LessonSeriesOverride.user_id == user.id,
            ).all():
                if (so.klassen_key, so.subjects_key) in keys_series and so.display_name.strip():
                    series_override[(so.klassen_key, so.subjects_key)] = so.display_name

        rows = db.query(
            LessonNote.lesson_date, LessonNote.klassen_key, LessonNote.subjects_key,
            LessonNote.block_start, LessonNote.theme, LessonNote.notes,
            LessonNote.material, LessonNote.remarks, LessonNote.subject_override,
            LessonNote.is_exam,
        ).filter(
            LessonNote.user_id == user.id,
            LessonNote.lesson_date >= monday.isoformat(),
            LessonNote.lesson_date <= friday.isoformat(),
        ).all()
        for d, kk, sk, bs, theme, notes, material, remarks, sov, ex in rows:
            key = (d, kk or "", sk or "", bs or "")
            if any([theme, notes, material, remarks, sov]):
                notes_present.add(key)
            if ex:
                exams.add(key)
            if (sov or "").strip():
                session_override[key] = sov

        grid["notes_present"] = notes_present
        grid["exams"] = exams
        grid["session_override"] = session_override
        grid["series_override"] = series_override

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
        return {"theme": "", "notes": "", "material": "", "remarks": "",
                "subject_override": "", "is_exam": False}
    return {
        "theme": n.theme or "",
        "notes": n.notes or "",
        "material": n.material or "",
        "remarks": n.remarks or "",
        "subject_override": n.subject_override or "",
        "is_exam": bool(n.is_exam),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _series_default(db: Session, user_id: int, kk: str, sk: str) -> str:
    so = db.query(LessonSeriesOverride).filter(
        LessonSeriesOverride.user_id == user_id,
        LessonSeriesOverride.klassen_key == kk,
        LessonSeriesOverride.subjects_key == sk,
    ).first()
    return (so.display_name or "") if so else ""


@router.get("/api/lesson-note")
def api_get_note(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    date: str,
    klassen: str = "",
    subjects: str = "",
    block_start: str = "",
):
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date == date,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
        LessonNote.block_start == block_start,
    ).first()
    return JSONResponse({
        "ok": True,
        "note": _note_dict(n),
        "series_default": _series_default(db, user.id, klassen, subjects),
    })


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
    bs = (body.get("block_start") or "")[:5]
    theme = (body.get("theme") or "")[:500]
    notes = body.get("notes") or ""
    material = body.get("material") or ""
    remarks = body.get("remarks") or ""
    subject_override = (body.get("subject_override") or "")[:200]
    is_exam = bool(body.get("is_exam"))

    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id, LessonNote.lesson_date == d,
        LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
        LessonNote.block_start == bs,
    ).first()

    is_blank = not any([theme.strip(), notes.strip(), material.strip(),
                        remarks.strip(), subject_override.strip(), is_exam])
    if is_blank:
        if n:
            db.delete(n)
            db.commit()
        return JSONResponse({"ok": True, "deleted": True})

    if not n:
        n = LessonNote(
            user_id=user.id, lesson_date=d, klassen_key=kk,
            subjects_key=sk, block_start=bs,
        )
        db.add(n)
    n.theme = theme
    n.notes = notes
    n.material = material
    n.remarks = remarks
    n.subject_override = subject_override
    n.is_exam = is_exam
    n.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "saved_at": n.updated_at.isoformat()})


# ── Reihen-Override (Fach-Bezeichnung pro Klassen+Fach-Kombi) ─────────────
@router.get("/api/lesson-series-override")
def api_get_series(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    klassen: str = "",
    subjects: str = "",
):
    return JSONResponse({
        "ok": True,
        "display_name": _series_default(db, user.id, klassen, subjects),
    })


@router.post("/api/lesson-series-override")
def api_save_series(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    kk = (body.get("klassen") or "")[:255]
    sk = (body.get("subjects") or "")[:255]
    dn = (body.get("display_name") or "").strip()[:200]

    so = db.query(LessonSeriesOverride).filter(
        LessonSeriesOverride.user_id == user.id,
        LessonSeriesOverride.klassen_key == kk,
        LessonSeriesOverride.subjects_key == sk,
    ).first()

    if not dn:
        if so:
            db.delete(so)
            db.commit()
        return JSONResponse({"ok": True, "deleted": True})

    if not so:
        so = LessonSeriesOverride(
            user_id=user.id, klassen_key=kk, subjects_key=sk, display_name=dn,
        )
        db.add(so)
    else:
        so.display_name = dn
        so.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "display_name": dn})


@router.get("/api/lesson-note/previous")
def api_previous_note(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    before: str,
    klassen: str = "",
    subjects: str = "",
    block_start: str = "",
):
    """Letzte Notiz zur selben Klassen+Fach-Kombi vor dem 'before'-Datum.
    Bevorzugt denselben Block; wenn dort nichts gefunden wird, fällt zurück
    auf irgendeinen Block derselben Klassen+Fach-Kombi."""
    base_q = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
        LessonNote.lesson_date < before,
    )
    n = None
    if block_start:
        n = base_q.filter(LessonNote.block_start == block_start)\
            .order_by(LessonNote.lesson_date.desc()).first()
    if not n:
        n = base_q.order_by(LessonNote.lesson_date.desc()).first()
    if not n:
        return JSONResponse({"ok": True, "note": None})
    return JSONResponse({"ok": True, "note": {
        "date": n.lesson_date, "block_start": n.block_start, **_note_dict(n),
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
