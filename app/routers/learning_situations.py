"""CRUD und Detail-Ansicht für Lernsituationen."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.auth import audit, require_user
from app.db import get_db
from app.constants import ATTACHMENT_KATEGORIEN, ATTACHMENT_KATEGORIE_LABELS
from app.models import (
    LearningSituation, Lernfeld, LsArbeitsblatt, LsAttachment, LsAufgabe,
    LsLernfeld, User, Worksheet)
from app.services import (aufgabe_sync, file_store, ls_sync, obsidian_writer,
                          smb_client, wizard_helpers, worksheet_from_ls)
from app.models import AppFile
from app.templating import templates

router = APIRouter()


@router.get("/learning-situations", response_class=HTMLResponse)
def ls_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = (
        db.query(LearningSituation)
        .filter(LearningSituation.user_id == user.id)
        .order_by(LearningSituation.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "learning_situations/list.html", {
        "items": rows,
        "smb_configured": bool(user.smb_creds_enc),
    })


@router.get("/ls/new", response_class=HTMLResponse)
def ls_new_form(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Manuelles Anlegen einer Lernsituation (ohne KI/Wizard).

    Erzeugt die LS direkt im Schema v3 — der Lehrer landet danach auf
    der Detail-Seite mit Inline-Edit für alle Sektionen."""
    return templates.TemplateResponse(request, "learning_situations/new.html", {})


@router.post("/ls/new")
def ls_new_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(...),
    klassen_key: str = Form(""),
    lernfeld: str = Form(""),
    dauer_stunden: int = Form(8),
):
    display_name = display_name.strip()[:200]
    if not display_name:
        raise HTTPException(400, "Bezeichnung fehlt")
    slug = wizard_helpers.make_slug(display_name)
    base_slug = slug
    n = 2
    while db.query(LearningSituation.id).filter(
        LearningSituation.user_id == user.id, LearningSituation.slug == slug,
    ).first():
        slug = f"{base_slug}-{n}"
        n += 1

    ls = LearningSituation(
        user_id=user.id, slug=slug, display_name=display_name,
        klassen_key=klassen_key.strip(), lernfeld=lernfeld.strip(),
        dauer_stunden=max(0, dauer_stunden),
        schema_version=3, version_no=1,
    )
    db.add(ls)
    db.flush()
    ls.smb_folder_name = wizard_helpers.folder_name(ls.id, ls.slug)
    ls.obsidian_note_path = obsidian_writer.note_filename(ls)

    # Erstes leeres Arbeitsblatt + Skeleton-MD in den Vault
    db.add(LsArbeitsblatt(
        learning_situation_id=ls.id, position=1,
        title="Arbeitsblatt 1", phase="",
        bearbeitungshinweis_md="", content_md="",
    ))
    db.flush()
    cfg = smb_client.load_config(user)
    if cfg:
        try:
            smb_client.ensure_folder(user, smb_client.material_subpath(cfg, ls.smb_folder_name))
            ls_sync.save_to_vault(user, ls, db)
        except Exception:
            pass
    audit(db, "ls_created_manual", actor=user, target=str(ls.id),
          detail=display_name, request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)


