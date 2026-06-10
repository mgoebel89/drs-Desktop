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
from app.models import (
    Exam, IcalCalendar, LearningSituation, LessonNote, LessonNoteAufgabe,
    LessonSeriesOverride, LsAufgabe, User,
)
from app.services import aufgabe_sync, ical_client, webuntis_client
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
        import logging
        logging.getLogger(__name__).warning(
            "Stundenplan %s nicht ladbar: %s", ref.isoformat(), e, exc_info=True,
        )
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

        # Aufgaben-Marker pro Block: {(d,kk,sk,bs): "Aufg. 2, 3"}
        aufgaben_markers: dict[tuple[str, str, str, str], str] = {}
        rows_a = db.query(
            LessonNote.lesson_date, LessonNote.klassen_key, LessonNote.subjects_key,
            LessonNote.block_start, LsAufgabe.nummer,
        ).join(
            LessonNoteAufgabe, LessonNoteAufgabe.lesson_note_id == LessonNote.id,
        ).join(
            LsAufgabe, LsAufgabe.id == LessonNoteAufgabe.ls_aufgabe_id,
        ).filter(
            LessonNote.user_id == user.id,
            LessonNote.lesson_date >= monday.isoformat(),
            LessonNote.lesson_date <= friday.isoformat(),
        ).order_by(
            LessonNote.lesson_date, LsAufgabe.nummer,
        ).all()
        bucket: dict[tuple[str, str, str, str], list[int]] = {}
        for d, kk, sk, bs, num in rows_a:
            key = (d, kk or "", sk or "", bs or "")
            bucket.setdefault(key, []).append(num)
        for key, nums in bucket.items():
            aufgaben_markers[key] = "Aufg. " + ", ".join(str(n) for n in nums)
        grid["aufgaben_markers"] = aufgaben_markers

    return templates.TemplateResponse(request, "timetable.html", {
        "user": user, "error": err, "grid": grid,
        "prev_week": (ref - timedelta(days=7)).isoformat(),
        "next_week": (ref + timedelta(days=7)).isoformat(),
        "this_week": date.today().isoformat(),
    })


_WEEKDAY_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


_md_renderer = None


def _md_to_html(text: str) -> str:
    """Rendert die Blocknotizen (Markdown) als HTML für den Arbeitsplan-PDF.

    Nutzt markdown-it-py wie das Obsidian-Notizen-Rendering. Falls keine
    Eingabe vorliegt → leerer String."""
    if not text or not text.strip():
        return ""
    global _md_renderer
    if _md_renderer is None:
        from markdown_it import MarkdownIt
        _md_renderer = (
            MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
            .enable("table").enable("strikethrough")
        )
    return _md_renderer.render(text)


