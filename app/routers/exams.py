"""Prüfungen / Bewertungen — CRUD + 4-Tab-Edit + Export."""
from __future__ import annotations

import io
import json
import zipfile
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
from app.services import exam_md, grading, obsidian_writer
from app.services.playwright_pdf import render_pdf
from app import branding
from fastapi.responses import PlainTextResponse, Response
from urllib.parse import quote
from slugify import slugify
import re
from datetime import datetime
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


@router.get("/exams/template.md")
def exams_template(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    ls_id: int | None = None,
):
    """Vorlage als Markdown zum Download. Optional aus LS vorbefüllt."""
    ls = None
    klassen_key = ""
    lernfeld = ""
    lernsituation_slug = ""
    title = ""
    feedback_points: list[dict] = []
    students_list: list[dict] = []

    if ls_id:
        ls = db.get(LearningSituation, ls_id)
        if not ls or ls.user_id != user.id:
            raise HTTPException(404, "Lernsituation nicht gefunden")
        klassen_key = ls.klassen_key
        lernfeld = ls.lernfeld
        lernsituation_slug = ls.slug
        title = f"{ls.display_name} · Bewertung"

        # Aufgaben aus LS-MD als Feedbackpunkt-Vorschläge
        try:
            md = obsidian_writer.read_note(user, ls)
            if md.strip() and obsidian_writer.detect_schema_version(md) >= 2:
                for a in obsidian_writer.parse_aufgaben(md):
                    feedback_points.append({
                        "name": f"Aufgabe {a['nummer']}: {a['titel']}",
                        "max_points": 10,
                    })
        except Exception:
            pass

    # Schüler aus DB für diese Klasse (auch ohne LS, wenn klassen_key gesetzt)
    if klassen_key:
        for s in db.scalars(
            select(Student).where(
                Student.owner_user_id == user.id,
                Student.klassen_key == klassen_key,
                Student.active.is_(True),
            ).order_by(Student.nachname, Student.vorname)
        ).all():
            students_list.append({
                "nachname": s.nachname, "vorname": s.vorname,
                "email": s.email, "moodle_id": s.moodle_id,
            })

    md_text = exam_md.build_template(
        title=title,
        klasse=klassen_key,
        lernfeld=lernfeld,
        lernsituation_slug=lernsituation_slug,
        lehrer=user.full_name or user.username,
        students=students_list or None,
        feedback_points=feedback_points or None,
    )

    # Dateiname
    name_part = ls.smb_folder_name if ls else "pruefungsvorlage"
    filename = f"{name_part}_vorlage.md"
    return Response(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(filename)}"',
        },
    )


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


def _format_number(v: float) -> str:
    """1.0 → '1', 1.5 → '1,5' (deutsche Schreibweise im PDF)."""
    if v is None:
        return ""
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _build_student_pdf_html(
    request: Request, db: Session, user: User, ex: Exam, student: Student,
) -> str:
    """Rendert das HTML für ein Schüler-PDF."""
    fps = list(ex.feedback_points)
    result = db.query(ExamResult).filter(
        ExamResult.exam_id == ex.id,
        ExamResult.student_id == student.id,
    ).first()
    erreicht = json.loads(result.erreicht_json) if result and result.erreicht_json else {}
    comment = (result.comment if result else "") or ""

    rows = []
    sum_err = 0.0
    sum_max = 0.0
    for fp in fps:
        val = erreicht.get(str(fp.id), 0)
        try:
            val_f = float(val) if val != "" else 0.0
        except (TypeError, ValueError):
            val_f = 0.0
        sum_err += val_f
        sum_max += float(fp.max_points or 0)
        rows.append({
            "name": fp.name,
            "max_str": _format_number(fp.max_points),
            "erreicht_str": _format_number(val_f),
        })

    pct = (sum_err / sum_max * 100.0) if sum_max > 0 else 0.0
    note = grading.grade_for_percent(ex.grading_scale_key, pct) if sum_max > 0 else ""

    # Datum hübsch
    datum_pretty = ""
    if ex.datum:
        try:
            datum_pretty = datetime.fromisoformat(ex.datum).strftime("%d.%m.%Y")
        except Exception:
            datum_pretty = ex.datum

    return templates.get_template("exams/student_pdf.html").render({
        "request": request,
        "exam": ex,
        "student": student,
        "rows": rows,
        "sum_err_str": _format_number(sum_err),
        "sum_max_str": _format_number(sum_max),
        "pct_str": _format_number(round(pct, 1)),
        "note": note,
        "datum_pretty": datum_pretty,
        "lehrer_name": user.full_name or user.username,
        "klassen_key": ex.klassen_key,
        "school_logo_data_url": branding.logo_data_url(db),
        "signature_data_url": "",  # später aus User-Setting
        "comment": comment,
    })


@router.get("/exams/{ex_id}/export/pdf")
async def exams_export_pdf_single(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    student_id: int,
):
    ex = _get_exam(db, user, ex_id)
    student = db.get(Student, student_id)
    if not student or student.owner_user_id != user.id:
        raise HTTPException(404, "Schüler nicht gefunden")

    html = _build_student_pdf_html(request, db, user, ex, student)
    pdf_bytes = await render_pdf(html)

    audit(db, "exam_pdf_single", actor=user, target=str(ex_id),
          detail=f"student={student_id}", request=request)
    db.commit()

    filename = f"{slugify(ex.title)}_{slugify(student.nachname)}_{slugify(student.vorname)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(filename)}"',
        },
    )


