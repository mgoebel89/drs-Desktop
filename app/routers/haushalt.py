"""Haushalt: Posten je Haushaltsjahr, Anschaffungsideen fürs Folgejahr.

Die Rechenregeln stehen in `app/services/haushalt.py` — dieser Router ist nur
die Hülle: Seite, JSON-Endpunkte, Umrechnung Euro ↔ Cent an der Grenze.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import HhIdee, HhPosten, User, Vorgang, VorgangEintrag
from app.services import haushalt as hh
from app.templating import templates

router = APIRouter()


def _jahr(wert, fallback: int | None = None) -> int:
    try:
        j = int(wert)
    except (TypeError, ValueError):
        return fallback if fallback is not None else date.today().year
    # Tippfehler wie 202 oder 20266 sollen keine Geisterjahre anlegen.
    return j if 2000 <= j <= 2100 else (fallback or date.today().year)


@router.get("/haushalt", response_class=HTMLResponse)
def haushalt_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
):
    return templates.TemplateResponse(request, "haushalt/index.html", {
        "arten": hh.ART_LABEL,
        "jahr": date.today().year,
    })


# ── Übersicht ────────────────────────────────────────────────────────────

@router.get("/api/haushalt/uebersicht")
def haushalt_uebersicht(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    jahr: int = 0,
):
    j = _jahr(jahr or date.today().year)
    return JSONResponse({
        "ok": True,
        "jahre": hh.bekannte_jahre(db, user),
        **hh.posten_view(db, user, j),
        **{"ideen": hh.ideen_view(db, user, j + 1)},
    })


# ── Posten ───────────────────────────────────────────────────────────────

@router.post("/api/haushalt/posten")
def posten_speichern(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    """Anlegen und Ändern in einem Endpunkt — `id` entscheidet."""
    bez = (payload.get("bezeichnung") or "").strip()[:200]
    if not bez:
        return JSONResponse({"ok": False, "error": "Bitte eine Bezeichnung angeben."},
                            status_code=400)
    art = payload.get("art")
    if art not in hh.ARTEN:
        return JSONResponse({"ok": False, "error": "Unbekannter Haushalt."},
                            status_code=400)

    pid = payload.get("id")
    if pid:
        p = db.get(HhPosten, int(pid))
        if not p or p.user_id != user.id:
            return JSONResponse({"ok": False, "error": "Posten nicht gefunden."},
                                status_code=404)
    else:
        p = HhPosten(user_id=user.id)
        db.add(p)

    p.jahr = _jahr(payload.get("jahr"))
    p.art = art
    p.bezeichnung = bez
    p.betrag_cent = hh.to_cent(payload.get("betrag"))
    p.notiz = (payload.get("notiz") or "").strip()[:2000]
    db.flush()
    audit(db, "hh_posten_save", actor=user, target=str(p.id),
          detail=f"{p.jahr}/{p.art}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": p.id})


@router.post("/api/haushalt/posten/{posten_id}/delete")
def posten_loeschen(
    request: Request,
    posten_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Löschen nur, solange nichts darauf gebucht ist.

    Sonst hingen Kosten-Einträge an einer Nummer, die es nicht mehr gibt, und
    die Summen eines abgeschlossenen Jahres änderten sich rückwirkend.
    """
    p = db.get(HhPosten, posten_id)
    if not p or p.user_id != user.id:
        return JSONResponse({"ok": False, "error": "Posten nicht gefunden."},
                            status_code=404)
    gebucht = hh.verbrauch_je_posten(db, user, [p.id]).get(p.id, 0)
    anzahl = db.query(VorgangEintrag).filter(
        VorgangEintrag.hh_posten_id == p.id).count()
    if anzahl:
        summe = f"{hh.to_euro(gebucht):.2f}".replace(".", ",")
        wort = "Buchung" if anzahl == 1 else "Buchungen"
        return JSONResponse({
            "ok": False,
            "error": (f"Auf diesen Posten {'ist' if anzahl == 1 else 'sind'} "
                      f"{anzahl} {wort} über {summe} € gebucht. Erst die "
                      "Buchungen umhängen oder löschen."),
        }, status_code=409)
    db.delete(p)
    audit(db, "hh_posten_delete", actor=user, target=str(posten_id),
          request=request)
    db.commit()
    return JSONResponse({"ok": True})


# ── Ideen ────────────────────────────────────────────────────────────────

@router.post("/api/haushalt/ideen")
def idee_speichern(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    titel = (payload.get("titel") or "").strip()[:200]
    if not titel:
        return JSONResponse({"ok": False, "error": "Bitte einen Titel angeben."},
                            status_code=400)

    iid = payload.get("id")
    if iid:
        i = db.get(HhIdee, int(iid))
        if not i or i.user_id != user.id:
            return JSONResponse({"ok": False, "error": "Idee nicht gefunden."},
                                status_code=404)
    else:
        i = HhIdee(user_id=user.id)
        db.add(i)

    cent = hh.to_cent(payload.get("betrag"))
    art = payload.get("art")
    i.zieljahr = _jahr(payload.get("zieljahr"), date.today().year + 1)
    # Ohne ausdrückliche Wahl schlägt die 1000-€-Grenze den Topf vor.
    i.art = art if art in hh.ARTEN else hh.art_fuer(cent)
    i.titel = titel
    i.betrag_cent = cent
    i.begruendung = (payload.get("begruendung") or "").strip()[:4000]
    try:
        i.prioritaet = max(1, min(3, int(payload.get("prioritaet") or 2)))
    except (TypeError, ValueError):
        i.prioritaet = 2
    status = payload.get("status")
    if status in hh.IDEE_STATUS:
        i.status = status
    db.flush()
    audit(db, "hh_idee_save", actor=user, target=str(i.id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": i.id})


@router.post("/api/haushalt/ideen/{idee_id}/delete")
def idee_loeschen(
    request: Request,
    idee_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    i = db.get(HhIdee, idee_id)
    if not i or i.user_id != user.id:
        return JSONResponse({"ok": False, "error": "Idee nicht gefunden."},
                            status_code=404)
    db.delete(i)
    audit(db, "hh_idee_delete", actor=user, target=str(idee_id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/haushalt/ideen/{idee_id}/vorgang")
def idee_zu_vorgang(
    request: Request,
    idee_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Bewilligte Idee → echter Vorgang.

    Die Idee bleibt stehen (Status `bewilligt`) und merkt sich den Vorgang;
    so bleibt die Haushaltsplanung des Jahres vollständig nachlesbar.
    """
    i = db.get(HhIdee, idee_id)
    if not i or i.user_id != user.id:
        return JSONResponse({"ok": False, "error": "Idee nicht gefunden."},
                            status_code=404)
    if i.vorgang_id and db.get(Vorgang, i.vorgang_id):
        return JSONResponse({"ok": True, "vorgang_id": i.vorgang_id,
                             "schon_da": True})

    v = Vorgang(user_id=user.id, titel=i.titel,
                beschreibung=i.begruendung,
                kategorie="Anschaffung",
                status="geplant",
                haushaltsjahr=i.zieljahr)
    db.add(v)
    db.flush()
    i.vorgang_id = v.id
    i.status = "bewilligt"
    audit(db, "hh_idee_zu_vorgang", actor=user, target=str(v.id),
          detail=f"idee={idee_id}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "vorgang_id": v.id})
