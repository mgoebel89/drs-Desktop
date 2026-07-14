from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.routers import auth as auth_router
from app.routers import setup as setup_router
from app.routers import users as users_router
from app.routers import profile as profile_router
# Phase 1 (Verschlankung): Module ausgeblendet — Router bleiben im Code, werden aber
# nicht mehr gemountet. Aufräumen (Löschen) erfolgt in Phase 3.
# from app.routers import worksheets as worksheets_router
from app.routers import settings as settings_router
from app.routers import help as help_router
from app.routers import timetable as timetable_router
# from app.routers import preview as preview_router
# from app.routers import obsidian as obsidian_router
# from app.routers import learning_situations as ls_router
# from app.routers import lernfelder as lernfelder_router
# from app.routers import wizard as wizard_router
from app.routers import students as students_router
from app.routers import exams as exams_router
from app.routers import grading_scales as grading_scales_router
from app.routers import feedback_templates as feedback_templates_router
from app.routers import files as files_router
from app.routers import vikunja as vikunja_router
from app.routers import stammdaten as stammdaten_router
from app.routers import timetable_settings as timetable_settings_router
from app.models import Exam, LessonNote, User
from app.templating import templates
from datetime import date

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="DRS Unterrichtsmaterial")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(setup_router.router)
app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(profile_router.router)
# app.include_router(worksheets_router.router)   # Phase 1: ausgeblendet
app.include_router(settings_router.router)
app.include_router(help_router.router)
app.include_router(timetable_router.router)
# app.include_router(preview_router.router)       # Phase 1: ausgeblendet (LS/SMB-Vorschau)
# app.include_router(obsidian_router.router)      # Phase 1: ausgeblendet (LS)
# app.include_router(ls_router.router)            # Phase 1: ausgeblendet (Lernsituationen)
# app.include_router(lernfelder_router.router)    # Phase 1: ausgeblendet (LS-Stammdaten)
# app.include_router(wizard_router.router)        # Phase 1: ausgeblendet (Wizard)
app.include_router(students_router.router)
app.include_router(exams_router.router)
app.include_router(grading_scales_router.router)
app.include_router(feedback_templates_router.router)
app.include_router(files_router.router)
app.include_router(vikunja_router.router)
app.include_router(stammdaten_router.router)
app.include_router(timetable_settings_router.router)


@app.get("/")
def root(request: Request, db: Annotated[Session, Depends(get_db)]):
    # First-Run: solange noch kein Nutzer existiert, zur Setup-Seite leiten.
    if db.query(User.id).first() is None:
        return RedirectResponse(url="/setup", status_code=303)
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user.must_change_pw:
        return RedirectResponse(url="/change-password", status_code=303)

    today = date.today().isoformat()
    # Anstehende Prüfungen (datum als ISO-String, lexikografisch sortierbar)
    upcoming_exams = (
        db.query(Exam)
        .filter(Exam.owner_user_id == user.id, Exam.datum >= today, Exam.datum != "")
        .order_by(Exam.datum.asc())
        .limit(6)
        .all()
    )
    # Nächste Stunden mit gepflegter Notiz (Thema oder Notizen vorhanden)
    upcoming_notes = (
        db.query(LessonNote)
        .filter(
            LessonNote.user_id == user.id,
            LessonNote.lesson_date >= today,
            (LessonNote.theme != "") | (LessonNote.notes != ""),
        )
        .order_by(LessonNote.lesson_date.asc(), LessonNote.block_start.asc())
        .limit(6)
        .all()
    )
    return templates.TemplateResponse(request, "home.html", {
        "user": user,
        "upcoming_exams": upcoming_exams,
        "upcoming_notes": upcoming_notes,
    })


@app.get("/health")
def health():
    return {"status": "ok"}
