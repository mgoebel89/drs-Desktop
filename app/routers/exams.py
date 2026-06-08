"""Prüfungen / Bewertungen — CRUD + 4-Tab-Edit + Export."""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (Exam, ExamFeedbackPoint, ExamResult, LearningSituation,
                        Student, User)
from app.services import grading
from app.templating import templates

router = APIRouter()


def _get_exam(db: Session, user: User, ex_id: int) -> Exam:
    ex = db.get(Exam, ex_id)
    if not ex or ex.owner_user_id != user.id:
        raise HTTPException(404)
    return ex


@router.get("/exams", response_class=HTMLResponse)
def exams_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(Exam).where(Exam.owner_user_id == user.id)
        .order_by(Exam.datum.desc(), Exam.id.desc())
    ).all()
    # Anzahl SuS für die Anzeige
    summary = []
    for e in rows:
        n_results = db.scalar(
            select(ExamResult.id).where(ExamResult.exam_id == e.id).limit(1)
        )
        n_students = db.scalar(
            select(Student.id)
            .where(Student.owner_user_id == user.id,
                   Student.klassen_key == e.klassen_key,
                   Student.active.is_(True))
            .limit(1)
        )
        summary.append({"exam": e, "has_results": bool(n_results),
                        "has_students": bool(n_students)})
    return templates.TemplateResponse(request, "exams/list.html", {
        "items": summary,
    })


@router.get("/exams/new", response_class=HTMLResponse)
def exams_new_form(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    ls_id: int | None = None,
):
    ls_options = db.scalars(
        select(LearningSituation).where(LearningSituation.user_id == user.id)
        .order_by(LearningSituation.updated_at.desc())
    ).all()
    klassen = [
        row[0] for row in db.execute(
            select(Student.klassen_key)
            .where(Student.owner_user_id == user.id)
            .distinct()
        ).all()
    ]
    prefill_ls: LearningSituation | None = None
    if ls_id:
        prefill_ls = db.get(LearningSituation, ls_id)
        if not prefill_ls or prefill_ls.user_id != user.id:
            prefill_ls = None
    return templates.TemplateResponse(request, "exams/new.html", {
        "ls_options": ls_options,
        "klassen": klassen,
        "today": date.today().isoformat(),
        "scales": grading.list_scales(),
        "default_scale": grading.DEFAULT_SCALE,
        "prefill_ls": prefill_ls,
    })


@router.post("/exams")
def exams_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    title: str = Form(...),
    datum: str = Form(""),
    klassen_key: str = Form(""),
    learning_situation_id: str = Form(""),
    grading_scale_key: str = Form("mss_noten"),
    input_mode: str = Form("numeric"),
):
    title = title.strip()[:200] or "Neue Prüfung"
    if input_mode not in ("numeric", "stages"):
        input_mode = "numeric"
    if not grading.is_known_scale(grading_scale_key):
        grading_scale_key = grading.DEFAULT_SCALE

    ls_id: int | None = None
    if learning_situation_id.strip():
        try:
            cand = int(learning_situation_id)
            ls = db.get(LearningSituation, cand)
            if ls and ls.user_id == user.id:
                ls_id = cand
                if not klassen_key.strip():
                    klassen_key = ls.klassen_key
        except ValueError:
            pass

    ex = Exam(
        owner_user_id=user.id,
        title=title,
        datum=datum.strip()[:10],
        klassen_key=klassen_key.strip()[:255],
        learning_situation_id=ls_id,
        grading_scale_key=grading_scale_key,
        input_mode=input_mode,
    )
    db.add(ex)
    db.flush()
    audit(db, "exam_created", actor=user, target=str(ex.id),
          detail=f"{title} / {klassen_key}", request=request)
    db.commit()
    return RedirectResponse(f"/exams/{ex.id}", status_code=303)


