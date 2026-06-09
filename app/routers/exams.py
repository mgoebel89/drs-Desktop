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
from app.models import (Exam, ExamFeedbackPoint, ExamGroupResult, ExamResult,
                        ExamStudent, FeedbackTemplate, LearningSituation,
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


def _loadjson(s: str | None) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def _exam_classes(ex: Exam) -> list[str]:
    return [c.strip() for c in (ex.klassen_key or "").split(",") if c.strip()]


def _exam_participants(db: Session, ex: Exam) -> list[tuple[Student, str]]:
    """Teilnehmer (Member) der Prüfung + group_label, sortiert."""
    rows = db.execute(
        select(Student, ExamStudent.group_label)
        .join(ExamStudent, ExamStudent.student_id == Student.id)
        .where(ExamStudent.exam_id == ex.id)
        .order_by(ExamStudent.group_label, Student.nachname, Student.vorname)
    ).all()
    return [(s, g or "") for s, g in rows]


def _scoring_ctx(db: Session, user: User, ex: Exam):
    """Vorberechnung für Noten: Feedbackpunkte nach Scope, Summen, Stufen,
    Ergebnis-Maps."""
    fps = list(ex.feedback_points)
    indiv_fps = [fp for fp in fps if fp.scope != "group"]
    group_fps = [fp for fp in fps if fp.scope == "group"]
    sum_max = sum(float(fp.max_points or 0) for fp in fps)
    stufen = grading.resolve_stufen(db, user, ex.grading_scale_key)
    indiv_results = {r.student_id: _loadjson(r.erreicht_json) for r in ex.results}
    group_results = {gr.group_label or "": _loadjson(gr.erreicht_json)
                     for gr in ex.group_results}
    return {
        "fps": fps, "indiv_fps": indiv_fps, "group_fps": group_fps,
        "sum_max": sum_max, "stufen": stufen,
        "indiv_results": indiv_results, "group_results": group_results,
    }


def _student_total(ctx: dict, student_id: int, group_label: str):
    """(sum_err, pct, note) für einen Schüler (Einzel- + Gruppenpunkte)."""
    er = ctx["indiv_results"].get(student_id, {})
    total = sum(float(er.get(str(fp.id), 0) or 0) for fp in ctx["indiv_fps"])
    ger = ctx["group_results"].get(group_label or "", {})
    total += sum(float(ger.get(str(fp.id), 0) or 0) for fp in ctx["group_fps"])
    sum_max = ctx["sum_max"]
    pct = (total / sum_max * 100.0) if sum_max > 0 else 0.0
    note = grading.grade_from_stufen(ctx["stufen"], pct) if sum_max > 0 else ""
    return total, pct, note


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
            select(ExamStudent.student_id)
            .where(ExamStudent.exam_id == e.id).limit(1)
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
        "scales": grading.list_scales_for(db, user),
        "default_scale": grading.DEFAULT_SCALE,
        "prefill_ls": prefill_ls,
    })


def _add_class_members(db: Session, user: User, ex: Exam, klassen: list[str]) -> None:
    """Fügt alle aktiven Schüler der genannten Klassen als Teilnehmer hinzu
    (preselected), sofern noch nicht Mitglied."""
    existing = {row[0] for row in db.execute(
        select(ExamStudent.student_id).where(ExamStudent.exam_id == ex.id)
    ).all()}
    for kk in klassen:
        if not kk:
            continue
        for s in db.scalars(
            select(Student).where(
                Student.owner_user_id == user.id,
                Student.klassen_key == kk,
                Student.active.is_(True),
            )
        ).all():
            if s.id not in existing:
                db.add(ExamStudent(exam_id=ex.id, student_id=s.id, group_label=""))
                existing.add(s.id)