@router.post("/ls/{ls_id}/meta")
def ls_meta_update(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Inline-Edit der LS-Stammdaten (display_name, klassen_key, lernfeld,
    dauer_stunden, version_no). Bei v3-LS wird die MD anschließend neu
    in den Vault geschrieben, damit die Unterrichtsinformationen-Tabelle
    aktualisiert wird."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    field = (body.get("field") or "").strip()
    value = body.get("value")
    if field == "display_name":
        v = str(value or "").strip()[:200]
        if not v:
            raise HTTPException(400, "Bezeichnung darf nicht leer sein")
        ls.display_name = v
    elif field == "klassen_key":
        ls.klassen_key = str(value or "").strip()[:255]
    elif field == "lernfeld":
        ls.lernfeld = str(value or "").strip()[:64]
    elif field == "auftrag_md":
        ls.auftrag_md = str(value or "")
    elif field == "fachliche_praezisierung_md":
        ls.fachliche_praezisierung_md = str(value or "")
    elif field == "dauer_stunden":
        try:
            ls.dauer_stunden = max(0, int(value))
        except (TypeError, ValueError):
            raise HTTPException(400, "Dauer muss eine Zahl sein")
    elif field == "version_no":
        try:
            ls.version_no = max(1, int(value))
        except (TypeError, ValueError):
            raise HTTPException(400, "Version muss eine Zahl sein")
    else:
        raise HTTPException(400, "Unbekanntes Feld")

    if (ls.schema_version or 2) >= 3:
        try:
            ls_sync.save_to_vault(user, ls, db)
        except Exception:
            pass
    audit(db, "ls_meta_updated", actor=user, target=str(ls.id),
          detail=f"{field}={value}", request=request)
    db.commit()
    return JSONResponse({"ok": True})


# ── LS ↔ Lernfeld M2M (Schema v4) ─────────────────────────────────────────


@router.get("/api/ls/{ls_id}/lernfelder")
def ls_lernfelder_get(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Liefert verknüpfte Lernfeld-IDs der LS + die Auswahl-Liste."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    linked_ids = [int(row[0]) for row in db.execute(
        select(LsLernfeld.lernfeld_id).where(
            LsLernfeld.learning_situation_id == ls_id)
    ).all()]
    all_lf = db.scalars(
        select(Lernfeld).where(Lernfeld.user_id == user.id)
        .order_by(Lernfeld.beruf_key, Lernfeld.nummer)
    ).all()
    return JSONResponse({
        "ok": True,
        "linked_ids": linked_ids,
        "options": [
            {"id": lf.id, "beruf_key": lf.beruf_key or "",
             "nummer": lf.nummer or 0, "titel": lf.titel}
            for lf in all_lf
        ],
    })


