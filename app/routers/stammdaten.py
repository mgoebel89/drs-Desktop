"""Stammdaten: Jahrgang → Klasse → Schüler, dazu Lerngruppen und Fächer.

Die Hierarchie:

  Jahrgang ("BSMT 23")   trägt die Lernfelder/Fächer (mit Stundenansatz)
    └─ Klasse ("BSMT 23 a")   trägt die Schüler
  Lerngruppe                  ist das, was im STUNDENPLAN steht

Klasse und Lerngruppe sind bewusst getrennt: Die Lerngruppe trägt den
`klassen_key`, und der ist Teil des key4, an dem alle Stundennotizen hängen —
nach dem Anlegen UNVERÄNDERLICH. Deshalb sind MT23a und das zusammengelegte
MT23 zwei Lerngruppen mit zwei Schlüsseln; ihre Notizen mischen sich nie. Eine
Klasse dagegen darf man jederzeit umbenennen.

Hier leben nur die SEITEN (plus der Fächer-Katalog und die Zuordnungs-Korrektur,
die beide klassische Formulare benutzen). Angelegt und bearbeitet wird über die
Assistenten und Detail-Modals, die auf `app/routers/stammdaten_api.py` sprechen —
die Regeln stehen dort, damit sie nicht an zwei Stellen gepflegt werden müssen.

`/api/stammdaten/suggest-keys` liest die real vorhandenen Keys aus dem Bestand
aus und bietet sie zur 1:1-Übernahme an.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (Exam, LessonNote, LessonSeriesOverride, Student,
                        TtFach, TtJahrgang, TtJahrgangFach, TtKlasse,
                        TtLerngruppeKlasse, TtRow, TtSchulklasse, User)
from app.services.lerngruppen import klassen_der_lerngruppe
from app.templating import templates

router = APIRouter()


def _redir(pfad: str, ok: str = "", err: str = "") -> RedirectResponse:
    if ok:
        pfad += ("&" if "?" in pfad else "?") + f"ok={ok.replace(' ', '+')}"
    if err:
        pfad += ("&" if "?" in pfad else "?") + f"err={err.replace(' ', '+')}"
    return RedirectResponse(pfad, status_code=303)


# ── Vorschläge aus dem Bestand ───────────────────────────────────────────

def _suggest_klassen(db: Session, user: User) -> list[dict]:
    """Distinct klassen_key aus Notizen, Schülern und Prüfungen, mit Trefferzahl."""
    counts: dict[str, int] = {}
    sources: dict[str, set[str]] = {}

    def add(key: str, quelle: str, n: int = 1) -> None:
        key = (key or "").strip()
        if not key:
            return
        counts[key] = counts.get(key, 0) + n
        sources.setdefault(key, set()).add(quelle)

    for kk, n in db.execute(
        select(LessonNote.klassen_key, func.count())
        .where(LessonNote.user_id == user.id)
        .group_by(LessonNote.klassen_key)
    ).all():
        add(kk, "Notizen", n)
    for kk, n in db.execute(
        select(Student.klassen_key, func.count())
        .where(Student.owner_user_id == user.id)
        .group_by(Student.klassen_key)
    ).all():
        add(kk, "Schüler", n)
    for kk, n in db.execute(
        select(Exam.klassen_key, func.count())
        .where(Exam.owner_user_id == user.id)
        .group_by(Exam.klassen_key)
    ).all():
        add(kk, "Prüfungen", n)

    vorhanden = {
        k for (k,) in db.execute(
            select(TtKlasse.klassen_key).where(TtKlasse.user_id == user.id)
        ).all()
    }
    return [
        {"key": k, "count": counts[k], "sources": sorted(sources[k]),
         "exists": k in vorhanden}
        for k in sorted(counts)
    ]


def _suggest_faecher(db: Session, user: User) -> list[dict]:
    """Distinct subjects_key aus Notizen + Reihen-Overrides. Der Override liefert
    gleich einen brauchbaren Anzeigenamen mit."""
    counts: dict[str, int] = {}
    namen: dict[str, str] = {}

    for sk, n in db.execute(
        select(LessonNote.subjects_key, func.count())
        .where(LessonNote.user_id == user.id)
        .group_by(LessonNote.subjects_key)
    ).all():
        if (sk or "").strip():
            counts[sk] = counts.get(sk, 0) + n

    for so in db.query(LessonSeriesOverride).filter(
        LessonSeriesOverride.user_id == user.id,
    ).all():
        if so.subjects_key and so.display_name.strip():
            counts.setdefault(so.subjects_key, 0)
            namen[so.subjects_key] = so.display_name.strip()

    vorhanden = {
        k for (k,) in db.execute(
            select(TtFach.subjects_key).where(TtFach.user_id == user.id)
        ).all()
    }
    return [
        {"key": k, "count": counts[k], "vorschlag_name": namen.get(k, k),
         "exists": k in vorhanden}
        for k in sorted(counts)
    ]


@router.get("/api/stammdaten/suggest-keys")
def suggest_keys(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return JSONResponse({
        "klassen": _suggest_klassen(db, user),
        "faecher": _suggest_faecher(db, user),
    })


# ── Jahrgänge ────────────────────────────────────────────────────────────

def _jahrgang(db: Session, user: User, jid: int) -> TtJahrgang:
    j = db.get(TtJahrgang, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404)
    return j


@router.get("/stammdaten/jahrgaenge")
def jahrgaenge_alt():
    """Alter Pfad — die Jahrgänge stehen jetzt auf der Stammdaten-Startseite."""
    return RedirectResponse("/stammdaten", status_code=307)


@router.get("/stammdaten", response_class=HTMLResponse)
def stammdaten_start(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    alle: str = "",
):
    """Bereichs-Startseite: Kacheln als Einstieg, darunter die Jahrgänge als Karten."""
    q = select(TtJahrgang).where(TtJahrgang.user_id == user.id)
    if alle != "1":
        q = q.where(TtJahrgang.active.is_(True))
    jahrgaenge = list(db.scalars(
        q.order_by(TtJahrgang.position, TtJahrgang.name)).all())

    inaktiv = db.scalar(select(func.count()).select_from(TtJahrgang).where(
        TtJahrgang.user_id == user.id, TtJahrgang.active.is_(False))) or 0

    zahlen = {}
    for j in jahrgaenge:
        zahlen[j.id] = {
            "klassen": db.scalar(select(func.count()).select_from(TtSchulklasse)
                                 .where(TtSchulklasse.jahrgang_id == j.id)) or 0,
            "faecher": db.scalar(select(func.count()).select_from(TtJahrgangFach)
                                 .where(TtJahrgangFach.jahrgang_id == j.id)) or 0,
            "schueler": db.scalar(select(func.count()).select_from(Student)
                                  .where(Student.jahrgang_id == j.id)) or 0,
            "pool": db.scalar(select(func.count()).select_from(Student).where(
                Student.jahrgang_id == j.id,
                Student.schulklasse_id.is_(None))) or 0,
        }

    gruppen_gesamt = db.scalar(select(func.count()).select_from(TtKlasse).where(
        TtKlasse.user_id == user.id, TtKlasse.active.is_(True))) or 0
    kombis = db.scalar(select(func.count()).select_from(TtKlasse).where(
        TtKlasse.user_id == user.id, TtKlasse.active.is_(True),
        TtKlasse.art != "klasse")) or 0
    faecher_gesamt = db.scalar(select(func.count()).select_from(TtFach).where(
        TtFach.user_id == user.id, TtFach.active.is_(True))) or 0
    # Was der ratende Backfill offen gelassen hat: Lerngruppen ohne Jahrgang.
    offen = db.scalar(select(func.count()).select_from(TtKlasse).where(
        TtKlasse.user_id == user.id, TtKlasse.jahrgang_id.is_(None))) or 0

    return templates.TemplateResponse(request, "stammdaten/index.html", {
        "jahrgaenge": jahrgaenge, "zahlen": zahlen,
        "alle": alle == "1", "inaktiv_count": inaktiv,
        "summe": {
            "jahrgaenge": len(jahrgaenge),
            "klassen": sum(z["klassen"] for z in zahlen.values()),
            "schueler": sum(z["schueler"] for z in zahlen.values()),
            "gruppen": gruppen_gesamt, "kombis": kombis,
            "faecher": faecher_gesamt, "offen": offen,
        },
    })


@router.get("/stammdaten/jahrgaenge/{jid}", response_class=HTMLResponse)
def jahrgang_detail(
    request: Request,
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    j = _jahrgang(db, user, jid)

    klassen = list(db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.jahrgang_id == j.id)
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all())
    schuelerzahl = {
        k.id: db.scalar(select(func.count()).select_from(Student)
                        .where(Student.schulklasse_id == k.id)) or 0
        for k in klassen
    }
    jf = list(db.scalars(
        select(TtJahrgangFach).where(TtJahrgangFach.jahrgang_id == j.id)
        .order_by(TtJahrgangFach.position)).all())
    belegt = {x.fach_id for x in jf}
    katalog = [f for f in db.scalars(
        select(TtFach).where(TtFach.user_id == user.id, TtFach.active.is_(True))
        .order_by(TtFach.position, TtFach.subjects_key)).all()
        if f.id not in belegt]

    gruppen = list(db.scalars(
        select(TtKlasse).where(TtKlasse.user_id == user.id,
                               TtKlasse.jahrgang_id == j.id)
        .order_by(TtKlasse.position, TtKlasse.klassen_key)).all())
    gruppen_klassen = {g.id: klassen_der_lerngruppe(db, g) for g in gruppen}

    pool = list(db.scalars(
        select(Student).where(Student.owner_user_id == user.id,
                              Student.jahrgang_id == j.id,
                              Student.schulklasse_id.is_(None))
        .order_by(Student.nachname, Student.vorname)).all())

    return templates.TemplateResponse(request, "stammdaten/jahrgang_detail.html", {
        "j": j, "klassen": klassen, "schuelerzahl": schuelerzahl,
        "jf": jf, "katalog": katalog,
        "gruppen": gruppen, "gruppen_klassen": gruppen_klassen,
        "pool": pool,
    })


# ── Lerngruppen (das, was im Stundenplan steht) ──────────────────────────

@router.get("/stammdaten/klassen")
def klassen_alt():
    """Alter Pfad — die Klassenliste ist jetzt die Lerngruppen-Liste."""
    return RedirectResponse("/stammdaten/lerngruppen", status_code=307)


@router.get("/stammdaten/lerngruppen", response_class=HTMLResponse)
def lerngruppen_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    alle: str = "",
):
    q = select(TtKlasse).where(TtKlasse.user_id == user.id)
    if alle != "1":
        q = q.where(TtKlasse.active.is_(True))
    gruppen = list(db.scalars(
        q.order_by(TtKlasse.position, TtKlasse.klassen_key)).all())

    jahrgaenge = list(db.scalars(
        select(TtJahrgang).where(TtJahrgang.user_id == user.id,
                                 TtJahrgang.active.is_(True))
        .order_by(TtJahrgang.position, TtJahrgang.name)).all())
    klassen = list(db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.user_id == user.id,
                                    TtSchulklasse.active.is_(True))
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all())

    return templates.TemplateResponse(request, "stammdaten/lerngruppen.html", {
        "gruppen": gruppen,
        "mitglieder": {g.id: klassen_der_lerngruppe(db, g) for g in gruppen},
        "jahrgaenge": jahrgaenge, "klassen": klassen,
        "alle": alle == "1",
        "suggest": [s for s in _suggest_klassen(db, user) if not s["exists"]],
    })


@router.get("/api/stammdaten/schulklassen/{kid}/schueler")
def klasse_schueler(
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Schüler einer Klasse — für die Teilgruppen-Auswahl im Lerngruppen-Dialog."""
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    rows = db.scalars(
        select(Student).where(Student.schulklasse_id == k.id,
                              Student.active.is_(True))
        .order_by(Student.nachname, Student.vorname)).all()
    return JSONResponse([
        {"id": s.id, "name": f"{s.nachname}, {s.vorname}".strip(", ")}
        for s in rows
    ])