@router.post("/exams")
def exams_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    title: str = Form(...),
    datum: str = Form(""),
    klassen: list[str] = Form(default=[]),
    learning_situation_id: str = Form(""),
    grading_scale_key: str = Form("builtin:mss_noten"),
    input_mode: str = Form("numeric"),
):
    title = title.strip()[:200] or "Neue Prüfung"
    if input_mode not in ("numeric", "stages"):
        input_mode = "numeric"
    # Skala: builtin akzeptieren oder custom:<id> des Nutzers
    if not _valid_scale_ref(db, user, grading_scale_key):
        grading_scale_key = grading.DEFAULT_SCALE

    klassen_clean = [k.strip() for k in klassen if k.strip()]

    ls_id: int | None = None
    if learning_situation_id.strip():
        try:
            cand = int(learning_situation_id)
            ls = db.get(LearningSituation, cand)
            if ls and ls.user_id == user.id:
                ls_id = cand
                if not klassen_clean and ls.klassen_key:
                    klassen_clean = [ls.klassen_key]
        except ValueError:
            pass

    ex = Exam(
        owner_user_id=user.id,
        title=title,
        datum=datum.strip()[:10],
        klassen_key=", ".join(klassen_clean)[:255],
        learning_situation_id=ls_id,
        grading_scale_key=grading_scale_key,
        input_mode=input_mode,
    )
    db.add(ex)
    db.flush()
    # Alle Schüler der gewählten Klassen als Teilnehmer vorauswählen
    _add_class_members(db, user, ex, klassen_clean)
    audit(db, "exam_created", actor=user, target=str(ex.id),
          detail=f"{title} / {ex.klassen_key}", request=request)
    db.commit()
    return RedirectResponse(f"/exams/{ex.id}", status_code=303)


def _valid_scale_ref(db: Session, user: User, ref: str) -> bool:
    if grading.is_known_scale(ref):
        return True
    if ref and ref.startswith("custom:"):
        try:
            from app.models import GradingScale
            gs = db.get(GradingScale, int(ref.split(":", 1)[1]))
            return bool(gs and gs.owner_user_id == user.id)
        except Exception:
            return False
    return False


