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
                        TtLerngruppeKlasse, TtLerngruppeStudent, TtRow,
                        TtSchulklasse, User)
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


@router.get("/stammdaten/jahrgaenge", response_class=HTMLResponse)
def jahrgaenge_list(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    alle: str = "",
):
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
    return templates.TemplateResponse(request, "stammdaten/jahrgaenge.html", {
        "jahrgaenge": jahrgaenge, "zahlen": zahlen,
        "alle": alle == "1", "inaktiv_count": inaktiv,
    })


@router.post("/stammdaten/jahrgaenge")
def jahrgang_add(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(...),
    kuerzel: str = Form(""),
):
    n = name.strip()[:120]
    if not n:
        raise HTTPException(400, "Name fehlt.")
    if db.scalar(select(TtJahrgang.id).where(
            TtJahrgang.user_id == user.id, TtJahrgang.name == n)):
        return _redir("/stammdaten/jahrgaenge", err="Diesen Jahrgang gibt es schon")
    pos = db.scalar(select(func.count()).select_from(TtJahrgang)
                    .where(TtJahrgang.user_id == user.id)) or 0
    j = TtJahrgang(user_id=user.id, name=n, kuerzel=kuerzel.strip()[:40],
                   position=pos)
    db.add(j)
    audit(db, "tt_jahrgang_added", actor=user, target=n, request=request)
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{j.id}")