@router.post("/stammdaten/klassen/import")
def klassen_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Übernimmt alle noch fehlenden Bestands-Keys als Lerngruppen."""
    offen = [s for s in _suggest_klassen(db, user) if not s["exists"]]
    pos = db.scalar(select(func.count()).select_from(TtKlasse)
                    .where(TtKlasse.user_id == user.id)) or 0
    for i, s in enumerate(offen):
        db.add(TtKlasse(user_id=user.id, klassen_key=s["key"],
                        display_name=s["key"], position=pos + i, art="klasse"))
    audit(db, "tt_klassen_imported", actor=user,
          detail=f"{len(offen)} übernommen", request=request)
    db.commit()
    return _redir("/stammdaten/zuordnung", ok=f"{len(offen)} übernommen")


# ── Zuordnung prüfen (nach dem Backfill) ─────────────────────────────────

@router.get("/stammdaten/zuordnung", response_class=HTMLResponse)
def zuordnung(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Die Migration RÄT den Jahrgang aus dem Klassennamen. Hier wird das gerade
    gezogen — ohne je einen Schlüssel anzufassen."""
    gruppen = list(db.scalars(
        select(TtKlasse).where(TtKlasse.user_id == user.id)
        .order_by(TtKlasse.jahrgang_id.is_(None).desc(),
                  TtKlasse.position, TtKlasse.klassen_key)).all())
    jahrgaenge = list(db.scalars(
        select(TtJahrgang).where(TtJahrgang.user_id == user.id)
        .order_by(TtJahrgang.position, TtJahrgang.name)).all())
    klassen = list(db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.user_id == user.id)
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all())
    ohne_klasse = list(db.scalars(
        select(Student).where(Student.owner_user_id == user.id,
                              Student.schulklasse_id.is_(None))
        .order_by(Student.nachname)).all())

    return templates.TemplateResponse(request, "stammdaten/zuordnung.html", {
        "gruppen": gruppen, "jahrgaenge": jahrgaenge, "klassen": klassen,
        "mitglieder": {g.id: {k.id for k in klassen_der_lerngruppe(db, g)}
                       for g in gruppen},
        "ohne_klasse": ohne_klasse,
    })