def _collect_week_plan(db: Session, user: User, ref: date) -> dict:
    """Sammelt alle Daten für den Wochen-Arbeitsplan (PDF).

    Liefert {monday, friday, days: [{label, ical, rows}]}. Nur Tage mit
    Unterricht (oder iCal-Terminen) erscheinen. Pro Block eine Zeile je
    Lesson; Blöcke ohne Notiz behalten leere Inhaltsfelder."""
    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)

    ical_events: list[dict] = []
    for cal in db.query(IcalCalendar).filter(
        IcalCalendar.user_id == user.id, IcalCalendar.enabled == True).all():  # noqa: E712
        evs, err_msg = ical_client.get_events_for_calendar(cal, monday, friday)
        if not err_msg:
            ical_events.extend(evs)

    grid = webuntis_client.get_week_grid(user, ref, ical_events=ical_events)

    # Blocknotizen der Woche (Volltext) als Map
    note_map: dict[tuple[str, str, str, str], dict] = {}
    note_ls: dict[tuple[str, str, str, str], int | None] = {}
    note_ids: dict[tuple[str, str, str, str], int] = {}
    for n in db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date >= monday.isoformat(),
        LessonNote.lesson_date <= friday.isoformat(),
    ).all():
        key = (n.lesson_date, n.klassen_key or "", n.subjects_key or "",
               n.block_start or "")
        note_map[key] = {
            "theme": n.theme or "", "notes": n.notes or "",
            "material": n.material or "", "remarks": n.remarks or "",
            "subject_override": n.subject_override or "",
            "is_exam": bool(n.is_exam),
        }
        note_ls[key] = n.learning_situation_id
        note_ids[key] = n.id

    # Reihen-Fachnamen
    series_override: dict[tuple[str, str], str] = {}
    for so in db.query(LessonSeriesOverride).filter(
        LessonSeriesOverride.user_id == user.id,
    ).all():
        if so.display_name.strip():
            series_override[(so.klassen_key, so.subjects_key)] = so.display_name

    # LS-Namen + Aufgaben-Marker
    ls_names: dict[int, str] = {}
    ls_ids = {v for v in note_ls.values() if v}
    if ls_ids:
        for ls in db.query(LearningSituation).filter(
            LearningSituation.id.in_(ls_ids)).all():
            ls_names[ls.id] = ls.display_name

    aufgaben_markers: dict[tuple[str, str, str, str], str] = {}
    rows_a = db.query(
        LessonNote.lesson_date, LessonNote.klassen_key, LessonNote.subjects_key,
        LessonNote.block_start, LsAufgabe.nummer,
    ).join(
        LessonNoteAufgabe, LessonNoteAufgabe.lesson_note_id == LessonNote.id,
    ).join(
        LsAufgabe, LsAufgabe.id == LessonNoteAufgabe.ls_aufgabe_id,
    ).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date >= monday.isoformat(),
        LessonNote.lesson_date <= friday.isoformat(),
    ).order_by(LessonNote.lesson_date, LsAufgabe.nummer).all()
    bucket_a: dict[tuple[str, str, str, str], list[int]] = {}
    for d, kk, sk, bs, num in rows_a:
        bucket_a.setdefault((d, kk or "", sk or "", bs or ""), []).append(num)
    for key, nums in bucket_a.items():
        aufgaben_markers[key] = "Aufg. " + ", ".join(str(n) for n in nums)

    # Prüfungen der Woche
    week_exams = db.query(Exam).filter(
        Exam.owner_user_id == user.id,
        Exam.datum >= monday.isoformat(),
        Exam.datum <= friday.isoformat(),
    ).all()
    exams_by_note_id: dict[int, str] = {}
    exams_by_day_class: list[tuple[str, set[str], str]] = []
    for exm in week_exams:
        if exm.lesson_note_id:
            exams_by_note_id[exm.lesson_note_id] = exm.title
        classes = {c.strip() for c in (exm.klassen_key or "").split(",") if c.strip()}
        exams_by_day_class.append((exm.datum, classes, exm.title))

    # Tage aufbauen
    days_out: list[dict] = []
    for day_idx in range(5):
        d = monday + timedelta(days=day_idx)
        d_iso = d.isoformat()

        ical_lines: list[str] = []
        for ev in grid.get("all_day_row", {}).get(day_idx, []):
            ical_lines.append(f"Ganztägig: {ev.get('summary', '')}")
        for (slot_start, di), evs in grid.get("events", {}).items():
            if di != day_idx:
                continue
            for ev in evs:
                ical_lines.append(
                    f"{ev.get('start_time', '')}–{ev.get('end_time', '')} "
                    f"{ev.get('summary', '')}")

        rows: list[dict] = []
        for sl in grid["slots"]:
            lessons = grid["cells"].get((sl["start"], day_idx)) or []
            for i, l in enumerate(lessons):
                kk, sk = webuntis_client.lesson_key_parts(l)
                key = (d_iso, kk, sk, sl["start"])
                note = note_map.get(key, {})
                fach = (note.get("subject_override")
                        or series_override.get((kk, sk))
                        or " / ".join(l.get("subjects_long")
                                      or l.get("subjects") or []))
                ls_id = note_ls.get(key)
                pruefung = ""
                note_id = note_ids.get(key)
                if note_id and note_id in exams_by_note_id:
                    pruefung = exams_by_note_id[note_id]
                else:
                    lesson_classes = set(l.get("klassen") or [])
                    for exd, classes, title in exams_by_day_class:
                        if exd == d_iso and (classes & lesson_classes):
                            pruefung = title
                            break
                if not pruefung and note.get("is_exam"):
                    pruefung = "✓ Prüfung"
                rows.append({
                    "block": sl["name"] if i == 0 else "",
                    "zeit": f"{sl['start']}–{sl['end']}" if i == 0 else "",
                    "klasse": ", ".join(l.get("klassen") or []),
                    "fach": fach,
                    "thema": note.get("theme", ""),
                    "notizen_html": _md_to_html(note.get("notes", "")),
                    "material": note.get("material", ""),
                    "bemerkungen": note.get("remarks", ""),
                    "ls_name": ls_names.get(ls_id, "") if ls_id else "",
                    "aufgaben": aufgaben_markers.get(key, ""),
                    "pruefung": pruefung,
                })

        if rows or ical_lines:
            days_out.append({
                "label": f"{_WEEKDAY_LONG[day_idx]}, {d.strftime('%d.%m.%Y')}",
                "ical": ical_lines,
                "rows": rows,
            })

    return {"monday": monday, "friday": friday, "days": days_out}