@router.post("/stammdaten/jahrgaenge/{jid}")
def jahrgang_edit(
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    j = _jahrgang(db, user, jid)
    j.name = (name.strip() or j.name)[:120]
    j.kuerzel = kuerzel.strip()[:40]
    j.active = active == "1"
    db.commit()
    return _redir("/stammdaten/jahrgaenge")


@router.post("/stammdaten/jahrgaenge/{jid}/delete")
def jahrgang_delete(
    request: Request,
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Löschen nur, wenn nichts mehr dranhängt — sonst stilllegen.

    Ein Jahrgang mit Klassen zu löschen würde Schüler und Lerngruppen mitreißen
    und damit die Notizen der Vergangenheit abhängen. Stilllegen blendet ihn
    überall aus und ist wiederherstellbar."""
    j = _jahrgang(db, user, jid)
    klassen = db.scalar(select(func.count()).select_from(TtSchulklasse)
                        .where(TtSchulklasse.jahrgang_id == j.id)) or 0
    gruppen = db.scalar(select(func.count()).select_from(TtKlasse)
                        .where(TtKlasse.jahrgang_id == j.id)) or 0
    if klassen or gruppen:
        j.active = False
        db.commit()
        return _redir("/stammdaten/jahrgaenge",
                      err="Jahrgang hat noch Klassen/Lerngruppen und wurde nur stillgelegt")
    name = j.name
    db.delete(j)
    audit(db, "tt_jahrgang_deleted", actor=user, target=name, request=request)
    db.commit()
    return _redir("/stammdaten/jahrgaenge")


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


# ── Klassen (Schüler-Behälter) ───────────────────────────────────────────

@router.post("/stammdaten/jahrgaenge/{jid}/klassen")
def klasse_add(
    request: Request,
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(...),
    kuerzel: str = Form(""),
    klassen_key: str = Form(""),
):
    """Legt die Klasse an — und gleich die passende 1:1-Lerngruppe dazu.

    Ohne Lerngruppe stünde die Klasse im Stundenplan nicht zur Verfügung; das
    hier ist der Normalfall, deshalb passiert es in einem Schritt. Der Schlüssel
    ist ab jetzt unveränderlich, darum ist er beim Anlegen frei setzbar
    (Bestands-Keys aus Untis 1:1 übernehmen!) und danach nicht mehr."""
    j = _jahrgang(db, user, jid)
    n = name.strip()[:120]
    if not n:
        raise HTTPException(400, "Name fehlt.")
    if db.scalar(select(TtSchulklasse.id).where(
            TtSchulklasse.user_id == user.id, TtSchulklasse.name == n)):
        return _redir(f"/stammdaten/jahrgaenge/{jid}",
                      err="Diese Klasse gibt es schon")

    pos = db.scalar(select(func.count()).select_from(TtSchulklasse)
                    .where(TtSchulklasse.jahrgang_id == j.id)) or 0
    k = TtSchulklasse(user_id=user.id, jahrgang_id=j.id, name=n,
                      kuerzel=kuerzel.strip()[:40], position=pos)
    db.add(k)
    db.flush()

    key = (klassen_key.strip() or n)[:255]
    lg = db.scalar(select(TtKlasse).where(TtKlasse.user_id == user.id,
                                          TtKlasse.klassen_key == key))
    if lg is None:
        lgpos = db.scalar(select(func.count()).select_from(TtKlasse)
                          .where(TtKlasse.user_id == user.id)) or 0
        lg = TtKlasse(user_id=user.id, klassen_key=key, display_name=n,
                      kuerzel=kuerzel.strip()[:40], position=lgpos,
                      jahrgang_id=j.id, art="klasse")
        db.add(lg)
        db.flush()
    else:
        # Key existiert schon (typisch: Bestands-Lerngruppe aus dem Backfill) —
        # dann wird die neue Klasse einfach daran gehängt, statt einen zweiten
        # Eintrag mit demselben Schlüssel zu erzeugen.
        lg.jahrgang_id = lg.jahrgang_id or j.id
    db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=k.id))

    audit(db, "tt_klasse_added", actor=user, target=n, request=request)
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{jid}")


@router.post("/stammdaten/schulklassen/{kid}")
def klasse_edit(
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    k.name = (name.strip() or k.name)[:120]
    k.kuerzel = kuerzel.strip()[:40]
    k.active = active == "1"
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{k.jahrgang_id}")


@router.post("/stammdaten/schulklassen/{kid}/delete")
def klasse_delete(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    jid = k.jahrgang_id
    schueler = db.scalar(select(func.count()).select_from(Student)
                         .where(Student.schulklasse_id == k.id)) or 0
    if schueler:
        k.active = False
        db.commit()
        return _redir(f"/stammdaten/jahrgaenge/{jid}",
                      err=f"Klasse hat noch {schueler} Schüler und wurde nur stillgelegt")
    db.execute(TtLerngruppeKlasse.__table__.delete()
               .where(TtLerngruppeKlasse.schulklasse_id == k.id))
    name = k.name
    db.delete(k)
    audit(db, "tt_klasse_deleted", actor=user, target=name, request=request)
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{jid}")


# ── Lernfelder/Fächer eines Jahrgangs ────────────────────────────────────

@router.post("/stammdaten/jahrgaenge/{jid}/faecher")
def jahrgang_fach_add(
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    fach_id: int = Form(...),
    stundenansatz: int = Form(0),
    zeitraum_von: str = Form(""),
    zeitraum_bis: str = Form(""),
):
    j = _jahrgang(db, user, jid)
    f = db.get(TtFach, fach_id)
    if not f or f.user_id != user.id:
        raise HTTPException(404)
    if db.scalar(select(TtJahrgangFach.id).where(
            TtJahrgangFach.jahrgang_id == j.id,
            TtJahrgangFach.fach_id == f.id)):
        return _redir(f"/stammdaten/jahrgaenge/{jid}",
                      err="Dieses Fach ist im Jahrgang schon eingetragen")
    pos = db.scalar(select(func.count()).select_from(TtJahrgangFach)
                    .where(TtJahrgangFach.jahrgang_id == j.id)) or 0
    db.add(TtJahrgangFach(
        jahrgang_id=j.id, fach_id=f.id, stundenansatz=max(0, stundenansatz),
        zeitraum_von=zeitraum_von.strip()[:10],
        zeitraum_bis=zeitraum_bis.strip()[:10], position=pos))
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{jid}")


@router.post("/stammdaten/jahrgaenge/{jid}/faecher/{jfid}")
def jahrgang_fach_edit(
    jid: int,
    jfid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    stundenansatz: int = Form(0),
    zeitraum_von: str = Form(""),
    zeitraum_bis: str = Form(""),
):
    _jahrgang(db, user, jid)
    x = db.get(TtJahrgangFach, jfid)
    if not x or x.jahrgang_id != jid:
        raise HTTPException(404)
    x.stundenansatz = max(0, stundenansatz)
    x.zeitraum_von = zeitraum_von.strip()[:10]
    x.zeitraum_bis = zeitraum_bis.strip()[:10]
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{jid}")


@router.post("/stammdaten/jahrgaenge/{jid}/faecher/{jfid}/delete")
def jahrgang_fach_delete(
    jid: int,
    jfid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Entfernt das Fach NUR aus diesem Jahrgang — der Katalogeintrag und alle
    bisherigen Stunden/Notizen bleiben unberührt."""
    _jahrgang(db, user, jid)
    x = db.get(TtJahrgangFach, jfid)
    if not x or x.jahrgang_id != jid:
        raise HTTPException(404)
    db.delete(x)
    db.commit()
    return _redir(f"/stammdaten/jahrgaenge/{jid}")


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


@router.post("/stammdaten/lerngruppen/bilden")
def lerngruppe_bilden(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    art: str = Form("kombi"),
    klassen_key: str = Form(...),
    display_name: str = Form(""),
    jahrgang_id: int = Form(...),
    schulklasse_ids: Annotated[list[int], Form()] = [],
    student_ids: Annotated[list[int], Form()] = [],
):
    """Bildet eine Lerngruppe: Zusammenlegung mehrerer Klassen ('kombi') oder
    Teilgruppe einer Klasse ('gruppe').

    Der Schlüssel wird hier EINMALIG vergeben und ist danach unveränderlich —
    er entscheidet, an welchen Stundennotizen diese Gruppe hängt."""
    if art not in ("kombi", "gruppe"):
        raise HTTPException(400, "Unbekannte Art.")
    j = _jahrgang(db, user, jahrgang_id)
    key = klassen_key.strip()[:255]
    if not key:
        return _redir("/stammdaten/lerngruppen", err="Schlüssel fehlt")
    if db.scalar(select(TtKlasse.id).where(TtKlasse.user_id == user.id,
                                           TtKlasse.klassen_key == key)):
        return _redir("/stammdaten/lerngruppen",
                      err="Diesen Schlüssel gibt es schon")
    if art == "kombi" and len(schulklasse_ids) < 2:
        return _redir("/stammdaten/lerngruppen",
                      err="Für eine Zusammenlegung mindestens zwei Klassen wählen")
    if art == "gruppe" and not student_ids:
        return _redir("/stammdaten/lerngruppen",
                      err="Für eine Gruppe mindestens einen Schüler wählen")

    pos = db.scalar(select(func.count()).select_from(TtKlasse)
                    .where(TtKlasse.user_id == user.id)) or 0
    lg = TtKlasse(user_id=user.id, klassen_key=key,
                  display_name=(display_name.strip() or key)[:200],
                  position=pos, jahrgang_id=j.id, art=art)
    db.add(lg)
    db.flush()

    if art == "kombi":
        for kid in schulklasse_ids:
            k = db.get(TtSchulklasse, kid)
            if k and k.user_id == user.id:
                db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=k.id))
    else:
        klassen_ids = set()
        for sid in student_ids:
            s = db.get(Student, sid)
            if s and s.owner_user_id == user.id:
                db.add(TtLerngruppeStudent(lerngruppe_id=lg.id, student_id=s.id))
                if s.schulklasse_id:
                    klassen_ids.add(s.schulklasse_id)
        # Die Herkunftsklassen mitschreiben, damit die Gruppe auch dann
        # zuordenbar bleibt, wenn ein Schüler später versetzt wird.
        for kid in klassen_ids:
            db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=kid))

    audit(db, "tt_lerngruppe_added", actor=user, target=key,
          detail=art, request=request)
    db.commit()
    return _redir("/stammdaten/lerngruppen", ok="Lerngruppe angelegt")


