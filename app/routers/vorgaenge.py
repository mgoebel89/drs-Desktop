"""Vorgänge & Projekte: Übersicht, Detail mit Zeitleiste, Budget.

Der Typen-Katalog der Zeitleiste steht in `app/services/vorgaenge.py`, die
Budget-Rechnung in `app/services/haushalt.py`. Aufgaben-Einträge legen eine
echte Vikunja-Aufgabe im fest konfigurierten Projekt an — mit dem Label
„Vorgang: <Titel>", damit sie im Aufgaben-Modul zuzuordnen ist.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (HhPosten, TtKlasse, User, Vorgang, VorgangEintrag,
                        VorgangKontakt)
from app.services import haushalt as hh
from app.services import vikunja_client as vk
from app.services import vorgaenge as vg
from app.services.lerngruppen import lerngruppen
from app.templating import templates

router = APIRouter()

VORGANG_LABEL_COLOR = "1f6feb"


def _own(db: Session, user: User, vorgang_id: int) -> Vorgang | None:
    v = db.get(Vorgang, vorgang_id)
    return v if v and v.user_id == user.id else None


def _vorgang_dict(db: Session, v: Vorgang, lg_namen: dict[int, str]) -> dict:
    return {
        "id": v.id,
        "titel": v.titel,
        "beschreibung": v.beschreibung,
        "kategorie": v.kategorie,
        "status": v.status,
        "status_label": vg.STATUS_LABEL.get(v.status, v.status),
        "lerngruppe_id": v.lerngruppe_id,
        "lerngruppe": lg_namen.get(v.lerngruppe_id or 0, ""),
        "haushaltsjahr": v.haushaltsjahr or 0,
        "updated_at": (v.updated_at or v.created_at or datetime.utcnow()).isoformat(),
    }


def _lerngruppen_namen(db: Session, user: User) -> dict[int, str]:
    """Anzeigenamen aller Lerngruppen — auch stillgelegte.

    Der Picker zeigt nur aktive; ein alter Vorgang soll seine Klasse aber
    weiter benennen können, statt eine nackte Zahl anzuzeigen.
    """
    rows = db.scalars(select(TtKlasse).where(TtKlasse.user_id == user.id)).all()
    return {k.id: (k.display_name or k.klassen_key) for k in rows}


# ── Seiten ───────────────────────────────────────────────────────────────

@router.get("/vorgaenge", response_class=HTMLResponse)
def vorgaenge_page(
    request: Request,
    user: Annotated[User, Depends(require_user)],
):
    return templates.TemplateResponse(request, "vorgaenge/list.html", {
        "status_label": vg.STATUS_LABEL,
    })


@router.get("/vorgaenge/{vorgang_id}", response_class=HTMLResponse)
def vorgang_detail_page(
    request: Request,
    vorgang_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    v = _own(db, user, vorgang_id)
    if not v:
        return RedirectResponse("/vorgaenge", status_code=303)
    return templates.TemplateResponse(request, "vorgaenge/detail.html", {
        "vorgang_id": v.id,
        "titel": v.titel,
    })


# ── Stammdaten für die Dialoge ───────────────────────────────────────────

@router.get("/api/vorgaenge/stamm")
def vorgaenge_stamm(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    jahr: int = 0,
):
    """Alles, was die Dialoge brauchen — in einem Aufruf."""
    j = jahr or date.today().year
    return JSONResponse({
        "ok": True,
        "typen": [{"typ": t, "label": d["label"], "hinweis": d.get("hinweis", ""),
                   "betrag": bool(d.get("betrag")), "posten": bool(d.get("posten"))}
                  for t, d in vg.TYPEN.items()],
        "status": [{"wert": s, "label": vg.STATUS_LABEL[s]} for s in vg.STATUS],
        "wege": [{"wert": w, "label": vg.WEG_LABEL[w]} for w in vg.WEGE],
        "score_label": vg.SCORE_LABEL,
        "lerngruppen": [{"id": g.id, "name": g.display_name or g.klassen_key}
                        for g in lerngruppen(db, user)],
        "posten": hh.posten_auswahl(db, user, j),
        "jahre": hh.bekannte_jahre(db, user),
        "kontakte": [k.name for k in db.scalars(
            select(VorgangKontakt)
            .where(VorgangKontakt.user_id == user.id)
            .order_by(VorgangKontakt.last_used.desc())).all()][:50],
        "vikunja_bereit": vk.is_configured(user),
    })


# ── Übersicht ────────────────────────────────────────────────────────────

@router.get("/api/vorgaenge")
def vorgaenge_liste(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    suche: str = "",
    status: str = "",
    jahr: int = 0,
):
    q = select(Vorgang).where(Vorgang.user_id == user.id)
    if status in vg.STATUS:
        q = q.where(Vorgang.status == status)
    if jahr:
        q = q.where(Vorgang.haushaltsjahr == jahr)
    rows = list(db.scalars(q.order_by(Vorgang.updated_at.desc())).all())

    begriff = suche.strip().lower()
    if begriff:
        rows = [v for v in rows
                if begriff in (v.titel or "").lower()
                or begriff in (v.beschreibung or "").lower()
                or begriff in (v.kategorie or "").lower()]

    lg = _lerngruppen_namen(db, user)
    # Kosten je Vorgang in einem Rutsch, statt je Karte eine Abfrage.
    kosten: dict[int, int] = {}
    for vid, cent in db.execute(
        select(VorgangEintrag.vorgang_id, VorgangEintrag.betrag_cent)
        .join(Vorgang, Vorgang.id == VorgangEintrag.vorgang_id)
        .where(Vorgang.user_id == user.id, VorgangEintrag.typ == "kosten")
    ).all():
        kosten[vid] = kosten.get(vid, 0) + (cent or 0)

    aktiv, beendet = [], []
    for v in rows:
        d = _vorgang_dict(db, v, lg)
        d["kosten"] = hh.to_euro(kosten.get(v.id, 0))
        (beendet if v.status == "beendet" else aktiv).append(d)
    return JSONResponse({"ok": True, "aktiv": aktiv, "beendet": beendet,
                         "kategorien": sorted({v.kategorie for v in rows if v.kategorie})})


@router.post("/api/vorgaenge")
def vorgang_speichern(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    titel = (payload.get("titel") or "").strip()[:250]
    if not titel:
        return JSONResponse({"ok": False, "error": "Bitte einen Titel angeben."},
                            status_code=400)

    vid = payload.get("id")
    if vid:
        v = _own(db, user, int(vid))
        if not v:
            return JSONResponse({"ok": False, "error": "Vorgang nicht gefunden."},
                                status_code=404)
    else:
        v = Vorgang(user_id=user.id)
        db.add(v)

    v.titel = titel
    v.beschreibung = (payload.get("beschreibung") or "").strip()[:8000]
    v.kategorie = (payload.get("kategorie") or "").strip()[:80]
    status = payload.get("status")
    if status in vg.STATUS:
        v.status = status
    lg = payload.get("lerngruppe_id")
    v.lerngruppe_id = int(lg) if lg else None
    try:
        v.haushaltsjahr = int(payload.get("haushaltsjahr") or 0)
    except (TypeError, ValueError):
        v.haushaltsjahr = 0
    db.flush()
    audit(db, "vorgang_save", actor=user, target=str(v.id), request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": v.id})


@router.post("/api/vorgaenge/{vorgang_id}/delete")
def vorgang_loeschen(
    request: Request,
    vorgang_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    v = _own(db, user, vorgang_id)
    if not v:
        return JSONResponse({"ok": False, "error": "Vorgang nicht gefunden."},
                            status_code=404)
    # Die Einträge hängen per CASCADE dran und gehen mit.
    db.delete(v)
    audit(db, "vorgang_delete", actor=user, target=str(vorgang_id), request=request)
    db.commit()
    return JSONResponse({"ok": True})


# ── Detail ───────────────────────────────────────────────────────────────

def _eintrag_dict(e: VorgangEintrag) -> dict:
    p = vg.load_payload(e.payload_json)
    d = {
        "id": e.id,
        "typ": e.typ,
        "typ_label": vg.TYPEN.get(e.typ, {}).get("label", e.typ),
        "datum": e.datum,
        "erledigt": bool(e.erledigt),
        "betrag": hh.to_euro(e.betrag_cent) if e.typ in vg.BETRAG_TYPEN else None,
        "hh_posten_id": e.hh_posten_id,
        "payload": p,
    }
    if e.typ == "entscheidung":
        d["matrix"] = vg.matrix_auswertung(p)
    return d


@router.get("/api/vorgaenge/{vorgang_id}")
def vorgang_detail(
    vorgang_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    v = _own(db, user, vorgang_id)
    if not v:
        return JSONResponse({"ok": False, "error": "Vorgang nicht gefunden."},
                            status_code=404)

    eintraege = list(db.scalars(
        select(VorgangEintrag)
        .where(VorgangEintrag.vorgang_id == v.id)
        # Neueste zuerst; bei gleichem Datum entscheidet die Anlage-Reihenfolge,
        # damit ein frisch angelegter Eintrag oben steht.
        .order_by(VorgangEintrag.datum.desc(), VorgangEintrag.id.desc())
    ).all())

    # Budget: was dieser Vorgang auf welchen Posten gebucht hat.
    posten = {p.id: p for p in hh.posten_des_jahres(
        db, user, v.haushaltsjahr or date.today().year)}
    je_posten: dict[int, int] = {}
    for e in eintraege:
        if e.typ == "kosten" and e.hh_posten_id:
            je_posten[e.hh_posten_id] = je_posten.get(e.hh_posten_id, 0) + (e.betrag_cent or 0)

    gesamt_verbrauch = hh.verbrauch_je_posten(db, user, list(je_posten.keys()))
    budget = []
    for pid, cent in je_posten.items():
        p = posten.get(pid)
        if not p:
            # Posten aus einem anderen Jahr — Buchung trotzdem zeigen.
            p = db.get(HhPosten, pid)
        gesamt = gesamt_verbrauch.get(pid, 0)
        budget.append({
            "posten_id": pid,
            "bezeichnung": (p.bezeichnung if p else "(gelöschter Posten)"),
            "art": (p.art if p else ""),
            "jahr": (p.jahr if p else 0),
            "dieser_vorgang": hh.to_euro(cent),
            "budget": hh.to_euro(p.betrag_cent if p else 0),
            "verbrauch_gesamt": hh.to_euro(gesamt),
            "rest": hh.to_euro((p.betrag_cent if p else 0) - gesamt),
        })
    budget.sort(key=lambda b: (b["art"], b["bezeichnung"]))

    lg = _lerngruppen_namen(db, user)
    return JSONResponse({
        "ok": True,
        "vorgang": _vorgang_dict(db, v, lg),
        "eintraege": [_eintrag_dict(e) for e in eintraege],
        "budget": budget,
        "angebote": [{"id": e.id,
                      "name": vg.load_payload(e.payload_json).get("anbieter", ""),
                      "preis": hh.to_euro(e.betrag_cent)}
                     for e in eintraege if e.typ == "angebot"],
    })


# ── Einträge ─────────────────────────────────────────────────────────────

def _merke_kontakte(db: Session, user: User, namen: list[str]) -> None:
    """Empfängernamen fürs Vorschlagen merken (Freitext mit Gedächtnis)."""
    for name in {n.strip()[:120] for n in namen if n and n.strip()}:
        k = db.scalars(select(VorgangKontakt).where(
            VorgangKontakt.user_id == user.id,
            VorgangKontakt.name == name)).first()
        if k:
            k.last_used = datetime.utcnow()
        else:
            db.add(VorgangKontakt(user_id=user.id, name=name))


@router.post("/api/vorgaenge/{vorgang_id}/eintrag")
def eintrag_speichern(
    request: Request,
    vorgang_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    v = _own(db, user, vorgang_id)
    if not v:
        return JSONResponse({"ok": False, "error": "Vorgang nicht gefunden."},
                            status_code=404)

    typ = payload.get("typ")
    if typ not in vg.TYPEN:
        return JSONResponse({"ok": False, "error": "Unbekannter Eintragstyp."},
                            status_code=400)

    eid = payload.get("id")
    if eid:
        e = db.get(VorgangEintrag, int(eid))
        if not e or e.vorgang_id != v.id:
            return JSONResponse({"ok": False, "error": "Eintrag nicht gefunden."},
                                status_code=404)
    else:
        e = VorgangEintrag(vorgang_id=v.id)
        db.add(e)

    e.typ = typ
    e.datum = (payload.get("datum") or date.today().isoformat())[:10]
    e.erledigt = bool(payload.get("erledigt"))
    p = vg.normalize_payload(typ, payload.get("payload"))

    e.betrag_cent = hh.to_cent(payload.get("betrag")) if typ in vg.BETRAG_TYPEN else 0
    if typ in vg.POSTEN_TYPEN:
        pid = payload.get("hh_posten_id")
        # Ein fremder Posten wäre eine stille Fehlbuchung — deshalb prüfen.
        if pid:
            posten = db.get(HhPosten, int(pid))
            e.hh_posten_id = posten.id if posten and posten.user_id == user.id else None
        else:
            e.hh_posten_id = None
    else:
        e.hh_posten_id = None

    if typ == "weiterleitung":
        _merke_kontakte(db, user, [x.get("name", "") for x in p.get("empfaenger", [])])

    # Aufgabe: beim ersten Speichern in Vikunja anlegen (das feste Projekt).
    hinweis = ""
    if typ == "aufgabe" and not p.get("vikunja_task_id") and vk.is_configured(user):
        try:
            label_ids = []
            lb = vk.ensure_label(user, f"Vorgang: {v.titel}"[:100], VORGANG_LABEL_COLOR)
            if lb.get("id"):
                label_ids.append(int(lb["id"]))
            task = vk.create_task(
                user, title=p.get("titel") or v.titel,
                due_date=p.get("faellig") or "",
                priority=p.get("prioritaet") or 0,
                label_ids=label_ids)
            if task.get("id"):
                p["vikunja_task_id"] = int(task["id"])
        except vk.VikunjaError as ex:
            hinweis = f"Der Eintrag ist gespeichert, aber Vikunja meldet: {ex}"

    e.payload_json = vg.dump_payload(p)
    db.flush()
    audit(db, "vorgang_eintrag_save", actor=user, target=str(e.id),
          detail=typ, request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": e.id, "hinweis": hinweis})


@router.post("/api/vorgaenge/{vorgang_id}/eintrag/{eintrag_id}/delete")
def eintrag_loeschen(
    request: Request,
    vorgang_id: int, eintrag_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    v = _own(db, user, vorgang_id)
    e = db.get(VorgangEintrag, eintrag_id) if v else None
    if not v or not e or e.vorgang_id != v.id:
        return JSONResponse({"ok": False, "error": "Eintrag nicht gefunden."},
                            status_code=404)
    db.delete(e)
    audit(db, "vorgang_eintrag_delete", actor=user, target=str(eintrag_id),
          request=request)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/vorgaenge/{vorgang_id}/aufgaben/abgleichen")
def aufgaben_abgleichen(
    vorgang_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Erledigt-Status der Vikunja-Aufgaben zurückspiegeln.

    Bewusst auf Knopfdruck und nicht bei jedem Seitenaufbau: pro Aufgabe ein
    Request, und ein klemmendes Vikunja soll die Zeitleiste nicht aufhalten.
    """
    v = _own(db, user, vorgang_id)
    if not v:
        return JSONResponse({"ok": False, "error": "Vorgang nicht gefunden."},
                            status_code=404)
    if not vk.is_configured(user):
        return JSONResponse({"ok": False, "error": "Vikunja ist nicht eingerichtet."},
                            status_code=400)

    geaendert = 0
    fehler = ""
    for e in db.scalars(select(VorgangEintrag).where(
            VorgangEintrag.vorgang_id == v.id,
            VorgangEintrag.typ == "aufgabe")).all():
        p = vg.load_payload(e.payload_json)
        tid = p.get("vikunja_task_id")
        if not tid:
            continue
        try:
            task = vk.get_task(user, int(tid))
        except vk.VikunjaError as ex:
            fehler = str(ex)
            continue
        neu = bool(task.get("done"))
        titel = task.get("title") or p.get("titel")
        if neu != bool(e.erledigt) or titel != p.get("titel"):
            e.erledigt = neu
            p["titel"] = titel
            e.payload_json = vg.dump_payload(p)
            geaendert += 1
    db.commit()
    return JSONResponse({"ok": True, "geaendert": geaendert, "fehler": fehler})