@router.get("/timetable/arbeitsplan.pdf")
async def timetable_arbeitsplan_pdf(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    week: str | None = None,
):
    """Wochen-Arbeitsplan als A4-PDF: pro Tag eine Tabelle mit Block,
    Klasse, Fach, geplantem Inhalt, LS/Aufgaben und Prüfungen."""
    from fastapi.responses import Response
    from urllib.parse import quote

    from app import branding
    from app.auth import audit
    from app.services.playwright_pdf import render_pdf

    if not user.untis_creds_enc:
        raise HTTPException(400, "Keine WebUntis-Zugangsdaten hinterlegt")
    ref = _parse_iso_date(week)
    plan = _collect_week_plan(db, user, ref)

    html = templates.get_template("timetable/arbeitsplan_pdf.html").render({
        "request": request,
        "days": plan["days"],
        "monday": plan["monday"],
        "friday": plan["friday"],
        "lehrer_name": user.full_name or user.username,
        "school_logo_data_url": branding.logo_data_url(db),
        "school_name_value": branding.get_school_name(db),
    })
    pdf_bytes = await render_pdf(html)

    audit(db, "arbeitsplan_pdf", actor=user,
          target=plan["monday"].isoformat(), request=request)
    db.commit()

    filename = f"arbeitsplan_{plan['monday'].isoformat()}.pdf"
    # Inline-Disposition → Browser zeigt das PDF als Vorschau; das
    # eingebaute PDF-Viewer-UI bietet darin einen Download-Knopf.
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{quote(filename)}"'},
    )


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


# ── Aufgaben aus Lernsituationen pro Block ───────────────────────────────
@router.get("/api/lesson-note/aufgaben")
def api_get_block_aufgaben(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    date: str,
    klassen: str = "",
    subjects: str = "",
    block_start: str = "",
):
    """Liefert verfügbare LS für diese Klasse + Aufgaben + aktuelle Auswahl."""
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date == date,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
        LessonNote.block_start == block_start,
    ).first()

    selected_ls_id = n.learning_situation_id if n else None
    selected_aufgabe_ids: list[int] = []
    if n:
        selected_aufgabe_ids = [
            ena.ls_aufgabe_id for ena in db.query(LessonNoteAufgabe)
            .filter(LessonNoteAufgabe.lesson_note_id == n.id)
            .order_by(LessonNoteAufgabe.position).all()
        ]

    # LS dieses Lehrers, bevorzugt für die Klasse — sonst alle
    ls_q = db.query(LearningSituation).filter(LearningSituation.user_id == user.id)
    if klassen:
        prefer = ls_q.filter(
            (LearningSituation.klassen_key == klassen) |
            (LearningSituation.klassen_key == "")
        ).order_by(LearningSituation.updated_at.desc()).all()
    else:
        prefer = ls_q.order_by(LearningSituation.updated_at.desc()).all()

    ls_options = [
        {"id": ls.id, "display_name": ls.display_name,
         "klassen_key": ls.klassen_key, "lernfeld": ls.lernfeld}
        for ls in prefer
    ]

    aufgaben: list[dict] = []
    if selected_ls_id:
        ls = db.get(LearningSituation, selected_ls_id)
        if ls and ls.user_id == user.id:
            # Sync sicherstellen (best-effort)
            try:
                aufgabe_sync.sync_from_md(db, user, ls)
                db.commit()
            except Exception:
                db.rollback()
            for a in db.query(LsAufgabe).filter(
                LsAufgabe.learning_situation_id == selected_ls_id
            ).order_by(LsAufgabe.nummer).all():
                # Body + Lösungsskizze on-demand
                p = aufgabe_sync.get_aufgabe_md(user, ls, a.nummer)
                aufgaben.append({
                    "id": a.id, "nummer": a.nummer, "titel": a.titel,
                    "anchor": a.anchor, "phasen": a.phasen,
                    "body": (p or {}).get("body", ""),
                    "loesungsskizze": (p or {}).get("loesungsskizze", ""),
                })

    return JSONResponse({
        "ok": True,
        "ls_options": ls_options,
        "selected_ls_id": selected_ls_id,
        "selected_aufgabe_ids": selected_aufgabe_ids,
        "aufgaben": aufgaben,
    })


