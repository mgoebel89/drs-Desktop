"""Unterrichtsbesuche — Hospitationsprotokolle für Anwärter.

Drei Ebenen:
- **Einstellungen**: Kategorien (mit Piktogramm + Farbe), Phasen und die
  Beratungsschwerpunkte (intern `kriterien`) —
  frei pflegbar, mit Vorgaben beim ersten Öffnen.
- **Anwärter** als Stammdatum, **Besuche** mit Kopfdaten und Schwerpunkten.
- **Einträge** im Verlauf: vom Handy erfasst, jeder sofort gespeichert —
  ein verlorener Tab im Unterrichtsbesuch darf keine Notiz kosten.

Seiten unter `/unterrichtsbesuche`, JSON-Endpunkte unter `/api/ub`.
"""
from __future__ import annotations

import mimetypes
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (AppFile, UbAnwaerter, UbBesuch, UbEintrag, UbKategorie,
                        UbKriterium, UbPhase, UbSchwerpunkt, User)
from app.services import file_store
from app.services import unterrichtsbesuche as ub
from app.services import ub_protokoll_pdf
from app.templating import templates

router = APIRouter()

_FOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}


# ── Zugriff nur auf Eigenes ──────────────────────────────────────────────

def _besuch(db: Session, user: User, bid: int) -> UbBesuch:
    b = db.get(UbBesuch, bid)
    if not b or b.user_id != user.id:
        raise HTTPException(404)
    return b


def _anwaerter(db: Session, user: User, aid: int) -> UbAnwaerter:
    a = db.get(UbAnwaerter, aid)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    return a


def _eintrag(db: Session, user: User, eid: int) -> tuple[UbEintrag, UbBesuch]:
    e = db.get(UbEintrag, eid)
    if not e:
        raise HTTPException(404)
    return e, _besuch(db, user, e.besuch_id)


def _art(art: str) -> str:
    if art not in ub.MODELLE:
        raise HTTPException(404)
    return art


def _einstellungs_obj(db: Session, user: User, art: str, oid: int):
    o = db.get(ub.MODELLE[_art(art)], oid)
    if not o or o.user_id != user.id:
        raise HTTPException(404)
    return o


def _eigene_id(db: Session, user: User, model, wert) -> int | None:
    """Übernimmt eine ID nur, wenn der Datensatz dem Lehrer gehört."""
    try:
        oid = int(wert) if wert not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None
    if oid is None:
        return None
    o = db.get(model, oid)
    return oid if o and o.user_id == user.id else None


# ── Seiten ────────────────────────────────────────────────────────────────

