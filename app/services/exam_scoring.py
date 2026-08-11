"""Notenrechnung einer Prüfung — eine Regel, eine Stelle.

Lag bis 2026-08 als private Helfer in `app/routers/exams.py`. Herausgezogen,
weil das Klassenmodul dieselben Endnoten braucht: Ein Schüler soll auf seiner
Detailseite sehen, was er in den Prüfungen erreicht hat, und diese Zahl muss
dieselbe sein wie im Bewertungsbogen — nicht eine zweite, nachgebaute.

`scoring_ctx()` einmal je Prüfung bauen, dann `student_total()` je Schüler
aufrufen. Der Kontext ist ein reines Dict ohne DB-Zugriff, damit die Schleife
über viele Schüler keine N+1-Abfragen erzeugt.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import Exam, User
from app.services import grading


def _loadjson(s: str | None) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def scoring_ctx(db: Session, user: User, ex: Exam) -> dict:
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
    indiv_remarks = {r.student_id: _loadjson(r.feedback_remarks_json or "{}")
                     for r in ex.results}
    group_remarks = {gr.group_label or "": _loadjson(gr.feedback_remarks_json or "{}")
                     for gr in ex.group_results}
    return {
        "fps": fps, "indiv_fps": indiv_fps, "group_fps": group_fps,
        "sum_max": sum_max, "stufen": stufen,
        "indiv_results": indiv_results, "group_results": group_results,
        "indiv_remarks": indiv_remarks, "group_remarks": group_remarks,
        "bewertung_mode": ex.bewertung_mode or "mixed",
        "grading_scale_ref": ex.grading_scale_key,
    }


def item_percent(fp, value, stufen) -> float | None:
    """Prozentwert eines Items je eval_type. None = nicht bewertbar/leer."""
    if value in (None, ""):
        return None
    if fp.eval_type == "note":
        return grading.percent_for_grade(stufen, str(value))
    # punkte / stufen → wert / max * 100
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    mx = float(fp.max_points or 0)
    if mx <= 0:
        return None
    return max(0.0, min(100.0, v / mx * 100.0))


def item_weight(fp) -> float:
    """Gewicht eines Items für die gewichtete Endnote.
    - note: vom Lehrer gesetztes weight_pct (Fallback 100, falls 0).
    - punkte/stufen: max_points (natürliche Gewichtung = Punkte-Pooling)."""
    if fp.eval_type == "note":
        w = float(fp.weight_pct or 0)
        return w if w > 0 else 100.0
    return float(fp.max_points or 0) or 1.0


def student_total(ctx: dict, student_id: int, group_label: str):
    """(erfasste_items, pct, note) für einen Schüler.

    Im Punkte-Modus: Endnote = Summe(erreicht) / Summe(max) → Prozent →
    Note via Notenschlüssel. Sonst (note/mixed): gewichteter Prozent-
    Schnitt über alle Items je eval_type."""
    er = ctx["indiv_results"].get(student_id, {})
    ger = ctx["group_results"].get(group_label or "", {})
    stufen = ctx["stufen"]
    mode = ctx.get("bewertung_mode", "mixed")

    if mode == "punkte":
        sum_erreicht = 0.0
        sum_max = 0.0
        n_filled = 0
        for fp in ctx["indiv_fps"]:
            raw = er.get(str(fp.id), "")
            if raw in (None, ""):
                continue
            try:
                sum_erreicht += float(raw)
            except (TypeError, ValueError):
                continue
            sum_max += float(fp.max_points or 0)
            n_filled += 1
        for fp in ctx["group_fps"]:
            raw = ger.get(str(fp.id), "")
            if raw in (None, ""):
                continue
            try:
                sum_erreicht += float(raw)
            except (TypeError, ValueError):
                continue
            sum_max += float(fp.max_points or 0)
            n_filled += 1
        if not n_filled or sum_max <= 0:
            return 0, 0.0, ""
        pct = max(0.0, min(100.0, sum_erreicht / sum_max * 100.0))
        note = grading.grade_from_stufen(stufen, pct)
        return n_filled, pct, note

    # 'note' und 'mixed' → bestehende gewichtete Logik
    weighted: list[tuple[float, float]] = []  # (percent, weight)
    n_filled = 0
    for fp in ctx["indiv_fps"]:
        p = item_percent(fp, er.get(str(fp.id), ""), stufen)
        if p is not None:
            weighted.append((p, item_weight(fp)))
            n_filled += 1
    for fp in ctx["group_fps"]:
        p = item_percent(fp, ger.get(str(fp.id), ""), stufen)
        if p is not None:
            weighted.append((p, item_weight(fp)))
            n_filled += 1

    if not weighted:
        return 0, 0.0, ""
    pct = grading.weighted_final(weighted)
    note = grading.grade_from_stufen(stufen, pct)
    return n_filled, pct, note