@router.get("/exams/{ex_id}", response_class=HTMLResponse)
def exams_detail(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ex = _get_exam(db, user, ex_id)
    ls = db.get(LearningSituation, ex.learning_situation_id) if ex.learning_situation_id else None
    ctx = _scoring_ctx(db, user, ex)
    participants = _exam_participants(db, ex)

    # Teilnehmer-Tab: alle Schüler der beteiligten Klassen + Member-Status
    exam_classes = _exam_classes(ex)
    member_ids = {s.id for s, _ in participants}
    member_group = {s.id: g for s, g in participants}
    all_klassen = [
        row[0] for row in db.execute(
            select(Student.klassen_key).where(Student.owner_user_id == user.id).distinct()
        ).all()
    ]
    roster = []  # Schüler der beteiligten Klassen (für Checkboxen)
    if exam_classes:
        for s in db.scalars(
            select(Student).where(
                Student.owner_user_id == user.id,
                Student.klassen_key.in_(exam_classes),
                Student.active.is_(True),
            ).order_by(Student.klassen_key, Student.nachname, Student.vorname)
        ).all():
            roster.append({
                "student": s,
                "member": s.id in member_ids,
                "group_label": member_group.get(s.id, ""),
            })

    # Bewertungs-Tab: Teilnehmer mit Live-Note
    student_views = []
    for s, g in participants:
        er = ctx["indiv_results"].get(s.id, {})
        total, pct, note = _student_total(ctx, s.id, g)
        student_views.append({
            "student": s, "group_label": g,
            "erreicht": er, "sum_err": total, "pct": pct, "note": note,
        })

    # Gruppen + deren Gruppen-Bewertungen
    groups = sorted({g for _, g in participants if g})
    group_views = []
    for g in groups:
        group_views.append({
            "label": g,
            "erreicht": ctx["group_results"].get(g, {}),
            "members": [s.nachname for s, gg in participants if gg == g],
        })

    # Feedbackpunkte mit Stages + Scope
    fp_views = []
    fp_stages: dict[int, list] = {}
    for fp in ctx["fps"]:
        stages = _loadjson(fp.stages_json) if fp.stages_json else []
        fp_views.append({"fp": fp, "stages": stages})
        fp_stages[fp.id] = stages

    return templates.TemplateResponse(request, "exams/detail.html", {
        "exam": ex,
        "ls": ls,
        "feedback_points": fp_views,
        "fp_stages": fp_stages,
        "indiv_fps": ctx["indiv_fps"],
        "group_fps": ctx["group_fps"],
        "students_view": student_views,
        "group_views": group_views,
        "groups": groups,
        "roster": roster,
        "all_klassen": all_klassen,
        "exam_classes": exam_classes,
        "sum_max": ctx["sum_max"],
        "scales": grading.list_scales_for(db, user),
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
    body.tab = 'einstellungen' | 'teilnehmer' | 'feedbackpunkte' | 'bewertung'."""
    ex = _get_exam(db, user, ex_id)
    tab = body.get("tab") or ""

    if tab == "einstellungen":
        ex.title = (body.get("title") or "").strip()[:200] or ex.title
        ex.datum = (body.get("datum") or "").strip()[:10]
        scale = body.get("grading_scale_key") or ""
        if _valid_scale_ref(db, user, scale):
            ex.grading_scale_key = scale
        mode = body.get("input_mode") or ""
        if mode in ("numeric", "stages"):
            ex.input_mode = mode
        # Klassen-Mehrfachauswahl
        klassen = body.get("klassen")
        if isinstance(klassen, list):
            old_classes = set(_exam_classes(ex))
            new_clean = [k.strip() for k in klassen if k.strip()]
            ex.klassen_key = ", ".join(new_clean)[:255]
            # Neu hinzugekommene Klassen: Schüler vorauswählen
            added = [k for k in new_clean if k not in old_classes]
            if added:
                _add_class_members(db, user, ex, added)
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

    elif tab == "teilnehmer":
        # body.members = [{student_id, selected, group_label}, …]
        members = body.get("members") or []
        if not isinstance(members, list):
            raise HTTPException(400, "members muss Liste sein")
        # owner-Schüler-IDs für Sicherheit
        valid_ids = {row[0] for row in db.execute(
            select(Student.id).where(Student.owner_user_id == user.id)
        ).all()}
        existing = {es.student_id: es for es in db.scalars(
            select(ExamStudent).where(ExamStudent.exam_id == ex.id)
        ).all()}
        seen = set()
        for m in members:
            try:
                sid = int(m.get("student_id"))
            except (TypeError, ValueError):
                continue
            if sid not in valid_ids:
                continue
            selected = bool(m.get("selected"))
            group_label = (m.get("group_label") or "").strip()[:40]
            if not selected:
                if sid in existing:
                    db.delete(existing[sid])
                continue
            seen.add(sid)
            if sid in existing:
                existing[sid].group_label = group_label
            else:
                db.add(ExamStudent(exam_id=ex.id, student_id=sid, group_label=group_label))

    elif tab == "feedbackpunkte":
        fps_in = body.get("feedback_points") or []
        if not isinstance(fps_in, list):
            raise HTTPException(400, "feedback_points muss Liste sein")
        old_fps = list(ex.feedback_points)
        for ofp in old_fps:
            db.delete(ofp)
        db.flush()
        new_fps: list[ExamFeedbackPoint] = []
        for i, item in enumerate(fps_in):
            stages = item.get("stages") or []
            scope = item.get("scope") if item.get("scope") in ("individual", "group") else "individual"
            fp = ExamFeedbackPoint(
                exam_id=ex.id,
                position=i,
                name=(item.get("name") or "").strip()[:200],
                max_points=float(item.get("max_points") or 0),
                scope=scope,
                stages_json=json.dumps(stages, ensure_ascii=False) if stages else "",
            )
            db.add(fp)
            new_fps.append(fp)
        db.flush()
        # Bestehende Bewertungen per Position auf neue IDs mappen (Einzel + Gruppe)
        new_id_by_pos = [fp.id for fp in new_fps]
        old_id_by_pos = [fp.id for fp in old_fps]
        if new_id_by_pos and old_id_by_pos:
            id_map = {str(old_id_by_pos[i]): str(new_id_by_pos[i])
                      for i in range(min(len(old_id_by_pos), len(new_id_by_pos)))}
            for r in list(ex.results) + list(ex.group_results):
                erreicht = _loadjson(r.erreicht_json)
                mapped = {id_map[k]: v for k, v in erreicht.items() if k in id_map}
                r.erreicht_json = json.dumps(mapped, ensure_ascii=False)

    elif tab == "bewertung":
        erreicht = body.get("erreicht") or {}
        if not isinstance(erreicht, dict):
            raise HTTPException(400, "erreicht muss Dict sein")
        cleaned: dict[str, float] = {}
        for k, v in erreicht.items():
            try:
                cleaned[str(k)] = float(v) if v != "" else 0.0
            except (TypeError, ValueError):
                continue

        group_label = body.get("group_label")
        if group_label is not None:
            # Gruppen-Bewertung
            gl = (group_label or "").strip()[:40]
            gr = db.query(ExamGroupResult).filter(
                ExamGroupResult.exam_id == ex.id,
                ExamGroupResult.group_label == gl,
            ).first()
            if not gr:
                gr = ExamGroupResult(exam_id=ex.id, group_label=gl)
                db.add(gr)
            gr.erreicht_json = json.dumps(cleaned, ensure_ascii=False)
        else:
            # Einzel-Bewertung
            student_id = body.get("student_id")
            if not student_id:
                raise HTTPException(400, "student_id oder group_label fehlt")
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
            r.erreicht_json = json.dumps(cleaned, ensure_ascii=False)
            r.comment = (body.get("comment") or "")[:2000]
    else:
        raise HTTPException(400, f"Unbekannter Tab: {tab}")

    db.commit()

    # Nach Bewertungs-Save: aktualisierte Live-Noten zurückgeben
    out: dict = {"ok": True}
    if tab == "bewertung":
        ctx = _scoring_ctx(db, user, ex)
        notes = []
        for s, g in _exam_participants(db, ex):
            total, pct, note = _student_total(ctx, s.id, g)
            notes.append({"student_id": s.id, "sum_err": total,
                          "pct": round(pct, 1), "note": note})
        out["notes"] = notes
        out["sum_max"] = ctx["sum_max"]
    return JSONResponse(out)


def _format_number(v: float) -> str:
    """1.0 → '1', 1.5 → '1,5' (deutsche Schreibweise im PDF)."""
    if v is None:
        return ""
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _datum_pretty(datum: str) -> str:
    if not datum:
        return ""
    try:
        return datetime.fromisoformat(datum).strftime("%d.%m.%Y")
    except Exception:
        return datum


def _build_student_pdf_html(
    request: Request, db: Session, user: User, ex: Exam,
    student: Student, group_label: str, ctx: dict,
) -> str:
    """Rendert das HTML für ein Schüler-PDF (Einzel- + Gruppenpunkte)."""
    er = ctx["indiv_results"].get(student.id, {})
    ger = ctx["group_results"].get(group_label or "", {})

    rows = []
    for fp in ctx["fps"]:
        if fp.scope == "group":
            val = ger.get(str(fp.id), 0)
        else:
            val = er.get(str(fp.id), 0)
        try:
            val_f = float(val) if val != "" else 0.0
        except (TypeError, ValueError):
            val_f = 0.0
        rows.append({
            "name": fp.name,
            "scope": fp.scope,
            "max_str": _format_number(fp.max_points),
            "erreicht_str": _format_number(val_f),
        })

    total, pct, note = _student_total(ctx, student.id, group_label)
    comment = ""
    r = ctx["indiv_results"].get(student.id)  # nicht das Result-Objekt; Kommentar separat holen
    res_obj = next((x for x in ex.results if x.student_id == student.id), None)
    if res_obj:
        comment = res_obj.comment or ""

    return templates.get_template("exams/student_pdf.html").render({
        "request": request,
        "exam": ex,
        "student": student,
        "group_label": group_label,
        "rows": rows,
        "sum_err_str": _format_number(total),
        "sum_max_str": _format_number(ctx["sum_max"]),
        "pct_str": _format_number(round(pct, 1)),
        "note": note,
        "datum_pretty": _datum_pretty(ex.datum),
        "lehrer_name": user.full_name or user.username,
        "klassen_key": ex.klassen_key,
        "school_logo_data_url": branding.logo_data_url(db),
        "school_name_value": branding.get_school_name(db),
        "signature_data_url": "",  # später aus User-Setting
        "comment": comment,
    })


def _build_summary_pdf_html(
    request: Request, db: Session, user: User, ex: Exam, ctx: dict,
) -> str:
    """Lehrer-Zusammenfassung: Notenverteilung + Namensliste mit Endnote."""
    participants = _exam_participants(db, ex)
    rows = []
    verteilung: dict[str, int] = {}
    for s, g in participants:
        total, pct, note = _student_total(ctx, s.id, g)
        rows.append({
            "nachname": s.nachname, "vorname": s.vorname,
            "klasse": s.klassen_key, "gruppe": g,
            "pct_str": _format_number(round(pct, 1)),
            "note": note,
        })
        if note:
            verteilung[note] = verteilung.get(note, 0) + 1
    rows.sort(key=lambda r: (r["nachname"].lower(), r["vorname"].lower()))
    # Verteilung in Skalen-Reihenfolge
    verteilung_ordered = [
        {"note": lbl, "count": verteilung.get(lbl, 0)}
        for lbl, _, _ in ctx["stufen"] if verteilung.get(lbl, 0) > 0
    ]
    schnitt = ""
    pcts = [float(r["pct_str"].replace(",", ".")) for r in rows if r["note"]]
    if pcts:
        schnitt = _format_number(round(sum(pcts) / len(pcts), 1))

    return templates.get_template("exams/summary_pdf.html").render({
        "request": request,
        "exam": ex,
        "rows": rows,
        "verteilung": verteilung_ordered,
        "datum_pretty": _datum_pretty(ex.datum),
        "lehrer_name": user.full_name or user.username,
        "schnitt_pct": schnitt,
        "n": len(rows),
        "school_logo_data_url": branding.logo_data_url(db),
        "school_name_value": branding.get_school_name(db),
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
    es = db.get(ExamStudent, {"exam_id": ex.id, "student_id": student.id})
    group_label = es.group_label if es else ""

    ctx = _scoring_ctx(db, user, ex)
    html = _build_student_pdf_html(request, db, user, ex, student, group_label, ctx)
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
    """ZIP mit einem PDF pro Teilnehmer + Lehrer-Zusammenfassung."""
    ex = _get_exam(db, user, ex_id)
    participants = _exam_participants(db, ex)
    if not participants:
        raise HTTPException(400, "Keine Teilnehmer in dieser Prüfung")

    ctx = _scoring_ctx(db, user, ex)

    # ZIP im RAM bauen — pro Teilnehmer ein PDF + Zusammenfassung
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s, g in participants:
            try:
                html = _build_student_pdf_html(request, db, user, ex, s, g, ctx)
                pdf_bytes = await render_pdf(html)
            except Exception as e:
                err_text = f"Fehler beim Rendern für {s.nachname}, {s.vorname}: {e}"
                zf.writestr(f"_FEHLER_{slugify(s.nachname)}.txt", err_text)
                continue
            filename = f"{slugify(s.nachname)}_{slugify(s.vorname)}.pdf"
            zf.writestr(filename, pdf_bytes)
        # Lehrer-Zusammenfassung
        try:
            summary_html = _build_summary_pdf_html(request, db, user, ex, ctx)
            zf.writestr("_Zusammenfassung.pdf", await render_pdf(summary_html))
        except Exception as e:
            zf.writestr("_Zusammenfassung_FEHLER.txt", str(e))
    buf.seek(0)

    audit(db, "exam_pdf_zip", actor=user, target=str(ex_id),
          detail=f"{len(participants)} Teilnehmer", request=request)
    db.commit()

    zip_name = f"{slugify(ex.title)}_{ex.datum or 'ohne_datum'}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{quote(zip_name)}"',
        },
    )


@router.get("/exams/{ex_id}/summary.pdf")
async def exams_summary_pdf(
    request: Request,
    ex_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Nur die Lehrer-Zusammenfassung als PDF."""
    ex = _get_exam(db, user, ex_id)
    ctx = _scoring_ctx(db, user, ex)
    html = _build_summary_pdf_html(request, db, user, ex, ctx)
    pdf_bytes = await render_pdf(html)
    filename = f"{slugify(ex.title)}_Zusammenfassung.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'},
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
    students = [s for s, _ in _exam_participants(db, ex)]
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

    # Schüler-Sync: existierende mappen (alle eigenen), neue anlegen
    existing_by_name: dict[tuple[str, str], Student] = {}
    for s in db.scalars(
        select(Student).where(Student.owner_user_id == user.id)
    ).all():
        existing_by_name[(s.nachname.lower(), s.vorname.lower())] = s
    first_class = (_exam_classes(ex) or [""])[0]
    member_ids = {row[0] for row in db.execute(
        select(ExamStudent.student_id).where(ExamStudent.exam_id == ex.id)
    ).all()}
    for sd in parsed.students:
        key = (sd["nachname"].lower(), sd["vorname"].lower())
        s = existing_by_name.get(key)
        if s is None:
            s = Student(
                owner_user_id=user.id,
                klassen_key=first_class,
                nachname=sd["nachname"][:120],
                vorname=sd["vorname"][:120],
                email=sd.get("email", "")[:255],
                moodle_id=sd.get("moodle_id", "")[:64],
            )
            db.add(s)
            db.flush()
            existing_by_name[key] = s
        # Als Teilnehmer aufnehmen, falls noch nicht Mitglied
        if s.id not in member_ids:
            db.add(ExamStudent(exam_id=ex.id, student_id=s.id, group_label=""))
            member_ids.add(s.id)

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