@router.post("/api/ls/{ls_id}/lernfelder")
def ls_lernfelder_set(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Überschreibt die Lernfeld-Verknüpfungen der LS.

    Body: {ids: [int, ...]}.
    Synchronisiert auch das Legacy-String-Feld `lernfeld` (erstes LF als
    Anzeige-Wert), damit bestehende Pfade (Obsidian-MD, PDF-Export,
    Wizard-Prompts) weiter funktionieren."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    raw_ids = body.get("ids") or []
    if not isinstance(raw_ids, list):
        raise HTTPException(400, "ids muss eine Liste sein")
    # Nur eigene Lernfeld-IDs zulassen
    requested: list[int] = []
    for x in raw_ids:
        try:
            requested.append(int(x))
        except (TypeError, ValueError):
            continue
    valid_rows = db.scalars(
        select(Lernfeld).where(
            Lernfeld.user_id == user.id,
            Lernfeld.id.in_(requested or [-1]))
    ).all() if requested else []
    valid_ids = {lf.id for lf in valid_rows}

    # Bestehende Links löschen, neue setzen
    db.query(LsLernfeld).filter(
        LsLernfeld.learning_situation_id == ls_id).delete()
    for lid in valid_ids:
        db.add(LsLernfeld(learning_situation_id=ls_id, lernfeld_id=lid))

    # Legacy-String aktualisieren (kommagetrennt aus LF-Nummern + Titeln)
    if valid_ids:
        by_id = {lf.id: lf for lf in valid_rows}
        ordered = sorted(valid_ids, key=lambda i: (
            by_id[i].beruf_key or "", by_id[i].nummer or 0))
        parts = []
        for i in ordered:
            lf = by_id[i]
            if lf.nummer:
                parts.append(f"LF{lf.nummer} {lf.titel}".strip())
            else:
                parts.append(lf.titel)
        ls.lernfeld = (", ".join(parts))[:64]
    else:
        ls.lernfeld = ""

    if (ls.schema_version or 2) >= 3:
        try:
            ls_sync.save_to_vault(user, ls, db)
        except Exception:
            pass
    audit(db, "ls_lernfelder_set", actor=user, target=str(ls_id),
          detail=",".join(str(i) for i in sorted(valid_ids)), request=request)
    db.commit()
    return JSONResponse({"ok": True, "linked_ids": sorted(valid_ids),
                         "lernfeld_display": ls.lernfeld})


# ── LS-Anhänge (kategorisiert) + Auftragsbild (Schema v4) ────────────────


import re as _re


_ATTACH_SUBFOLDER = "_anhaenge"
_FILENAME_SAFE = _re.compile(r"[^A-Za-z0-9._\- ]+")


def _safe_filename(name: str) -> str:
    name = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    name = _FILENAME_SAFE.sub("_", name)[:200]
    return name or "datei"


def _serialize_attachment(a: LsAttachment) -> dict:
    return {
        "id": a.id,
        "kategorie": a.kategorie,
        "kategorie_label": ATTACHMENT_KATEGORIE_LABELS.get(
            a.kategorie, a.kategorie),
        "dateiname": a.dateiname,
        "smb_relpath": a.smb_relpath,
        "mime_type": a.mime_type,
        "position": a.position,
    }


@router.get("/api/ls/{ls_id}/attachments")
def ls_attachments_list(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    rows = db.scalars(
        select(LsAttachment).where(
            LsAttachment.learning_situation_id == ls_id)
        .order_by(LsAttachment.position, LsAttachment.id)
    ).all()
    return JSONResponse({
        "ok": True,
        "kategorien": [
            {"key": k, "label": ATTACHMENT_KATEGORIE_LABELS[k]}
            for k in ATTACHMENT_KATEGORIEN
        ],
        "items": [_serialize_attachment(a) for a in rows],
    })


@router.post("/api/ls/{ls_id}/attachments")
async def ls_attachments_upload(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    kategorie: str = Form("sonstiges"),
    file: UploadFile = File(...),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if kategorie not in ATTACHMENT_KATEGORIEN:
        raise HTTPException(400, "Unbekannte Kategorie")
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    dateiname = _safe_filename(file.filename or "anhang")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Datei leer")
    # Eindeutiger Pfad: _anhaenge/<id>__<dateiname> — id wird nach commit
    # bekannt, daher: zuerst INSERT, dann Pfad festlegen, dann schreiben.
    a = LsAttachment(
        learning_situation_id=ls.id, kategorie=kategorie,
        dateiname=dateiname, mime_type=file.content_type or "",
        smb_relpath="", position=0,
    )
    db.add(a)
    db.flush()
    a.smb_relpath = f"{_ATTACH_SUBFOLDER}/{a.id:04d}__{dateiname}"
    base = smb_client.material_subpath(cfg, ls.smb_folder_name)
    smb_client.ensure_folder(user, base + "/" + _ATTACH_SUBFOLDER)
    smb_client.write_file(user, base + "/" + a.smb_relpath, data)
    audit(db, "ls_attachment_uploaded", actor=user, target=str(ls.id),
          detail=f"{kategorie}:{dateiname}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "item": _serialize_attachment(a)})


@router.post("/api/ls/{ls_id}/attachments/{aid}")
def ls_attachment_update(
    request: Request,
    ls_id: int,
    aid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Aktualisiert die Kategorie eines bestehenden Anhangs."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    a = db.get(LsAttachment, aid)
    if not a or a.learning_situation_id != ls_id:
        raise HTTPException(404)
    new_kat = (body.get("kategorie") or "").strip()
    if new_kat and new_kat in ATTACHMENT_KATEGORIEN:
        a.kategorie = new_kat
    audit(db, "ls_attachment_updated", actor=user, target=str(a.id),
          detail=a.kategorie, request=request)
    db.commit()
    return JSONResponse({"ok": True, "item": _serialize_attachment(a)})


@router.delete("/api/ls/{ls_id}/attachments/{aid}")
def ls_attachment_delete(
    request: Request,
    ls_id: int,
    aid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    a = db.get(LsAttachment, aid)
    if not a or a.learning_situation_id != ls_id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if cfg and a.smb_relpath:
        base = smb_client.material_subpath(cfg, ls.smb_folder_name)
        try:
            smb_client.delete_file(user, base + "/" + a.smb_relpath)
        except Exception:
            pass
    db.delete(a)
    audit(db, "ls_attachment_deleted", actor=user, target=str(aid),
          detail=a.dateiname, request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/ls/{ls_id}/auftragsbild")
async def ls_auftragsbild_upload(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Lädt das Auftragsbild für die LS hoch und setzt auftrag_bild_path.

    Bild wird als `_auftrag<ext>` im LS-Material-Ordner abgelegt
    (overschreibt vorhandenes Bild)."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    raw_name = _safe_filename(file.filename or "auftrag.jpg")
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
        raise HTTPException(400, "Bildformat nicht unterstützt")
    relpath = f"_auftrag.{ext}"
    data = await file.read()
    base = smb_client.material_subpath(cfg, ls.smb_folder_name)
    smb_client.ensure_folder(user, base)
    smb_client.write_file(user, base + "/" + relpath, data)
    # Altes Bild mit abweichender Endung entfernen (Aufräumen)
    for old_ext in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
        if old_ext == ext:
            continue
        try:
            smb_client.delete_file(user, base + f"/_auftrag.{old_ext}")
        except Exception:
            pass
    ls.auftrag_bild_path = relpath
    audit(db, "ls_auftragsbild_set", actor=user, target=str(ls.id),
          detail=relpath, request=request)
    db.commit()
    return JSONResponse({"ok": True, "auftrag_bild_path": relpath})


@router.delete("/api/ls/{ls_id}/auftragsbild")
def ls_auftragsbild_delete(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if cfg and ls.auftrag_bild_path:
        base = smb_client.material_subpath(cfg, ls.smb_folder_name)
        try:
            smb_client.delete_file(user, base + "/" + ls.auftrag_bild_path)
        except Exception:
            pass
    ls.auftrag_bild_path = ""
    audit(db, "ls_auftragsbild_cleared", actor=user, target=str(ls.id),
          request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/ls/{ls_id}", response_class=HTMLResponse)
def ls_detail(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    files: list[dict] = []
    smb_error = ""
    if cfg:
        subpath = smb_client.material_subpath(cfg, ls.smb_folder_name)
        try:
            files = smb_client.list_folder(user, subpath)
        except Exception as e:
            smb_error = str(e)
    has_note = bool(obsidian_writer.read_note(user, ls)) if cfg else False

    aufgaben = []
    arbeitsblaetter = []
    if cfg and has_note and (ls.schema_version or 2) < 3:
        try:
            aufgaben = aufgabe_sync.sync_from_md(db, user, ls)
            db.commit()
        except Exception:
            db.rollback()
    elif (ls.schema_version or 2) >= 3:
        # v3: initialer Pull bei leerer DB, danach Arbeitsblätter laden
        if cfg and has_note and not ls.content_hash:
            try:
                ls_sync.load_from_vault(db, user, ls)
                db.commit()
            except Exception:
                db.rollback()
        arbeitsblaetter = db.query(LsArbeitsblatt).filter(
            LsArbeitsblatt.learning_situation_id == ls.id
        ).order_by(LsArbeitsblatt.position).all()
        aufgaben_by_ab: dict[int, list] = {}
        for a in db.query(LsAufgabe).filter(
            LsAufgabe.learning_situation_id == ls.id,
            LsAufgabe.arbeitsblatt_id.isnot(None),
        ).order_by(LsAufgabe.arbeitsblatt_id, LsAufgabe.nummer).all():
            aufgaben_by_ab.setdefault(a.arbeitsblatt_id, []).append(a)
        for ab in arbeitsblaetter:
            ab._aufgaben = aufgaben_by_ab.get(ab.id, [])

    return templates.TemplateResponse(request, "learning_situations/detail.html", {
        "ls": ls,
        "files": files,
        "smb_configured": bool(cfg),
        "smb_error": smb_error,
        "has_note": has_note,
        "aufgaben": aufgaben,
        "arbeitsblaetter": arbeitsblaetter,
    })


@router.post("/ls/{ls_id}/rename")
def ls_rename(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(...),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    display_name = display_name.strip()[:200]
    if not display_name:
        raise HTTPException(400, "Name darf nicht leer sein")
    ls.display_name = display_name  # slug + folder bleiben stabil
    audit(db, "ls_renamed", actor=user, target=str(ls.id), detail=display_name, request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)


@router.post("/ls/{ls_id}/upload")
async def ls_upload(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    files: list[UploadFile] = File(...),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    base = smb_client.material_subpath(cfg, ls.smb_folder_name)
    smb_client.ensure_folder(user, base)

    saved = []
    for f in files:
        name = (f.filename or "datei").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not name or name.startswith("."):
            continue
        data = await f.read()
        smb_client.write_file(user, f"{base}/{name}", data)
        saved.append(name)
    audit(db, "ls_upload", actor=user, target=str(ls.id),
          detail=", ".join(saved), request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)


@router.post("/ls/{ls_id}/worksheet")
def ls_create_worksheet(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    role: str = Form("student"),
    aufgabe_nummern: str = Form(""),
):
    """Erzeugt direkt aus der LS-MD ein Worksheet (ohne Wizard).
    role: 'student' oder 'teacher'.
    aufgabe_nummern: CSV von Nummern (optional) — wenn leer, alle Aufgaben."""
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if role not in ("student", "teacher"):
        raise HTTPException(400, "Ungültige Rolle")

    nummer_filter: list[int] | None = None
    if aufgabe_nummern.strip():
        try:
            nummer_filter = [int(n) for n in aufgabe_nummern.split(",") if n.strip()]
        except ValueError:
            raise HTTPException(400, "aufgabe_nummern muss eine Zahlenliste sein")

    try:
        ws = worksheet_from_ls.create_worksheet_from_ls(
            db, user, ls, role=role, nummer_filter=nummer_filter,  # type: ignore[arg-type]
        )
    except ValueError as e:
        # Z. B. keine MD, oder Schema v1
        return RedirectResponse(
            f"/ls/{ls_id}?ws_error={str(e).replace(' ', '+')}",
            status_code=303,
        )

    audit(db, "worksheet_from_ls", actor=user, target=str(ws.id),
          detail=f"role={role}, ls={ls_id}", request=request)
    db.commit()
    return RedirectResponse(f"/worksheets/{ws.id}", status_code=303)


@router.get("/ls/{ls_id}/delete", response_class=HTMLResponse)
def ls_delete_confirm(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)

    file_count = 0
    smb_error = ""
    has_note = False
    if cfg:
        try:
            file_count = smb_client.count_files(
                user, smb_client.material_subpath(cfg, ls.smb_folder_name))
        except Exception as e:
            smb_error = str(e)
        try:
            has_note = bool(obsidian_writer.read_note(user, ls))
        except Exception:
            pass

    linked_worksheets = db.scalars(
        select(Worksheet).where(Worksheet.learning_situation_id == ls.id)
    ).all()

    return templates.TemplateResponse(request, "learning_situations/confirm_delete.html", {
        "ls": ls,
        "file_count": file_count,
        "has_note": has_note,
        "smb_error": smb_error,
        "smb_configured": bool(cfg),
        "linked_worksheets": linked_worksheets,
    })


@router.post("/ls/{ls_id}/delete")
def ls_delete_exec(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    confirm: str = Form(""),
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if confirm != "1":
        raise HTTPException(400, "Bestätigungs-Checkbox nicht gesetzt")

    display_name = ls.display_name
    folder = ls.smb_folder_name
    cfg = smb_client.load_config(user)

    smb_errors: list[str] = []
    deleted_files = 0
    if cfg:
        # 1) Material-Ordner rekursiv löschen
        try:
            deleted_files = smb_client.delete_folder_recursive(
                user, smb_client.material_subpath(cfg, ls.smb_folder_name))
        except Exception as e:
            smb_errors.append(f"Material-Ordner: {e}")
        # 2) Vault-MD löschen
        try:
            smb_client.delete_file(
                user, smb_client.vault_subpath(cfg, obsidian_writer.note_filename(ls)))
        except Exception as e:
            smb_errors.append(f"Vault-MD: {e}")

    # 3) DB löschen — FKs in worksheets/lesson_notes sind ON DELETE SET NULL
    db.delete(ls)
    audit(db, "ls_deleted", actor=user, target=str(ls_id),
          detail=f"{display_name} · {folder} · {deleted_files} Datei(en)"
                 + (f" · Fehler: {'; '.join(smb_errors)}" if smb_errors else ""),
          request=request)
    db.commit()
    return RedirectResponse("/learning-situations", status_code=303)


# ─────────────────────── Schema v3: Sync-Endpoints ─────────────────────


_SECTION_FIELDS = {
    "lernsituation": "lernsituation_md",
    "kompetenzen": "kompetenzen_md",
    "uebergreifende_aspekte": "uebergreifende_aspekte_md",
    "lehrer_vorwissen": "lehrer_vorwissen_md",
    "leistungsfeststellung": "leistungsfeststellung_md",
    # Schema v4
    "auftrag": "auftrag_md",
    "fachliche_praezisierung": "fachliche_praezisierung_md",
}


def _require_v3(db: Session, user: User, ls_id: int) -> LearningSituation:
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if (ls.schema_version or 2) < 3:
        raise HTTPException(409, "Lernsituation ist noch Schema v2 — bitte migrieren")
    return ls


@router.post("/ls/{ls_id}/migrate-v3")
def ls_migrate_v3(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Hebt eine v2-LS auf Schema v3 an. Sicherheitskopie der alten MD
    wird als <slug>.v2.bak.md im Vault abgelegt. Anschließend wird eine
    v3-Vorlage geschrieben, befüllt mit den bestehenden Top-Level-
    Feldern (lernziele/vorwissen aus der DB)."""
    from app.services import obsidian_writer_v3 as v3

    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    if (ls.schema_version or 2) >= 3:
        raise HTTPException(409, "Bereits v3")

    # Sicherheitskopie der vorhandenen MD
    raw = obsidian_writer.read_note(user, ls) or ""
    if raw:
        try:
            cfg = smb_client.load_config(user)
            if cfg:
                bak_name = ls.smb_folder_name + ".v2.bak.md"
                bak_subpath = smb_client.vault_subpath(cfg, bak_name)
                smb_client.write_file(user, bak_subpath, raw.encode("utf-8"))
        except Exception:
            pass  # Backup-Fehler darf Migration nicht stoppen

    # v3-Skeleton mit bestehenden Inhalten befüllen
    ls.schema_version = 3
    if ls.lernziele and not ls.lernsituation_md:
        ls.lernsituation_md = ls.lernziele.strip()
    if ls.vorwissen and not ls.lehrer_vorwissen_md:
        ls.lehrer_vorwissen_md = ls.vorwissen.strip()
    if not ls.dauer_stunden:
        ls.dauer_stunden = 8
    if not ls.version_no:
        ls.version_no = 1
    db.flush()

    # MD aus dem (jetzt leeren) DB-Stand bauen + Beispiel-Arbeitsblatt
    if not db.query(LsArbeitsblatt).filter(
        LsArbeitsblatt.learning_situation_id == ls.id
    ).count():
        db.add(LsArbeitsblatt(
            learning_situation_id=ls.id, position=1,
            title="Arbeitsblatt 1", phase="Arbeitsplanung",
            bearbeitungshinweis_md="Hinweis zur Bearbeitung (Optional)",
            content_md="",
        ))
        db.flush()

    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_migrated_v3", actor=user, target=str(ls.id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "schema_version": 3,
                         "backup": ls.smb_folder_name + ".v2.bak.md"})


@router.get("/ls/{ls_id}/sync/status")
def ls_sync_status(
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Liefert den Konflikt-Report (leeres `sections`-Array = in sync)."""
    ls = _require_v3(db, user, ls_id)
    rep = ls_sync.detect_conflict(db, user, ls)
    return JSONResponse({
        "ok": True,
        "in_sync": not rep.has_conflict,
        "file_hash": rep.file_hash,
        "db_hash": rep.db_hash,
        "sections": [
            {"key": s.key, "label": s.label,
             "app_value": s.app_value, "vault_value": s.vault_value}
            for s in rep.sections
        ],
    })


@router.post("/ls/{ls_id}/sync/pull")
def ls_sync_pull(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Vault → DB. Überschreibt DB-Sektionen mit den Werten aus der MD."""
    ls = _require_v3(db, user, ls_id)
    changed = ls_sync.load_from_vault(db, user, ls)
    audit(db, "ls_sync_pull", actor=user, target=str(ls.id),
          detail="changed" if changed else "noop", request=request)
    db.commit()
    return JSONResponse({"ok": True, "applied": changed})


@router.post("/ls/{ls_id}/sync/push")
def ls_sync_push(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """DB → Vault. Baut MD aus dem aktuellen DB-Stand und schreibt sie."""
    ls = _require_v3(db, user, ls_id)
    try:
        ls_sync.save_to_vault(user, ls, db)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    audit(db, "ls_sync_push", actor=user, target=str(ls.id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/section/{section_key}")
def ls_section_save(
    request: Request,
    ls_id: int,
    section_key: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Inline-Edit pro Sektion. Erwartet `{value, expected_hash?}`.

    Wenn `expected_hash` mitgesendet wird, prüft die App, dass die
    Datei zwischenzeitlich nicht extern geändert wurde — bei Mismatch
    409 Conflict (Client sollte auf den Konflikt-Banner umschalten)."""
    ls = _require_v3(db, user, ls_id)
    value = (body.get("value") or "")
    expected = body.get("expected_hash")
    if expected and (ls.content_hash or "") != expected:
        rep = ls_sync.detect_conflict(db, user, ls)
        if rep.has_conflict:
            raise HTTPException(409, "Konflikt mit externer Änderung")

    if section_key in _SECTION_FIELDS:
        setattr(ls, _SECTION_FIELDS[section_key], value[:200000])
    elif section_key.startswith("arbeitsblatt:"):
        try:
            pos = int(section_key.split(":", 1)[1])
        except ValueError:
            raise HTTPException(400, "Ungültiger Sektions-Key")
        ab = db.query(LsArbeitsblatt).filter(
            LsArbeitsblatt.learning_situation_id == ls.id,
            LsArbeitsblatt.position == pos,
        ).first()
        if not ab:
            ab = LsArbeitsblatt(
                learning_situation_id=ls.id, position=pos,
                title=f"Arbeitsblatt {pos}",
            )
            db.add(ab)
            db.flush()
        # Sub-Felder via field-Suffix: arbeitsblatt:N:phase|hinweis|content
        sub = (body.get("field") or "content").strip()
        if sub == "phase":
            ab.phase = value[:255]
        elif sub == "hinweis":
            ab.bearbeitungshinweis_md = value[:10000]
        elif sub == "title":
            ab.title = value[:255]
        else:
            ab.content_md = value[:200000]
    else:
        raise HTTPException(400, "Unbekannte Sektion")

    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_section_saved", actor=user, target=str(ls.id),
          detail=section_key, request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/bild")
async def ls_bild_upload(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Lädt ein Bild für die Lernsituationsbeschreibung hoch und setzt
    `ls.lernsituation_bild_path` auf `/api/files/<uuid>/<name>`. Die MD
    wird neu in den Vault geschrieben."""
    import mimetypes
    ls = _require_v3(db, user, ls_id)
    payload = await file.read()
    try:
        file_uuid, fname = file_store.store(payload, file.filename or "bild")
    except ValueError as e:
        raise HTTPException(400, str(e))
    mime = file.content_type or mimetypes.guess_type(fname)[0] or "application/octet-stream"
    db.add(AppFile(
        file_uuid=file_uuid, owner_user_id=user.id,
        filename=fname, mime=mime, size=len(payload),
    ))
    ls.lernsituation_bild_path = f"/api/files/{file_uuid}/{fname}"
    try:
        ls_sync.save_to_vault(user, ls, db)
    except Exception:
        pass
    audit(db, "ls_bild_uploaded", actor=user, target=str(ls.id),
          detail=f"{fname} · {len(payload)}B", request=request)
    db.commit()
    return JSONResponse({"ok": True, "path": ls.lernsituation_bild_path})


@router.post("/ls/{ls_id}/bild/delete")
def ls_bild_delete(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Entfernt das Bild aus der Lernsituationsbeschreibung. Die Datei
    bleibt in /api/files erhalten (kein delete) — der Pfad wird in der
    LS nur geleert."""
    ls = _require_v3(db, user, ls_id)
    ls.lernsituation_bild_path = ""
    try:
        ls_sync.save_to_vault(user, ls, db)
    except Exception:
        pass
    audit(db, "ls_bild_deleted", actor=user, target=str(ls.id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/ls/{ls_id}/cover-worksheet")
def ls_cover_worksheet(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Erzeugt ein Worksheet, das nur die Lernsituation als Deckblatt
    enthält (ohne Aufgaben)."""
    ls = _require_v3(db, user, ls_id)
    ws = worksheet_from_ls.create_worksheet_lernsituation_cover(db, user, ls)
    audit(db, "worksheet_ls_cover", actor=user, target=str(ws.id),
          detail=f"ls={ls.id}", request=request)
    db.commit()
    return RedirectResponse(f"/worksheets/{ws.id}", status_code=303)


@router.post("/ls/{ls_id}/arbeitsblatt/{ab_id}/worksheet")
def ls_arbeitsblatt_worksheet(
    request: Request,
    ls_id: int,
    ab_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    role: str = Form("student"),
):
    """Erzeugt ein Worksheet aus einem v3-Arbeitsblatt (DB-Daten)."""
    ls = _require_v3(db, user, ls_id)
    ab = db.get(LsArbeitsblatt, ab_id)
    if not ab or ab.learning_situation_id != ls.id:
        raise HTTPException(404, "Arbeitsblatt nicht gefunden")
    if role not in ("student", "teacher"):
        raise HTTPException(400, "role muss student|teacher sein")
    ws = worksheet_from_ls.create_worksheet_from_arbeitsblatt(db, user, ls, ab, role)  # type: ignore[arg-type]
    audit(db, "worksheet_from_arbeitsblatt", actor=user, target=str(ws.id),
          detail=f"ls={ls.id} ab={ab.id} role={role}", request=request)
    db.commit()
    return RedirectResponse(f"/worksheets/{ws.id}", status_code=303)


@router.post("/ls/{ls_id}/arbeitsblatt/{ab_id}/aufgabe")
def ls_aufgabe_add(
    request: Request,
    ls_id: int,
    ab_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Legt eine neue Aufgabe in einem Arbeitsblatt an. Nummer = max+1."""
    ls = _require_v3(db, user, ls_id)
    ab = db.get(LsArbeitsblatt, ab_id)
    if not ab or ab.learning_situation_id != ls.id:
        raise HTTPException(404, "Arbeitsblatt nicht gefunden")
    max_n = db.query(LsAufgabe.nummer).filter(
        LsAufgabe.arbeitsblatt_id == ab.id
    ).order_by(LsAufgabe.nummer.desc()).first()
    nummer = (max_n[0] if max_n else 0) + 1
    a = LsAufgabe(
        learning_situation_id=ls.id,
        arbeitsblatt_id=ab.id,
        nummer=nummer,
        titel="",
        anchor=f"aufgabe-{nummer}",
        phasen=ab.phase or "",
        text_md="",
        loesungsskizze_md="",
    )
    db.add(a)
    db.flush()
    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_aufgabe_added", actor=user, target=str(ls.id),
          detail=f"ab={ab.id} nr={nummer}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "aufgabe_id": a.id, "nummer": nummer})


@router.post("/ls/{ls_id}/aufgabe/{auf_id}")
def ls_aufgabe_update(
    request: Request,
    ls_id: int,
    auf_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Inline-Save eines Aufgabe-Feldes: titel|text|loesungsskizze."""
    ls = _require_v3(db, user, ls_id)
    a = db.get(LsAufgabe, auf_id)
    if not a or a.learning_situation_id != ls.id:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    field = (body.get("field") or "").strip()
    value = str(body.get("value") or "")
    if field == "titel":
        a.titel = value[:500]
    elif field == "text":
        a.text_md = value[:200000]
    elif field == "loesungsskizze":
        a.loesungsskizze_md = value[:200000]
    else:
        raise HTTPException(400, "Unbekanntes Feld")
    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_aufgabe_saved", actor=user, target=str(ls.id),
          detail=f"auf={a.id} {field}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/aufgabe/{auf_id}/delete")
def ls_aufgabe_delete(
    request: Request,
    ls_id: int,
    auf_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Löscht eine Aufgabe und nummeriert die nachfolgenden im selben
    Arbeitsblatt durch (1, 2, 3 …)."""
    ls = _require_v3(db, user, ls_id)
    a = db.get(LsAufgabe, auf_id)
    if not a or a.learning_situation_id != ls.id:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    ab_id = a.arbeitsblatt_id
    db.delete(a)
    db.flush()
    # Nachfolger neu nummerieren
    rest = db.query(LsAufgabe).filter(
        LsAufgabe.arbeitsblatt_id == ab_id
    ).order_by(LsAufgabe.nummer).all()
    for i, ra in enumerate(rest, start=1):
        ra.nummer = i
        ra.anchor = f"aufgabe-{i}"
    ls_sync.save_to_vault(user, ls, db)
    audit(db, "ls_aufgabe_deleted", actor=user, target=str(ls.id),
          detail=f"auf={auf_id}", request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/ls/{ls_id}/sync/resolve")
def ls_sync_resolve(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    body: dict = Body(...),
):
    """Konflikt auflösen. Body: `{choices: {section_key: 'app'|'vault'}}`.

    Für jeden Key mit 'vault' wird der Vault-Stand in die DB übernommen,
    danach wird die MD aus dem (jetzt vom Lehrer gemixten) DB-Stand neu
    geschrieben."""
    ls = _require_v3(db, user, ls_id)
    choices = body.get("choices") or {}
    if not isinstance(choices, dict):
        raise HTTPException(400, "Ungültige Auswahl")
    ls_sync.apply_resolution(db, user, ls, {k: str(v) for k, v in choices.items()})
    audit(db, "ls_sync_resolved", actor=user, target=str(ls.id),
          detail=f"{sum(1 for v in choices.values() if v == 'vault')} sektionen geholt",
          request=request)
    db.commit()
    return JSONResponse({"ok": True, "hash": ls.content_hash})


@router.post("/ls/{ls_id}/files/{filename}/delete")
def ls_delete_file(
    request: Request,
    ls_id: int,
    filename: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400)
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)
    cfg = smb_client.load_config(user)
    if not cfg:
        raise HTTPException(400, "SMB nicht konfiguriert")
    subpath = smb_client.material_subpath(cfg, ls.smb_folder_name) + "/" + filename
    try:
        smb_client.delete_file(user, subpath)
    except Exception as e:
        raise HTTPException(502, f"SMB-Fehler: {e}")
    audit(db, "ls_file_deleted", actor=user, target=str(ls.id), detail=filename, request=request)
    db.commit()
    return RedirectResponse(f"/ls/{ls.id}", status_code=303)
