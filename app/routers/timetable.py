"""Stundenplan-Seite: zeigt die Lessons des Lehrers aus WebUntis."""
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import User
from app.services import webuntis_client
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
            "lessons": [], "monday": None, "friday": None, "prev_week": None, "next_week": None,
        })

    ref = _parse_iso_date(week)
    try:
        monday, friday, lessons = webuntis_client.get_week(user, ref)
        err = None
    except Exception as e:
        monday, friday, lessons = None, None, []
        err = f"{type(e).__name__}: {e}"

    return templates.TemplateResponse(request, "timetable.html", {
        "user": user, "error": err,
        "lessons": lessons, "monday": monday, "friday": friday,
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