@router.get("/exams/{ex_id}", response_class=HTMLResponse)
def exams_detail(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ex = _get_exam(db, user, ex_id)
    fps = list(ex.feedback_points)
    students = db.scalars(
        select(Student).where(
            Student.owner_user_id == user.id,
            Student.klassen_key == ex.klassen_key,
            Student.active.is_(True),
        ).order_by(Student.nachname, Student.vorname)
    ).all()
    results = {r.student_id: r for r in ex.results}
    ls = db.get(LearningSituation, ex.learning_situation_id) if ex.learning_situation_id else None

    # Bewertungen aufbereiten + Live-Note berechnen
    student_views = []
    sum_max = sum(fp.max_points for fp in fps)
    for s in students:
        r = results.get(s.id)
        erreicht = json.loads(r.erreicht_json) if r and r.erreicht_json else {}
        sum_err = sum(float(erreicht.get(str(fp.id), 0) or 0) for fp in fps)
        pct = (sum_err / sum_max * 100.0) if sum_max > 0 else 0.0
        note = grading.grade_for_percent(ex.grading_scale_key, pct) if sum_max > 0 else ""
        student_views.append({
            "student": s,
            "erreicht": erreicht,
            "sum_err": sum_err,
            "pct": pct,
            "note": note,
            "comment": r.comment if r else "",
        })

    # Stages aufbereiten
    fp_views = []
    for fp in fps:
        stages = []
        if fp.stages_json:
            try:
                stages = json.loads(fp.stages_json)
            except Exception:
                stages = []
        fp_views.append({
            "fp": fp,
            "stages": stages,
        })

    return templates.TemplateResponse(request, "exams/detail.html", {
        "exam": ex,
        "ls": ls,
        "feedback_points": fp_views,
        "students_view": student_views,
        "sum_max": sum_max,
        "scales": grading.list_scales(),
    })


@router.post("/exams/{ex_id}/save")
def exams_save(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """JSON-Endpoint für Auto-Save aus den Tabs.
    body.tab = 'einstellungen' | 'feedbackpunkte' | 'bewertung'."""
    ex = _get_exam(db, user, ex_id)
    tab = body.get("tab") or ""

    if tab == "einstellungen":
        ex.title = (body.get("title") or "").strip()[:200] or ex.title
        ex.datum = (body.get("datum") or "").strip()[:10]
        ex.klassen_key = (body.get("klassen_key") or "").strip()[:255]
        scale = body.get("grading_scale_key") or ""
        ex.grading_scale_key = scale if grading.is_known_scale(scale) else ex.grading_scale_key
        mode = body.get("input_mode") or ""
        if mode in ("numeric", "stages"):
            ex.input_mode = mode
        ls_raw = body.get("learning_situation_id")
        if ls_raw in (None, "", 0):
            ex.learning_situation_id = None
        else:
            try:
                cand = int(ls_raw)
                ls = db.get(LearningSituation, cand)
                if ls and ls.user_id == user.id:
                    ex.learning_situation_id = cand
            except Exception:
                pass

    elif tab == "feedbackpunkte":
        fps_in = body.get("feedback_points") or []
        if not isinstance(fps_in, list):
            raise HTTPException(400, "feedback_points muss Liste sein")
        # Komplett ersetzen — IDs neu vergeben. Bewertungen werden bei
        # ID-Wechsel ungültig — wir mappen daher bestehende per Position.
        old_fps = list(ex.feedback_points)
        for ofp in old_fps:
            db.delete(ofp)
        db.flush()
        new_fps: list[ExamFeedbackPoint] = []
        for i, item in enumerate(fps_in):
            stages = item.get("stages") or []
            fp = ExamFeedbackPoint(
                exam_id=ex.id,
                position=i,
                name=(item.get("name") or "").strip()[:200],
                max_points=float(item.get("max_points") or 0),
                stages_json=json.dumps(stages, ensure_ascii=False) if stages else "",
            )
            db.add(fp)
            new_fps.append(fp)
        db.flush()
        # Bewertungen: alte erreicht_json-Keys (alte IDs) auf neue IDs nach Position mappen
        new_id_by_pos = [fp.id for fp in new_fps]
        old_id_by_pos = [fp.id for fp in old_fps]
        if new_id_by_pos and old_id_by_pos:
            id_map = {str(old_id_by_pos[i]): str(new_id_by_pos[i])
                      for i in range(min(len(old_id_by_pos), len(new_id_by_pos)))}
            for r in ex.results:
                try:
                    erreicht = json.loads(r.erreicht_json) if r.erreicht_json else {}
                except Exception:
                    erreicht = {}
                mapped = {}
                for k, v in erreicht.items():
                    new_k = id_map.get(str(k))
                    if new_k is not None:
                        mapped[new_k] = v
                r.erreicht_json = json.dumps(mapped, ensure_ascii=False)

    elif tab == "bewertung":
        student_id = body.get("student_id")
        erreicht = body.get("erreicht") or {}
        comment = body.get("comment") or ""
        if not isinstance(erreicht, dict):
            raise HTTPException(400, "erreicht muss Dict sein")
        if not student_id:
            raise HTTPException(400, "student_id fehlt")
        s = db.get(Student, int(student_id))
        if not s or s.owner_user_id != user.id:
            raise HTTPException(404, "Schüler nicht gefunden")
        r = db.query(ExamResult).filter(
            ExamResult.exam_id == ex.id,
            ExamResult.student_id == s.id,
        ).first()
        if not r:
            r = ExamResult(exam_id=ex.id, student_id=s.id)
            db.add(r)
        # Werte als Float casten, leere Strings → 0
        cleaned: dict[str, float] = {}
        for k, v in erreicht.items():
            try:
                cleaned[str(k)] = float(v) if v != "" else 0.0
            except (TypeError, ValueError):
                continue
        r.erreicht_json = json.dumps(cleaned, ensure_ascii=False)
        r.comment = (comment or "")[:2000]

    else:
        raise HTTPException(400, f"Unbekannter Tab: {tab}")

    db.commit()

    # Live-Note nach Speichern für Bewertungs-Tab zurückgeben
    out: dict = {"ok": True}
    if tab == "bewertung":
        sum_max = sum(fp.max_points for fp in ex.feedback_points)
        sum_err = sum(float(cleaned.get(str(fp.id), 0) or 0) for fp in ex.feedback_points)
        pct = (sum_err / sum_max * 100.0) if sum_max > 0 else 0.0
        out["note"] = grading.grade_for_percent(ex.grading_scale_key, pct) if sum_max > 0 else ""
        out["pct"] = round(pct, 1)
        out["sum_err"] = sum_err
        out["sum_max"] = sum_max
    return JSONResponse(out)


@router.post("/exams/{ex_id}/delete")
def exams_delete(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    confirm: str = Form(""),
):
    if confirm != "1":
        raise HTTPException(400, "Bestätigung fehlt")
    ex = _get_exam(db, user, ex_id)
    title = ex.title
    db.delete(ex)
    audit(db, "exam_deleted", actor=user, target=str(ex_id), detail=title, request=request)
    db.commit()
    return RedirectResponse("/exams", status_code=303)
