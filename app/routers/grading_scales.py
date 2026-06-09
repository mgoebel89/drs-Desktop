"""Verwaltung benutzerdefinierter Notenskalen (Typ MSS Punkte / MSS Noten)."""
from __future__ import annotations

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import GradingScale, User
from app.services import grading
from app.templating import templates

router = APIRouter()


@router.get("/grading-scales", response_class=HTMLResponse)
def scales_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(GradingScale).where(GradingScale.owner_user_id == user.id)
        .order_by(GradingScale.name)
    ).all()
    builtins = [
        {"key": k, "label": v["label"], "type": v["type"],
         "n_stufen": len(v["stufen"])}
        for k, v in grading.BUILTINS.items()
    ]
    return templates.TemplateResponse(request, "grading_scales/list.html", {
        "scales": rows,
        "builtins": builtins,
        "scale_types": grading.list_scale_types(),
    })


@router.get("/grading-scales/new", response_class=HTMLResponse)
def scales_new(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    type: str = "mss_noten",
    copy_from: str = "",
):
    if type not in grading.SCALE_TYPES:
        type = "mss_noten"
    # Vorbelegung: Built-in-Vorlage kopieren oder Default des Typs
    if copy_from and copy_from in grading.BUILTINS:
        bt = grading.BUILTINS[copy_from]
        type = bt["type"]
        stufen = [{"label": l, "min_pct": lo, "max_pct": hi}
                  for l, lo, hi in bt["stufen"]]
        name = bt["label"] + " (Kopie)"
    else:
        stufen = grading.default_stufen_for(type)
        name = ""
    grade_names = grading.default_grade_names_for(type)
    for s in stufen:
        s["name_text"] = grade_names.get(s["label"], "")
    return templates.TemplateResponse(request, "grading_scales/edit.html", {
        "scale": None,
        "scale_type": type,
        "type_label": grading.SCALE_TYPES[type]["label"],
        "name": name,
        "stufen": stufen,
    })