@router.post("/api/lesson-note/aufgaben")
def api_save_block_aufgaben(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    d = (body.get("date") or "").strip()
    if len(d) != 10:
        raise HTTPException(400, "Ungültiges Datum")
    kk = (body.get("klassen") or "")[:255]
    sk = (body.get("subjects") or "")[:255]
    bs = (body.get("block_start") or "")[:5]
    ls_id_raw = body.get("ls_id")
    aufgabe_ids = body.get("aufgabe_ids") or []

    ls_id: int | None = None
    if ls_id_raw not in (None, "", 0):
        try:
            ls_id = int(ls_id_raw)
        except Exception:
            raise HTTPException(400, "Ungültige ls_id")
        ls = db.get(LearningSituation, ls_id)
        if not ls or ls.user_id != user.id:
            raise HTTPException(404, "LS nicht gefunden")

    # lesson_note finden oder anlegen
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id, LessonNote.lesson_date == d,
        LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
        LessonNote.block_start == bs,
    ).first()
    if not n:
        n = LessonNote(
            user_id=user.id, lesson_date=d, klassen_key=kk,
            subjects_key=sk, block_start=bs,
        )
        db.add(n)
        db.flush()

    n.learning_situation_id = ls_id

    # Alte M2M-Einträge wegräumen
    db.query(LessonNoteAufgabe).filter(
        LessonNoteAufgabe.lesson_note_id == n.id
    ).delete(synchronize_session=False)

    # Neue setzen (nur Aufgaben, die zur gewählten LS gehören)
    if ls_id and aufgabe_ids:
        valid_ids = {
            row.id for row in db.query(LsAufgabe).filter(
                LsAufgabe.learning_situation_id == ls_id
            ).all()
        }
        for pos, aid in enumerate(aufgabe_ids):
            try:
                aid_int = int(aid)
            except Exception:
                continue
            if aid_int in valid_ids:
                db.add(LessonNoteAufgabe(
                    lesson_note_id=n.id, ls_aufgabe_id=aid_int, position=pos,
                ))

    db.commit()
    return JSONResponse({"ok": True})


@router.get("/api/lesson-note/exams")
def api_get_block_exams(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    date: str,
    klassen: str = "",
    subjects: str = "",
    block_start: str = "",
):
    """Liefert Prüfungen für diese Klasse mit Datum-Markierung."""
    n = db.query(LessonNote).filter(
        LessonNote.user_id == user.id,
        LessonNote.lesson_date == date,
        LessonNote.klassen_key == klassen,
        LessonNote.subjects_key == subjects,
        LessonNote.block_start == block_start,
    ).first()
    note_id = n.id if n else None

    # Prüfungen mit klassen_key == klassen ODER explizit zu diesem note verknüpft
    q = db.query(Exam).filter(Exam.owner_user_id == user.id)
    if klassen:
        from sqlalchemy import or_
        q = q.filter(or_(Exam.klassen_key == klassen, Exam.lesson_note_id == note_id))
    exams = q.order_by(Exam.datum.desc()).limit(20).all()

    items = []
    for e in exams:
        items.append({
            "id": e.id,
            "title": e.title,
            "datum": e.datum,
            "klassen_key": e.klassen_key,
            "this_block": (e.lesson_note_id == note_id) if note_id else False,
            "this_date": (e.datum == date),
        })
    return JSONResponse({"ok": True, "exams": items})


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