@router.post("/stammdaten/lerngruppen/{lgid}")
def lerngruppe_edit(
    lgid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    display_name: str = Form(""),
    kuerzel: str = Form(""),
    active: str = Form(""),
):
    lg = db.get(TtKlasse, lgid)
    if not lg or lg.user_id != user.id:
        raise HTTPException(404)
    # klassen_key bleibt bewusst unangetastet — er ist Teil des key4.
    lg.display_name = (display_name.strip() or lg.klassen_key)[:200]
    lg.kuerzel = kuerzel.strip()[:40]
    lg.active = active == "1"
    db.commit()
    return _redir("/stammdaten/lerngruppen")


@router.post("/stammdaten/lerngruppen/{lgid}/delete")
def lerngruppe_delete(
    request: Request,
    lgid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lg = db.get(TtKlasse, lgid)
    if not lg or lg.user_id != user.id:
        raise HTTPException(404)
    benutzt = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.klasse_id == lg.id))
    notizen = db.scalar(select(func.count()).select_from(LessonNote).where(
        LessonNote.user_id == user.id,
        LessonNote.klassen_key == lg.klassen_key)) or 0
    if benutzt or notizen:
        # Nicht löschen: Stundenplan-Zeilen bzw. Notizen hängen am Schlüssel.
        lg.active = False
        db.commit()
        return _redir("/stammdaten/lerngruppen",
                      err="Lerngruppe wird noch benutzt und wurde nur stillgelegt")
    key = lg.klassen_key
    db.execute(TtLerngruppeKlasse.__table__.delete()
               .where(TtLerngruppeKlasse.lerngruppe_id == lg.id))
    db.execute(TtLerngruppeStudent.__table__.delete()
               .where(TtLerngruppeStudent.lerngruppe_id == lg.id))
    db.delete(lg)
    audit(db, "tt_lerngruppe_deleted", actor=user, target=key, request=request)
    db.commit()
    return _redir("/stammdaten/lerngruppen")


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