@router.post("/grading-scales")
def scales_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    name = (body.get("name") or "").strip()[:120]
    scale_type = body.get("scale_type") or "mss_noten"
    if scale_type not in grading.SCALE_TYPES:
        scale_type = "mss_noten"
    if not name:
        raise HTTPException(400, "Name fehlt")
    raw = body.get("stufen") or []
    stufen, grade_names = _clean_stufen_with_names(raw)
    gs = GradingScale(
        owner_user_id=user.id, name=name, scale_type=scale_type,
        payload_json=json.dumps(stufen, ensure_ascii=False),
        grade_names_json=json.dumps(grade_names, ensure_ascii=False),
    )
    db.add(gs)
    db.flush()
    audit(db, "grading_scale_created", actor=user, target=str(gs.id),
          detail=name, request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": gs.id})


@router.get("/grading-scales/{scale_id}", response_class=HTMLResponse)
def scales_edit(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    try:
        stufen = json.loads(gs.payload_json) or []
    except Exception:
        stufen = []
    grade_names = grading.default_grade_names_for(gs.scale_type)
    try:
        stored = json.loads(gs.grade_names_json or "{}") or {}
        grade_names.update({str(k): str(v) for k, v in stored.items() if v})
    except Exception:
        pass
    for s in stufen:
        s["name_text"] = grade_names.get(s.get("label", ""), "")
    return templates.TemplateResponse(request, "grading_scales/edit.html", {
        "scale": gs,
        "scale_type": gs.scale_type,
        "type_label": grading.SCALE_TYPES.get(gs.scale_type, {}).get("label", gs.scale_type),
        "name": gs.name,
        "stufen": stufen,
    })


@router.post("/grading-scales/{scale_id}")
def scales_update(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    name = (body.get("name") or "").strip()[:120]
    if name:
        gs.name = name
    stufen, grade_names = _clean_stufen_with_names(body.get("stufen") or [])
    gs.payload_json = json.dumps(stufen, ensure_ascii=False)
    gs.grade_names_json = json.dumps(grade_names, ensure_ascii=False)
    audit(db, "grading_scale_updated", actor=user, target=str(gs.id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/grading-scales/{scale_id}/delete")
def scales_delete(
    request: Request,
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    name = gs.name
    db.delete(gs)
    audit(db, "grading_scale_deleted", actor=user, target=str(scale_id),
          detail=name, request=request)
    db.commit()
    return RedirectResponse("/grading-scales", status_code=303)


def _clean_stufen(raw: list) -> list[dict]:
    out: list[dict] = []
    for row in raw:
        try:
            label = str(row.get("label", "")).strip()
            if not label:
                continue
            out.append({
                "label": label[:16],
                "min_pct": float(row.get("min_pct", 0)),
                "max_pct": float(row.get("max_pct", 0)),
            })
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _clean_stufen_with_names(raw: list) -> tuple[list[dict], dict[str, str]]:
    """Liefert (stufen_payload, grade_names_map). Schriftliche
    Bezeichnungen werden separat in grade_names_json gespeichert,
    damit das alte payload_json-Format unverändert bleibt."""
    stufen = _clean_stufen(raw)
    names: dict[str, str] = {}
    for row in raw:
        try:
            label = str(row.get("label", "")).strip()
            name_text = str(row.get("name_text") or "").strip()
        except (AttributeError, TypeError):
            continue
        if label and name_text:
            names[label[:16]] = name_text[:80]
    return stufen, names


# ── JSON / CSV — Export + Import ────────────────────────────────────────


@router.get("/grading-scales/{scale_id}/export.json")
def scales_export_json(
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    try:
        stufen = json.loads(gs.payload_json) or []
    except Exception:
        stufen = []
    try:
        names = json.loads(gs.grade_names_json or "{}") or {}
    except Exception:
        names = {}
    payload = {
        "name": gs.name,
        "scale_type": gs.scale_type,
        "stufen": [
            {"label": s.get("label", ""),
             "min_pct": s.get("min_pct", 0),
             "max_pct": s.get("max_pct", 0),
             "name_text": names.get(s.get("label", ""), "")}
            for s in stufen
        ],
    }
    filename = f"notenschluessel_{gs.id}_{gs.name[:40]}.json".replace(" ", "_")
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/grading-scales/{scale_id}/export.csv")
def scales_export_csv(
    scale_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    gs = db.get(GradingScale, scale_id)
    if not gs or gs.owner_user_id != user.id:
        raise HTTPException(404)
    try:
        stufen = json.loads(gs.payload_json) or []
    except Exception:
        stufen = []
    try:
        names = json.loads(gs.grade_names_json or "{}") or {}
    except Exception:
        names = {}
    buf = io.StringIO()
    buf.write("﻿")  # BOM für Excel
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Label", "min %", "max %", "Bezeichnung"])
    for s in stufen:
        w.writerow([
            s.get("label", ""),
            str(s.get("min_pct", 0)).replace(".", ","),
            str(s.get("max_pct", 0)).replace(".", ","),
            names.get(s.get("label", ""), ""),
        ])
    filename = f"notenschluessel_{gs.id}_{gs.name[:40]}.csv".replace(" ", "_")
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_csv_stufen(text: str) -> list[dict]:
    """CSV-Import: Spalten Label; min%; max%[; Bezeichnung]. Trennzeichen
    `;` oder `,`. Erste Zeile wird als Header erkannt, wenn sie Wörter
    wie 'label', 'min', 'max' enthält."""
    text = text.lstrip("﻿")
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    delim = ";" if ";" in lines[0] else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim, quotechar='"')
    rows = list(reader)
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    has_header = any(k in header for k in ("label", "note", "stufe")) or \
                 any("min" in c for c in header) or any("max" in c for c in header)
    body = rows[1:] if has_header else rows

    def to_float(s: str) -> float:
        return float((s or "0").replace(",", ".").strip())

    out: list[dict] = []
    for row in body:
        if not row or not row[0].strip():
            continue
        try:
            label = row[0].strip()
            min_pct = to_float(row[1]) if len(row) > 1 else 0.0
            max_pct = to_float(row[2]) if len(row) > 2 else 0.0
            name_text = row[3].strip() if len(row) > 3 else ""
        except (ValueError, IndexError):
            continue
        if not label:
            continue
        out.append({
            "label": label[:16],
            "min_pct": min_pct,
            "max_pct": max_pct,
            "name_text": name_text[:80],
        })
    return out


@router.post("/grading-scales/import")
async def scales_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    name: str = Form(""),
    scale_type: str = Form("mss_noten"),
):
    """Importiert einen Notenschlüssel aus JSON oder CSV.

    JSON-Format: {name?, scale_type?, stufen:[{label, min_pct, max_pct,
    name_text?}]}. Name + scale_type aus dem Form überschreiben die JSON-
    Werte, wenn gesetzt.

    CSV-Format: Spalten Label;min%;max%;Bezeichnung (Header optional).
    Bei CSV müssen Name + scale_type per Form mitkommen.
    """
    if scale_type not in grading.SCALE_TYPES:
        scale_type = "mss_noten"
    payload = await file.read()
    text = payload.decode("utf-8", errors="replace")
    lower = (file.filename or "").lower()

    raw_stufen: list[dict] = []
    final_name = name.strip()[:120]
    final_type = scale_type

    if lower.endswith(".json") or text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Kein gültiges JSON: {e}")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON muss ein Objekt sein")
        if not final_name:
            final_name = str(data.get("name") or "").strip()[:120]
        type_from_json = str(data.get("scale_type") or "").strip()
        if type_from_json in grading.SCALE_TYPES and not name.strip():
            final_type = type_from_json
        raw_stufen = data.get("stufen") or []
    else:
        raw_stufen = _parse_csv_stufen(text)

    if not raw_stufen:
        raise HTTPException(400, "Keine Stufen gefunden")
    if not final_name:
        raise HTTPException(400, "Name fehlt (im Formular oder in der JSON)")

    stufen, names = _clean_stufen_with_names(raw_stufen)
    gs = GradingScale(
        owner_user_id=user.id, name=final_name, scale_type=final_type,
        payload_json=json.dumps(stufen, ensure_ascii=False),
        grade_names_json=json.dumps(names, ensure_ascii=False),
    )
    db.add(gs)
    db.flush()
    audit(db, "grading_scale_imported", actor=user, target=str(gs.id),
          detail=f"{final_name} ({len(stufen)} Stufen)", request=request)
    db.commit()
    return RedirectResponse(f"/grading-scales/{gs.id}", status_code=303)