@router.post("/stammdaten/zuordnung/{lgid}")
def zuordnung_save(
    lgid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    jahrgang_id: str = Form(""),
    art: str = Form("klasse"),
    schulklasse_ids: Annotated[list[int], Form()] = [],
):
    lg = db.get(TtKlasse, lgid)
    if not lg or lg.user_id != user.id:
        raise HTTPException(404)
    lg.jahrgang_id = int(jahrgang_id) if jahrgang_id.strip() else None
    if art in ("klasse", "kombi", "gruppe"):
        lg.art = art
    db.execute(TtLerngruppeKlasse.__table__.delete()
               .where(TtLerngruppeKlasse.lerngruppe_id == lg.id))
    for kid in schulklasse_ids:
        k = db.get(TtSchulklasse, kid)
        if k and k.user_id == user.id:
            db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=k.id))
    db.commit()
    return _redir("/stammdaten/zuordnung", ok="Gespeichert")


# ── Fächer-Katalog ───────────────────────────────────────────────────────

@router.get("/stammdaten/faecher", response_class=HTMLResponse)
def faecher_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.scalars(
        select(TtFach).where(TtFach.user_id == user.id)
        .order_by(TtFach.position, TtFach.subjects_key)
    ).all()
    verwendet = {
        fid: n for fid, n in db.execute(
            select(TtJahrgangFach.fach_id, func.count())
            .group_by(TtJahrgangFach.fach_id)).all()
    }
    return templates.TemplateResponse(request, "stammdaten/faecher.html", {
        "faecher": rows,
        "verwendet": verwendet,
        "suggest": [s for s in _suggest_faecher(db, user) if not s["exists"]],
    })