@router.get("/unterrichtsbesuche", response_class=HTMLResponse)
def uebersicht(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ub.einstellung(db, user)
    alle = ub.besuche(db, user)
    anstehend = sorted([b for b in alle if ub.ist_anstehend(b)],
                       key=lambda b: (b.datum or "9999", b.beginn))
    vergangen = [b for b in alle if not ub.ist_anstehend(b)]
    zahlen = ub.besuche_je_anwaerter(db, user)
    eintrag_zahl = dict(db.execute(
        select(UbEintrag.besuch_id, func.count(UbEintrag.id))
        .join(UbBesuch, UbBesuch.id == UbEintrag.besuch_id)
        .where(UbBesuch.user_id == user.id, UbEintrag.art == "eintrag")
        .group_by(UbEintrag.besuch_id)
    ).all())
    return templates.TemplateResponse(request, "unterrichtsbesuche/index.html", {
        "anstehend": anstehend,
        "vergangen": vergangen,
        "eintrag_zahl": eintrag_zahl,
        "anwaerter": [ub.anwaerter_dict(a, zahlen.get(a.id, 0))
                      for a in ub.anwaerter_liste(db, user)],
        "schwerpunkt_katalog": [{"id": k.id, "name": k.name}
                                for k in ub.liste(db, user, "kriterien", nur_aktive=True)],
        "heute": date.today().isoformat(),
    })


@router.get("/unterrichtsbesuche/einstellungen", response_class=HTMLResponse)
def einstellungen_seite(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ub.einstellung(db, user)
    daten = {art: [ub.einstellung_dict(art, o, ub.nutzung(db, art, o.id))
                   for o in ub.liste(db, user, art)]
             for art in ub.MODELLE}
    return templates.TemplateResponse(request, "unterrichtsbesuche/einstellungen.html", {
        "daten": daten,
        "icons": ub.icon_katalog(),
        "farben": ub.FARBEN,
        "spalten": ub.SPALTEN,
    })


@router.get("/unterrichtsbesuche/{bid}", response_class=HTMLResponse)
def besuch_seite(
    request: Request,
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    b = _besuch(db, user, bid)
    return templates.TemplateResponse(request, "unterrichtsbesuche/besuch.html", {
        "b": b,
        "besuch": ub.besuch_dict(db, b, mit_eintraegen=True),
        "katalog": ub.katalog(db, user),
        "icons": ub.icon_katalog(),
        "wertungen": ub.WERTUNGEN,
        "status": ub.STATUS,
    })


@router.get("/unterrichtsbesuche/{bid}/erfassen", response_class=HTMLResponse)
def erfassen_seite(
    request: Request,
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    b = _besuch(db, user, bid)
    return templates.TemplateResponse(request, "unterrichtsbesuche/erfassen.html", {
        "b": b,
        "besuch": ub.besuch_dict(db, b, mit_eintraegen=True),
        "katalog": ub.katalog(db, user),
        "icons": ub.icon_katalog(),
        "wertungen": ub.WERTUNGEN,
    })


@router.get("/unterrichtsbesuche/{bid}/protokoll.pdf")
def protokoll_pdf(
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    fotos: int = 1,
):
    b = _besuch(db, user, bid)
    pdf = ub_protokoll_pdf.erzeuge(db, user, b, mit_fotos=bool(fotos))
    name = f"Unterrichtsbesuch_{b.datum or 'ohne-Datum'}_{file_store.safe_filename(b.anwaerter.name if b.anwaerter else '')}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ── Einstellungen (API) ──────────────────────────────────────────────────

@router.get("/api/ub/katalog")
def katalog_lesen(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return JSONResponse(ub.katalog(db, user))


def _einstellung_setzen(art: str, o, p: dict) -> None:
    if "name" in p:
        name = ub.text(p.get("name"), 80)
        if not name:
            raise HTTPException(400, "Der Name darf nicht leer sein.")
        o.name = name
    if "active" in p:
        o.active = bool(p.get("active"))
    if art == "kategorien":
        if "icon" in p:
            o.icon = ub.icon_name(p.get("icon"))
        if "farbe" in p:
            o.farbe = ub.farbe(p.get("farbe"))
        if "spalte" in p:
            o.spalte = ub.spalte(p.get("spalte"))


@router.post("/api/ub/einstellungen/{art}")
def einstellung_anlegen(
    art: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    model = ub.MODELLE[_art(art)]
    ub.einstellung(db, user)
    pos = db.scalar(select(func.max(model.position)).where(model.user_id == user.id))
    o = model(user_id=user.id, position=(pos if pos is not None else -1) + 1)
    if art == "kategorien":
        o.icon, o.farbe, o.spalte = ub.STANDARD_ICON, ub.FARBEN[0][0], "verlauf"
    _einstellung_setzen(art, o, {"name": payload.get("name"), **payload})
    db.add(o)
    db.commit()
    return JSONResponse({"ok": True, "obj": ub.einstellung_dict(art, o, 0)})


@router.post("/api/ub/einstellungen/{art}/reihenfolge")
def einstellung_reihenfolge(
    art: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    model = ub.MODELLE[_art(art)]
    eigene = {o.id: o for o in ub.liste(db, user, art)}
    for i, oid in enumerate(payload.get("ids") or []):
        o = eigene.get(int(oid))
        if o:
            o.position = i
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/ub/einstellungen/{art}/{oid}/save")
def einstellung_speichern(
    art: str,
    oid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    o = _einstellungs_obj(db, user, art, oid)
    _einstellung_setzen(art, o, payload)
    db.commit()
    return JSONResponse({"ok": True,
                         "obj": ub.einstellung_dict(art, o, ub.nutzung(db, art, o.id))})


@router.post("/api/ub/einstellungen/{art}/{oid}/delete")
def einstellung_loeschen(
    art: str,
    oid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    o = _einstellungs_obj(db, user, art, oid)
    n = ub.nutzung(db, art, o.id)
    if n:
        raise HTTPException(409, f"Wird in {n} Einträgen verwendet — bitte stilllegen statt löschen.")
    db.delete(o)
    db.commit()
    return JSONResponse({"ok": True})


# ── Anwärter (API) ───────────────────────────────────────────────────────

def _anwaerter_setzen(a: UbAnwaerter, p: dict) -> None:
    if "name" in p:
        name = ub.text(p.get("name"), 120)
        if not name:
            raise HTTPException(400, "Der Anwärter braucht einen Namen.")
        a.name = name
    if "faecher" in p:
        a.faecher = ub.text(p.get("faecher"), 200)
    if "seminar" in p:
        a.seminar = ub.text(p.get("seminar"), 200)
    if "notiz" in p:
        a.notiz = ub.text(p.get("notiz"))
    if "active" in p:
        a.active = bool(p.get("active"))


@router.post("/api/ub/anwaerter")
def anwaerter_anlegen(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    a = UbAnwaerter(user_id=user.id)
    _anwaerter_setzen(a, {"name": "", **payload})
    db.add(a)
    audit(db, "ub_anwaerter_created", actor=user, target=a.name, request=request)
    db.commit()
    return JSONResponse({"ok": True, "anwaerter": ub.anwaerter_dict(a)})


@router.post("/api/ub/anwaerter/{aid}/save")
def anwaerter_speichern(
    aid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    a = _anwaerter(db, user, aid)
    _anwaerter_setzen(a, payload)
    db.commit()
    return JSONResponse({"ok": True, "anwaerter": ub.anwaerter_dict(
        a, ub.besuche_je_anwaerter(db, user).get(a.id, 0))})


@router.get("/api/ub/anwaerter/{aid}/besuche")
def anwaerter_besuche(
    aid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    a = _anwaerter(db, user, aid)
    return JSONResponse({"ok": True, "besuche": [
        {"id": b.id, "datum": b.datum, "thema": b.thema, "klasse": b.klasse,
         "status": b.status, "status_label": ub.STATUS.get(b.status, b.status)}
        for b in ub.besuche(db, user, a.id)]})


@router.post("/api/ub/anwaerter/{aid}/delete")
def anwaerter_loeschen(
    request: Request,
    aid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    a = _anwaerter(db, user, aid)
    n = ub.besuche_je_anwaerter(db, user).get(a.id, 0)
    if n:
        raise HTTPException(409, f"An diesem Anwärter hängen {n} Besuche — bitte stilllegen.")
    audit(db, "ub_anwaerter_deleted", actor=user, target=a.name, request=request)
    db.delete(a)
    db.commit()
    return JSONResponse({"ok": True})


# ── Besuche (API) ────────────────────────────────────────────────────────

def _besuch_setzen(db: Session, b: UbBesuch, p: dict) -> None:
    """Teil-Update: nur, was mitkommt, wird angefasst."""
    if "datum" in p:
        b.datum = ub.datum(p.get("datum"))
    if "beginn" in p:
        b.beginn = ub.zeit(p.get("beginn"))
    if "ende" in p:
        b.ende = ub.zeit(p.get("ende"))
    for feld, laenge in (("klasse", 80), ("raum", 40), ("thema", 300)):
        if feld in p:
            setattr(b, feld, ub.text(p.get(feld), laenge))
    for feld in ("lernziele", "reflexion", "vereinbarungen"):
        if feld in p:
            setattr(b, feld, ub.text(p.get(feld)))
    if "status" in p and p.get("status") in ub.STATUS:
        b.status = p["status"]


@router.post("/api/ub/besuche")
def besuch_anlegen(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    """Ein Request am Ende des Assistenten — inklusive eines eventuell neu
    angelegten Anwärters. Bricht etwas ab, bleibt nichts halb zurück."""
    neu = payload.get("neuer_anwaerter")
    if neu:
        a = UbAnwaerter(user_id=user.id)
        _anwaerter_setzen(a, {"name": "", **neu})
        db.add(a)
        db.flush()
    else:
        a = _anwaerter(db, user, int(payload.get("anwaerter_id") or 0))
    b = UbBesuch(user_id=user.id, anwaerter_id=a.id, status="geplant")
    _besuch_setzen(db, b, payload)
    if not b.datum:
        raise HTTPException(400, "Der Besuch braucht ein Datum.")
    db.add(b)
    db.flush()
    ub.setze_schwerpunkte(db, user, b, payload.get("schwerpunkte") or [])
    audit(db, "ub_besuch_created", actor=user, target=str(b.id),
          detail=f"{a.name} · {b.datum}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": b.id})


@router.get("/api/ub/besuche/{bid}")
def besuch_lesen(
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    b = _besuch(db, user, bid)
    return JSONResponse({"ok": True, "besuch": ub.besuch_dict(db, b, mit_eintraegen=True)})


@router.post("/api/ub/besuche/{bid}/save")
def besuch_speichern(
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    b = _besuch(db, user, bid)
    if "anwaerter_id" in payload:
        b.anwaerter_id = _anwaerter(db, user, int(payload.get("anwaerter_id") or 0)).id
    _besuch_setzen(db, b, payload)
    if "datum" in payload and not b.datum:
        raise HTTPException(400, "Der Besuch braucht ein Datum.")
    if "schwerpunkte" in payload:
        ub.setze_schwerpunkte(db, user, b, payload.get("schwerpunkte") or [])
    db.commit()
    db.refresh(b)
    return JSONResponse({"ok": True, "besuch": ub.besuch_dict(db, b)})


def _foto_entfernen(db: Session, e: UbEintrag) -> None:
    if not e.file_uuid:
        return
    file_store.delete(e.file_uuid)
    af = db.scalar(select(AppFile).where(AppFile.file_uuid == e.file_uuid))
    if af:
        db.delete(af)
    e.file_uuid = ""
    e.filename = ""


@router.post("/api/ub/besuche/{bid}/delete")
def besuch_loeschen(
    request: Request,
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    b = _besuch(db, user, bid)
    for e in ub.eintraege(db, b.id):
        _foto_entfernen(db, e)
        db.delete(e)
    for s in db.scalars(select(UbSchwerpunkt).where(UbSchwerpunkt.besuch_id == b.id)).all():
        db.delete(s)
    audit(db, "ub_besuch_deleted", actor=user, target=str(b.id),
          detail=f"{b.anwaerter.name if b.anwaerter else ''} · {b.datum}", request=request)
    db.delete(b)
    db.commit()
    return JSONResponse({"ok": True})


# ── Einträge (API) ───────────────────────────────────────────────────────

def _eintrag_setzen(db: Session, user: User, b: UbBesuch, e: UbEintrag, p: dict) -> None:
    if "zeit" in p:
        e.zeit = ub.zeit(p.get("zeit"))
    if e.art == "phase":
        if "phase_id" in p:
            pid = _eigene_id(db, user, UbPhase, p.get("phase_id"))
            if not pid:
                raise HTTPException(400, "Unbekannte Phase.")
            e.phase_id = pid
        return
    if "kategorie_id" in p:
        kid = _eigene_id(db, user, UbKategorie, p.get("kategorie_id"))
        if not kid:
            raise HTTPException(400, "Unbekannte Kategorie.")
        e.kategorie_id = kid
    if "text" in p:
        e.text = ub.text(p.get("text"))
    # Genau ein Beratungsschwerpunkt (oder keiner) je Eintrag — so steht er
    # in der Gruppierung des Protokolls genau einmal.
    if "kriterium_id" in p:
        e.kriterium_id = _eigene_id(db, user, UbKriterium, p.get("kriterium_id"))
    if "wertung" in p:
        e.wertung = ub.wertung(p.get("wertung"))
    if "bezug_id" in p:
        ref = p.get("bezug_id")
        e.bezug_id = None
        if ref:
            r = db.get(UbEintrag, int(ref))
            if r and r.besuch_id == b.id and r.id != e.id:
                e.bezug_id = r.id


@router.post("/api/ub/besuche/{bid}/eintraege")
def eintrag_anlegen(
    bid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    b = _besuch(db, user, bid)
    art = "phase" if payload.get("art") == "phase" else "eintrag"
    e = UbEintrag(besuch_id=b.id, art=art,
                  position=ub.naechste_position(db, b.id))
    if art == "phase" and "phase_id" not in payload:
        raise HTTPException(400, "Unbekannte Phase.")
    if art == "eintrag" and "kategorie_id" not in payload:
        raise HTTPException(400, "Unbekannte Kategorie.")
    _eintrag_setzen(db, user, b, e, payload)
    # Ein reines Foto ist erlaubt: dann schickt die Oberfläche `foto_folgt`
    # und lädt das Bild direkt danach hoch.
    if art == "eintrag" and not e.text and not payload.get("foto_folgt"):
        raise HTTPException(400, "Der Eintrag braucht einen Text.")
    db.add(e)
    # Der erste Eintrag setzt den Besuch auf „läuft" — so erscheint er in
    # der Übersicht oben, auch wenn das Datum schon vorbei ist.
    if b.status == "geplant":
        b.status = "laufend"
    db.commit()
    return JSONResponse({"ok": True, "eintrag": ub.eintrag_dict(e), "status": b.status})


@router.post("/api/ub/eintraege/{eid}/save")
def eintrag_speichern(
    eid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Body()],
):
    e, b = _eintrag(db, user, eid)
    _eintrag_setzen(db, user, b, e, payload)
    if e.art == "eintrag" and "text" in payload and not e.text and not e.file_uuid:
        raise HTTPException(400, "Der Eintrag braucht einen Text.")
    db.commit()
    return JSONResponse({"ok": True, "eintrag": ub.eintrag_dict(e)})


@router.post("/api/ub/eintraege/{eid}/delete")
def eintrag_loeschen(
    eid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    e, b = _eintrag(db, user, eid)
    _foto_entfernen(db, e)
    # Wer sich auf diesen Eintrag bezog, verliert nur den Bezug.
    for r in db.scalars(select(UbEintrag).where(UbEintrag.bezug_id == e.id)).all():
        r.bezug_id = None
    db.delete(e)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/ub/eintraege/{eid}/foto")
async def eintrag_foto(
    eid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    e, b = _eintrag(db, user, eid)
    if e.art != "eintrag":
        raise HTTPException(400, "Nur Einträge können ein Foto haben.")
    name = file.filename or "foto.jpg"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in _FOTO_EXT:
        raise HTTPException(400, "Nur JPG-, PNG- oder WebP-Fotos.")
    payload = await file.read()
    try:
        file_uuid, fname = file_store.store(payload, name)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    _foto_entfernen(db, e)   # ein Foto je Eintrag — das alte fliegt raus
    db.add(AppFile(file_uuid=file_uuid, owner_user_id=user.id, filename=fname,
                   mime=file.content_type or mimetypes.guess_type(fname)[0] or "image/jpeg",
                   size=len(payload)))
    e.file_uuid, e.filename = file_uuid, fname
    db.commit()
    return JSONResponse({"ok": True, "eintrag": ub.eintrag_dict(e)})


@router.post("/api/ub/eintraege/{eid}/foto/delete")
def eintrag_foto_loeschen(
    eid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    e, b = _eintrag(db, user, eid)
    _foto_entfernen(db, e)
    db.commit()
    return JSONResponse({"ok": True, "eintrag": ub.eintrag_dict(e)})