@router.get("/exams/{ex_id}/export.zip")
async def exams_export_zip(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """ZIP mit einem PDF pro Schüler dieser Klasse."""
    ex = _get_exam(db, user, ex_id)
    students = db.scalars(
        select(Student).where(
            Student.owner_user_id == user.id,
            Student.klassen_key == ex.klassen_key,
            Student.active.is_(True),
        ).order_by(Student.nachname, Student.vorname)
    ).all()
    if not students:
        raise HTTPException(400, "Keine Schüler in dieser Klasse")

    # ZIP im RAM bauen — pro Schüler ein PDF
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s in students:
            try:
                html = _build_student_pdf_html(request, db, user, ex, s)
                pdf_bytes = await render_pdf(html)
            except Exception as e:
                # Einen fehlerhaften Datensatz nicht den ganzen ZIP-Bau abbrechen lassen
                err_text = f"Fehler beim Rendern für {s.nachname}, {s.vorname}: {e}"
                zf.writestr(f"_FEHLER_{slugify(s.nachname)}.txt", err_text)
                continue
            filename = f"{slugify(s.nachname)}_{slugify(s.vorname)}.pdf"
            zf.writestr(filename, pdf_bytes)
    buf.seek(0)

    audit(db, "exam_pdf_zip", actor=user, target=str(ex_id),
          detail=f"{len(students)} Schüler", request=request)
    db.commit()

    zip_name = f"{slugify(ex.title)}_{ex.datum or 'ohne_datum'}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(zip_name)}"',
        },
    )


@router.get("/exams/{ex_id}/export.md")
def exams_export_md(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Komplette Prüfungs-MD inkl. Bewertungen (für Offline-App / Obsidian)."""
    ex = _get_exam(db, user, ex_id)
    students = db.scalars(
        select(Student).where(
            Student.owner_user_id == user.id,
            Student.klassen_key == ex.klassen_key,
        ).order_by(Student.nachname, Student.vorname)
    ).all()
    results_by_sid = {r.student_id: r for r in ex.results}
    md = exam_md.build_from_exam(ex, students, results_by_sid)
    filename = f"{slugify(ex.title)}_{ex.datum or 'export'}.md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(filename)}"',
        },
    )


@router.post("/exams/{ex_id}/import.md")
async def exams_import_md(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Prüfungs-MD parsen und Bewertungen in die bestehende Prüfung schreiben.
    Schüler, die im MD vorkommen aber nicht in der DB sind, werden neu
    angelegt (in der Klasse der Prüfung). Feedbackpunkt-Zuordnung läuft
    per Spalten-Header (Name)."""
    ex = _get_exam(db, user, ex_id)
    md_text = body.get("md") or ""
    if not md_text.strip():
        raise HTTPException(400, "Leerer Inhalt")
    parsed = exam_md.parse_exam_md(md_text)

    # Feedbackpunkt-Index nach Name (case-insensitive)
    fp_by_name: dict[str, int] = {
        fp.name.strip().lower(): fp.id for fp in ex.feedback_points
    }

    # Schüler-Sync: existierende mappen, neue anlegen
    existing_by_name: dict[tuple[str, str], Student] = {}
    for s in db.scalars(
        select(Student).where(
            Student.owner_user_id == user.id,
            Student.klassen_key == ex.klassen_key,
        )
    ).all():
        existing_by_name[(s.nachname.lower(), s.vorname.lower())] = s
    for sd in parsed.students:
        key = (sd["nachname"].lower(), sd["vorname"].lower())
        if key not in existing_by_name:
            ns = Student(
                owner_user_id=user.id,
                klassen_key=ex.klassen_key,
                nachname=sd["nachname"][:120],
                vorname=sd["vorname"][:120],
                email=sd.get("email", "")[:255],
                moodle_id=sd.get("moodle_id", "")[:64],
            )
            db.add(ns)
            db.flush()
            existing_by_name[key] = ns

    # Bewertungen schreiben
    imported = 0
    for b in parsed.bewertungen:
        key = (b["nachname"].lower(), b["vorname"].lower())
        s = existing_by_name.get(key)
        if not s:
            continue
        erreicht: dict[str, float] = {}
        for col_name, val in b["by_col"].items():
            fp_id = fp_by_name.get(col_name.strip().lower())
            if fp_id is None:
                continue
            val = (val or "").strip()
            if not val:
                continue
            # Zahl-Versuch
            try:
                erreicht[str(fp_id)] = float(val.replace(",", "."))
                continue
            except ValueError:
                pass
            # Stufen-Label-Versuch
            fp = next((fp for fp in ex.feedback_points if fp.id == fp_id), None)
            if fp and fp.stages_json:
                try:
                    stages = json.loads(fp.stages_json)
                    match = next((st for st in stages
                                  if st.get("label", "").strip().lower() == val.lower()), None)
                    if match is not None:
                        erreicht[str(fp_id)] = float(match.get("points", 0))
                except Exception:
                    pass

        r = db.query(ExamResult).filter(
            ExamResult.exam_id == ex.id,
            ExamResult.student_id == s.id,
        ).first()
        if not r:
            r = ExamResult(exam_id=ex.id, student_id=s.id)
            db.add(r)
        r.erreicht_json = json.dumps(erreicht, ensure_ascii=False)
        if b.get("comment"):
            r.comment = b["comment"][:2000]
        imported += 1

    audit(db, "exam_md_imported", actor=user, target=str(ex_id),
          detail=f"{imported} Schüler-Bewertungen", request=request)
    db.commit()
    return JSONResponse({"ok": True, "imported": imported})


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