@router.post("/stammdaten/faecher")
def faecher_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    subjects_key: str = Form(...),
    display_name: str = Form(""),
    kuerzel: str = Form(""),
):
    key = subjects_key.strip()[:255]
    if not key:
        raise HTTPException(400, "Schlüssel fehlt.")
    exists = db.scalar(select(TtFach.id).where(
        TtFach.user_id == user.id, TtFach.subjects_key == key))
    if exists:
        return _redir("/stammdaten/faecher", err="Dieses Fach gibt es schon")
    pos = db.scalar(select(func.count()).select_from(TtFach)
                    .where(TtFach.user_id == user.id)) or 0
    db.add(TtFach(
        user_id=user.id, subjects_key=key,
        display_name=(display_name.strip() or key)[:200],
        kuerzel=kuerzel.strip()[:40], position=pos,
    ))
    audit(db, "tt_fach_added", actor=user, target=key, request=request)
    db.commit()
    return _redir("/stammdaten/faecher")


@router.post("/stammdaten/faecher/import")
def faecher_import(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    offen = [s for s in _suggest_faecher(db, user) if not s["exists"]]
    pos = db.scalar(select(func.count()).select_from(TtFach)
                    .where(TtFach.user_id == user.id)) or 0
    for i, s in enumerate(offen):
        db.add(TtFach(user_id=user.id, subjects_key=s["key"],
                      display_name=s["vorschlag_name"], position=pos + i))
    audit(db, "tt_faecher_imported", actor=user,
          detail=f"{len(offen)} übernommen", request=request)
    db.commit()
    return _redir("/stammdaten/faecher", ok=str(len(offen)))


@router.post("/stammdaten/faecher/{fid}")
def faecher_edit(
    fid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    f = db.get(TtFach, fid)
    if not f or f.user_id != user.id:
        raise HTTPException(404)
    f.display_name = (display_name.strip() or f.subjects_key)[:200]
    f.kuerzel = kuerzel.strip()[:40]
    f.active = active == "1"
    db.commit()
    return _redir("/stammdaten/faecher")


@router.post("/stammdaten/faecher/{fid}/delete")
def faecher_delete(
    request: Request,
    fid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    f = db.get(TtFach, fid)
    if not f or f.user_id != user.id:
        raise HTTPException(404)
    benutzt = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.fach_id == f.id))
    if benutzt:
        f.active = False
        db.commit()
        return _redir("/stammdaten/faecher",
                      err="Fach wird im Stundenplan benutzt und wurde nur stillgelegt")
    db.execute(TtJahrgangFach.__table__.delete()
               .where(TtJahrgangFach.fach_id == f.id))
    key = f.subjects_key
    db.delete(f)
    audit(db, "tt_fach_deleted", actor=user, target=key, request=request)
    db.commit()
    return _redir("/stammdaten/faecher")
