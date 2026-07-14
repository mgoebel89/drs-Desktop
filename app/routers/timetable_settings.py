"""Stundenplan-Einstellungen (pro Lehrer): Zeitraster, Schuljahr, Ferien.

Bewusst NICHT unter /admin — der Stundenplan ist die Sache des einzelnen Lehrers.
Die einmaligen Änderungen (Ausfall, Vertretung, …) gehören NICHT hierher; die
werden per Rechtsklick direkt im Grid gemacht.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import LessonNote, TtHoliday, TtSchoolyear, TtSlot, User
from app.services import schulkalender
from app.templating import templates

router = APIRouter()

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_time(value: str, feld: str) -> str:
    v = (value or "").strip()
    if not _HHMM.match(v):
        raise HTTPException(400, f"{feld}: Uhrzeit muss HH:MM sein (z. B. 07:55).")
    return v


def _check_date(value: str, feld: str) -> str:
    v = (value or "").strip()
    try:
        date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"{feld}: Datum fehlt oder ist ungültig.")
    return v


def _orphan_report(db: Session, user: User) -> dict[str, list[str]]:
    """Bestandsnotizen, deren Schlüssel in keinem Stammdatensatz bzw. keinem Slot
    vorkommen — die hingen dann im neuen Plan an keiner Stunde mehr."""
    from app.models import TtFach, TtKlasse

    kk_stamm = {k for (k,) in db.execute(
        select(TtKlasse.klassen_key).where(TtKlasse.user_id == user.id)).all()}
    sk_stamm = {s for (s,) in db.execute(
        select(TtFach.subjects_key).where(TtFach.user_id == user.id)).all()}
    bs_stamm = {b for (b,) in db.execute(
        select(TtSlot.start_time).where(TtSlot.user_id == user.id)).all()}

    kk_notiz = {k for (k,) in db.execute(
        select(LessonNote.klassen_key).distinct()
        .where(LessonNote.user_id == user.id, LessonNote.klassen_key != "")).all()}
    sk_notiz = {s for (s,) in db.execute(
        select(LessonNote.subjects_key).distinct()
        .where(LessonNote.user_id == user.id, LessonNote.subjects_key != "")).all()}
    bs_notiz = {b for (b,) in db.execute(
        select(LessonNote.block_start).distinct()
        .where(LessonNote.user_id == user.id, LessonNote.block_start != "")).all()}

    return {
        "klassen": sorted(kk_notiz - kk_stamm),
        "faecher": sorted(sk_notiz - sk_stamm),
        "bloecke": sorted(bs_notiz - bs_stamm),
    }


def _view_ctx(db: Session, user: User) -> dict:
    slots = db.scalars(
        select(TtSlot).where(TtSlot.user_id == user.id)
        .order_by(TtSlot.position, TtSlot.start_time)
    ).all()
    sy = db.scalars(
        select(TtSchoolyear).where(TtSchoolyear.user_id == user.id)
        .order_by(TtSchoolyear.first_day.desc())
    ).first()
    holidays = db.scalars(
        select(TtHoliday).where(TtHoliday.user_id == user.id)
        .order_by(TtHoliday.start_date)
    ).all()

    # Feiertage des Schuljahres (berechnet, read-only)
    feiertage: list[tuple[str, str]] = []
    if sy and sy.first_day and sy.last_day:
        try:
            von = date.fromisoformat(sy.first_day)
            bis = date.fromisoformat(sy.last_day)
            for jahr in range(von.year, bis.year + 1):
                for tag, name in sorted(schulkalender.feiertage_rlp(jahr).items()):
                    if von <= tag <= bis and tag.weekday() < 5:
                        feiertage.append((tag.strftime("%a %d.%m.%Y"), name))
        except ValueError:
            pass

    # A/B-Vorschau: macht u. a. sichtbar, dass am Jahreswechsel (KW 53 → KW 1)
    # zwei gleichnamige Wochen aufeinander folgen können.
    vorschau = []
    if sy:
        heute = date.today()
        montag = heute - timedelta(days=heute.weekday())
        for i in range(12):
            mo = montag + timedelta(weeks=i)
            vorschau.append({
                "kw": mo.isocalendar().week,
                "montag": mo.strftime("%d.%m."),
                "ab": schulkalender.ab_for_week(mo, sy.a_week_parity),
            })

    return {
        "slots": slots,
        "schoolyear": sy,
        "holidays": holidays,
        "feiertage": feiertage,
        "ab_vorschau": vorschau,
        "orphans": _orphan_report(db, user),
    }


@router.get("/timetable/settings", response_class=HTMLResponse)
def settings_view(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return templates.TemplateResponse(
        request, "timetable/settings.html", _view_ctx(db, user))


# ── Zeitraster ───────────────────────────────────────────────────────────

@router.post("/timetable/settings/slots")
def slot_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(""),
    start_time: str = Form(...),
    end_time: str = Form(...),
):
    start = _check_time(start_time, "Beginn")
    ende = _check_time(end_time, "Ende")
    if ende <= start:
        raise HTTPException(400, "Das Ende muss nach dem Beginn liegen.")
    doppelt = db.scalar(select(TtSlot.id).where(
        TtSlot.user_id == user.id, TtSlot.start_time == start))
    if doppelt:
        return RedirectResponse(
            "/timetable/settings?err=Ein+Block+mit+dieser+Startzeit+existiert+schon",
            status_code=303)
    pos = db.scalar(select(func.count()).select_from(TtSlot)
                    .where(TtSlot.user_id == user.id)) or 0
    db.add(TtSlot(user_id=user.id, position=pos,
                  name=name.strip()[:20] or f"Block {pos + 1}",
                  start_time=start, end_time=ende))
    audit(db, "tt_slot_added", actor=user, target=start, request=request)
    db.commit()
    return RedirectResponse("/timetable/settings#zeitraster", status_code=303)


@router.post("/timetable/settings/slots/{sid}")
def slot_edit(
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(""),
    end_time: str = Form(...),
    position: int = Form(0),
):
    s = db.get(TtSlot, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    # start_time bleibt unangetastet: sie ist der block_start in key4, an dem die
    # bestehenden Stundennotizen hängen.
    s.name = name.strip()[:20] or s.name
    s.end_time = _check_time(end_time, "Ende")
    s.position = position
    db.commit()
    return RedirectResponse("/timetable/settings#zeitraster", status_code=303)


@router.post("/timetable/settings/slots/{sid}/delete")
def slot_delete(
    request: Request,
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = db.get(TtSlot, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    # Notizen an diesem Block warnen, aber nicht blockieren — der Block
    # verschwindet nur aus der Anzeige, die Notizen bleiben in der DB.
    n = db.scalar(select(func.count()).select_from(LessonNote).where(
        LessonNote.user_id == user.id, LessonNote.block_start == s.start_time)) or 0
    start = s.start_time
    db.delete(s)
    audit(db, "tt_slot_deleted", actor=user, target=start,
          detail=f"{n} Notizen an diesem Block", request=request)
    db.commit()
    warn = (f"&warn=Achtung:+{n}+Notizen+hingen+an+diesem+Block+und+sind+jetzt+"
            "nicht+mehr+sichtbar") if n else ""
    return RedirectResponse(
        f"/timetable/settings?ok=1{warn}#zeitraster", status_code=303)


# ── Schuljahr + A/B-Regel ────────────────────────────────────────────────

@router.post("/timetable/settings/schoolyear")
def schoolyear_save(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    sy_id: int = Form(0),
    name: str = Form(""),
    first_day: str = Form(...),
    last_day: str = Form(...),
    halfyear_split: str = Form(""),
    a_week_parity: str = Form("even"),
):
    von = _check_date(first_day, "Erster Schultag")
    bis = _check_date(last_day, "Letzter Schultag")
    if bis <= von:
        raise HTTPException(400, "Der letzte Schultag muss nach dem ersten liegen.")
    split = halfyear_split.strip()
    if split:
        split = _check_date(split, "Beginn 2. Halbjahr")
        if not (von < split <= bis):
            raise HTTPException(
                400, "Der Beginn des 2. Halbjahres muss im Schuljahr liegen.")
    if a_week_parity not in ("even", "odd"):
        a_week_parity = "even"

    sy = db.get(TtSchoolyear, sy_id) if sy_id else None
    if sy and sy.user_id != user.id:
        raise HTTPException(404)
    if not sy:
        sy = TtSchoolyear(user_id=user.id)
        db.add(sy)
    sy.name = name.strip()[:40] or f"{von[:4]}/{bis[2:4]}"
    sy.first_day = von
    sy.last_day = bis
    sy.halfyear_split = split
    sy.a_week_parity = a_week_parity
    audit(db, "tt_schoolyear_saved", actor=user, target=sy.name, request=request)
    db.commit()
    return RedirectResponse("/timetable/settings#schuljahr", status_code=303)


# ── Ferien / bewegliche Ferientage ───────────────────────────────────────

@router.post("/timetable/settings/holidays")
def holiday_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(""),
    kind: str = Form("ferien"),
):
    von = _check_date(start_date, "Von")
    bis = _check_date(end_date, "Bis") if end_date.strip() else von
    if bis < von:
        raise HTTPException(400, "Das Enddatum liegt vor dem Startdatum.")
    db.add(TtHoliday(
        user_id=user.id, name=name.strip()[:120] or "Ferien",
        start_date=von, end_date=bis,
        kind=kind if kind in ("ferien", "beweglich") else "ferien",
    ))
    audit(db, "tt_holiday_added", actor=user, target=f"{von}..{bis}",
          detail=name.strip()[:120], request=request)
    db.commit()
    return RedirectResponse("/timetable/settings#ferien", status_code=303)


@router.post("/timetable/settings/holidays/{hid}/delete")
def holiday_delete(
    request: Request,
    hid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    h = db.get(TtHoliday, hid)
    if not h or h.user_id != user.id:
        raise HTTPException(404)
    label = h.name
    db.delete(h)
    audit(db, "tt_holiday_deleted", actor=user, target=label, request=request)
    db.commit()
    return RedirectResponse("/timetable/settings#ferien", status_code=303)
