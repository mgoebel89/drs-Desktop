"""Schüler — wohnen seit Migration 0026 in den STAMMDATEN.

Der Schüler hängt an einer Klasse (`schulklasse_id`), die Klasse am Jahrgang.
Deshalb ist die Klasse auch die Heimat der Schülerliste (`/stammdaten/klassen/{id}`),
und `/students` leitet nur noch dorthin um. Leitidee der Navigation:
Stammdaten = wer und was es gibt, Bewertung = was man damit macht.

Zwei Wahrheiten, die man auseinanderhalten muss:
* **Klasse** = wo der Schüler Schüler ist (genau eine).
* **Lerngruppe** = wo er im Unterricht sitzt (auch Zusammenlegungen/Teilgruppen).

`students.klassen_key` bleibt als denormalisierte Spalte bestehen (Altbestand in
Prüfungen/Export) und wird bei jedem Umzug mitgeschrieben — Quelle dafür ist der
Schlüssel der 1:1-Lerngruppe der Klasse, nicht deren Anzeigename. Sonst würde ein
umbenannter Klassenname die Verbindung zu alten Prüfungen kappen.

Der Import läuft über den JAHRGANG: Die Schüler landen zunächst ohne Klasse im
Pool (`schulklasse_id IS NULL`) und werden dann per Wisch-Geste verteilt.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (Student, StudentClassMove, TtJahrgang, TtKlasse,
                        TtLerngruppeKlasse, TtLerngruppeStudent, TtSchulklasse,
                        User)
from app.services import moodle_csv
from app.templating import templates

router = APIRouter()


# ── Helfer ───────────────────────────────────────────────────────────────

def _klasse(db: Session, user: User, kid: int) -> TtSchulklasse:
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404, "Klasse nicht gefunden.")
    return k


def _schueler(db: Session, user: User, sid: int) -> Student:
    s = db.get(Student, sid)
    if not s or s.owner_user_id != user.id:
        raise HTTPException(404, "Schüler nicht gefunden.")
    return s


def _klassen_key_fuer(db: Session, user: User, k: TtSchulklasse) -> str:
    """Der `klassen_key`, unter dem ein Schüler dieser Klasse geführt wird.

    Das ist der Schlüssel ihrer 1:1-Lerngruppe — der ist unveränderlich und
    verbindet den Schüler mit den alten Prüfungen. Der Klassenname taugt dafür
    nicht: Er darf umbenannt werden."""
    lg = db.scalars(
        select(TtKlasse)
        .join(TtLerngruppeKlasse, TtLerngruppeKlasse.lerngruppe_id == TtKlasse.id)
        .where(TtLerngruppeKlasse.schulklasse_id == k.id,
               TtKlasse.user_id == user.id, TtKlasse.art == "klasse")
    ).first()
    return (lg.klassen_key if lg else k.name)[:255]


def _lerngruppen_von(db: Session, user: User, s: Student) -> list[str]:
    """Alle Lerngruppen, in denen dieser Schüler sitzt — über seine Klasse und
    über direkte Teilgruppen-Mitgliedschaften."""
    namen: list[str] = []
    if s.schulklasse_id:
        for g in db.scalars(
            select(TtKlasse)
            .join(TtLerngruppeKlasse, TtLerngruppeKlasse.lerngruppe_id == TtKlasse.id)
            .where(TtLerngruppeKlasse.schulklasse_id == s.schulklasse_id,
                   TtKlasse.user_id == user.id, TtKlasse.art != "gruppe")
            .order_by(TtKlasse.position)
        ).all():
            namen.append(g.display_name or g.klassen_key)
    for g in db.scalars(
        select(TtKlasse)
        .join(TtLerngruppeStudent, TtLerngruppeStudent.lerngruppe_id == TtKlasse.id)
        .where(TtLerngruppeStudent.student_id == s.id)
    ).all():
        namen.append((g.display_name or g.klassen_key) + " (Teilgruppe)")
    return namen


# ── Seiten ───────────────────────────────────────────────────────────────

@router.get("/students")
def students_alt():
    """Alter Pfad — Schüler leben jetzt in den Stammdaten."""
    return RedirectResponse("/stammdaten/schueler", status_code=307)


@router.get("/stammdaten/schueler", response_class=HTMLResponse)
def schueler_suche(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = "",
):
    """Klassenübergreifende Suche — „wo ist Meier eigentlich gelandet?"."""
    # Moodle-Prüfungsimporte (active=False, ohne Klasse) gehören nicht hierher:
    # sie hängen ausschließlich an ihrer Prüfung.
    stmt = select(Student).where(Student.owner_user_id == user.id,
                                 Student.active.is_(True))
    begriff = q.strip()
    if begriff:
        wie = f"%{begriff}%"
        stmt = stmt.where(or_(Student.nachname.ilike(wie),
                              Student.vorname.ilike(wie),
                              Student.email.ilike(wie)))
    schueler = list(db.scalars(
        stmt.order_by(Student.nachname, Student.vorname)).all())

    klassen = {k.id: k for k in db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.user_id == user.id)).all()}
    return templates.TemplateResponse(request, "students/suche.html", {
        "schueler": schueler, "klassen": klassen, "q": begriff,
    })


@router.get("/stammdaten/klassen/{kid}", response_class=HTMLResponse)
def klasse_detail(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, kid)
    schueler = list(db.scalars(
        select(Student).where(Student.owner_user_id == user.id,
                              Student.schulklasse_id == k.id)
        .order_by(Student.nachname, Student.vorname)).all())
    # Ziel-Klassen fürs Versetzen: alle anderen aktiven Klassen
    ziele = list(db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.user_id == user.id,
                                    TtSchulklasse.id != k.id,
                                    TtSchulklasse.active.is_(True))
        .order_by(TtSchulklasse.name)).all())
    return templates.TemplateResponse(request, "students/klasse.html", {
        "k": k, "jahrgang": k.jahrgang, "schueler": schueler, "ziele": ziele,
        "klassen_key": _klassen_key_fuer(db, user, k),
    })


@router.get("/stammdaten/jahrgaenge/{jid}/zuordnen", response_class=HTMLResponse)
def zuordnen_seite(
    request: Request,
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Die Wisch-Zuordnung: ein Schüler pro Karte, je Klasse ein Ziel."""
    j = db.get(TtJahrgang, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404)
    klassen = list(db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.jahrgang_id == j.id,
                                    TtSchulklasse.active.is_(True))
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all())
    pool = list(db.scalars(
        select(Student).where(Student.owner_user_id == user.id,
                              Student.jahrgang_id == j.id,
                              Student.schulklasse_id.is_(None))
        .order_by(Student.nachname, Student.vorname)).all())
    return templates.TemplateResponse(request, "students/zuordnen.html", {
        "j": j, "klassen": klassen, "pool": pool,
    })


# ── JSON-API ─────────────────────────────────────────────────────────────

class SchuelerNeu(BaseModel):
    schulklasse_id: int
    nachname: str
    vorname: str = ""
    email: str = ""


class SchuelerSave(BaseModel):
    nachname: str
    vorname: str = ""
    email: str = ""
    active: bool = True
    # Nur relevant, wenn active=False: warum und wann der Schüler die Klasse
    # verlassen hat. "abschluss" | "abgang" | "".
    austritt_grund: str = ""
    austritt_datum: str = ""   # letzter Schultag, ISO (YYYY-MM-DD)


class Versetzen(BaseModel):
    student_ids: list[int] = Field(default_factory=list)
    nach_klasse_id: int
    grund: str = ""


class ImportEintrag(BaseModel):
    nachname: str
    vorname: str = ""
    email: str = ""
    moodle_id: str = ""


class ImportIn(BaseModel):
    jahrgang_id: int
    eintraege: list[ImportEintrag] = Field(default_factory=list)


class Zuordnen(BaseModel):
    schulklasse_id: int | None = None   # None = zurück in den Pool (Undo)


@router.post("/api/schueler")
def schueler_add(
    request: Request,
    payload: SchuelerNeu,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, payload.schulklasse_id)
    nachname = payload.nachname.strip()[:120]
    if not nachname:
        raise HTTPException(400, "Der Nachname fehlt.")
    s = Student(
        owner_user_id=user.id, schulklasse_id=k.id, jahrgang_id=k.jahrgang_id,
        klassen_key=_klassen_key_fuer(db, user, k),
        nachname=nachname, vorname=payload.vorname.strip()[:120],
        email=payload.email.strip()[:255],
    )
    db.add(s)
    audit(db, "student_added", actor=user, target=k.name,
          detail=f"{nachname}, {payload.vorname}", request=request)
    db.commit()
    return {"id": s.id}


@router.get("/api/schueler/{sid}")
def schueler_get(
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = _schueler(db, user, sid)
    k = db.get(TtSchulklasse, s.schulklasse_id) if s.schulklasse_id else None
    umzuege = list(db.scalars(
        select(StudentClassMove).where(StudentClassMove.student_id == s.id)
        .order_by(StudentClassMove.id.desc())).all())
    return {
        "id": s.id, "nachname": s.nachname, "vorname": s.vorname,
        "email": s.email, "active": s.active, "moodle_id": s.moodle_id,
        "austritt_grund": s.austritt_grund or "",
        "austritt_datum": s.austritt_datum or "",
        "klasse": k.name if k else "",
        "klasse_id": k.id if k else None,
        "lerngruppen": _lerngruppen_von(db, user, s),
        "historie": [
            {"von": m.von_name, "nach": m.nach_name, "datum": m.datum,
             "grund": m.grund}
            for m in umzuege
        ],
    }


@router.post("/api/schueler/{sid}/save")
def schueler_save(
    sid: int,
    payload: SchuelerSave,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    s = _schueler(db, user, sid)
    nachname = payload.nachname.strip()[:120]
    if not nachname:
        raise HTTPException(400, "Der Nachname fehlt.")
    s.nachname = nachname
    s.vorname = payload.vorname.strip()[:120]
    s.email = payload.email.strip()[:255]
    s.active = payload.active
    if payload.active:
        # Wieder aktiv geschaltet → Austrittsdaten verwerfen.
        s.austritt_grund = ""
        s.austritt_datum = ""
    else:
        grund = payload.austritt_grund.strip().lower()
        if grund not in ("abschluss", "abgang"):
            raise HTTPException(
                400, "Beim Austritt fehlt der Grund (Abschluss oder Abgang).")
        s.austritt_grund = grund
        s.austritt_datum = payload.austritt_datum.strip()[:10]
    db.commit()
    return {"ok": True}


@router.post("/api/schueler/{sid}/delete")
def schueler_delete(
    request: Request,
    sid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Löscht den Schüler samt seiner Bewertungen — die hängen per FK an ihm.

    Wer nur die Klasse wechselt, nutzt „Versetzen": Dabei bleibt die `student.id`
    und mit ihr jede bisherige Bewertung erhalten."""
    s = _schueler(db, user, sid)
    name = f"{s.nachname}, {s.vorname}"
    db.execute(TtLerngruppeStudent.__table__.delete()
               .where(TtLerngruppeStudent.student_id == s.id))
    db.delete(s)
    audit(db, "student_deleted", actor=user, target=name, request=request)
    db.commit()
    return {"ok": True}


@router.post("/api/schueler/versetzen")
def schueler_versetzen(
    request: Request,
    payload: Versetzen,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Versetzt Schüler in eine andere Klasse — die `student.id` bleibt.

    Genau darum überleben `exam_students`, `exam_results` und
    `exam_group_results` den Wechsel: Sie zeigen auf die ID, nicht auf die
    Klasse. Alte Prüfungen führen den Schüler weiterhin unter der damaligen
    Klassen-Anzeige — das ist historisch korrekt."""
    ziel = _klasse(db, user, payload.nach_klasse_id)
    key = _klassen_key_fuer(db, user, ziel)
    heute = date.today().isoformat()
    n = 0
    for sid in payload.student_ids:
        s = _schueler(db, user, sid)
        if s.schulklasse_id == ziel.id:
            continue
        alt = db.get(TtSchulklasse, s.schulklasse_id) if s.schulklasse_id else None
        db.add(StudentClassMove(
            student_id=s.id,
            von_klasse_id=alt.id if alt else None, nach_klasse_id=ziel.id,
            von_name=alt.name if alt else "", nach_name=ziel.name,
            datum=heute, grund=payload.grund.strip()[:255],
        ))
        s.schulklasse_id = ziel.id
        s.jahrgang_id = ziel.jahrgang_id
        s.klassen_key = key
        n += 1
    audit(db, "students_moved", actor=user, target=ziel.name,
          detail=f"{n} versetzt", request=request)
    db.commit()
    return {"ok": True, "anzahl": n}


@router.post("/api/schueler/import/vorschau")
async def import_vorschau(
    user: Annotated[User, Depends(require_user)],
    file: UploadFile = File(...),
):
    """Liest die CSV und gibt zurück, was erkannt wurde — schreibt NICHTS.
    Der Assistent zeigt das als Vorschau, bevor irgendetwas angelegt wird."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except Exception:
            raise HTTPException(
                400, "Die Datei ist weder UTF-8 noch CP1252 — bitte als CSV exportieren.")
    parsed, fmt = moodle_csv.parse_csv(text)
    if not parsed:
        raise HTTPException(400, "In der Datei wurde kein einziger Schüler erkannt.")
    return {
        "format": fmt,
        "eintraege": [
            {"nachname": p.nachname, "vorname": p.vorname,
             "email": p.email, "moodle_id": p.moodle_id}
            for p in parsed
        ],
    }


@router.post("/api/schueler/import")
def import_ausfuehren(
    request: Request,
    payload: ImportIn,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Legt die Schüler im POOL des Jahrgangs an (noch ohne Klasse).

    Verteilt werden sie danach per Wisch-Zuordnung. Das ist der Grund, warum der
    Import am Jahrgang hängt und nicht an einer Klasse: Ein Moodle-Kurs bündelt
    in der Regel den ganzen Jahrgang."""
    j = db.get(TtJahrgang, payload.jahrgang_id)
    if not j or j.user_id != user.id:
        raise HTTPException(404, "Jahrgang nicht gefunden.")

    angelegt, uebersprungen = 0, 0
    for e in payload.eintraege:
        nachname = e.nachname.strip()[:120]
        if not nachname:
            continue
        # Duplikat-Schutz über den ganzen Jahrgang, nicht nur über eine Klasse:
        # ein zweiter Import derselben Liste soll niemanden verdoppeln.
        doppelt = db.scalar(select(Student.id).where(
            Student.owner_user_id == user.id,
            Student.jahrgang_id == j.id,
            Student.nachname == nachname,
            Student.vorname == e.vorname.strip()[:120]))
        if doppelt:
            uebersprungen += 1
            continue
        db.add(Student(
            owner_user_id=user.id, jahrgang_id=j.id, schulklasse_id=None,
            klassen_key="", nachname=nachname,
            vorname=e.vorname.strip()[:120], email=e.email.strip()[:255],
            moodle_id=e.moodle_id.strip()[:64],
        ))
        angelegt += 1

    audit(db, "students_imported", actor=user, target=j.name,
          detail=f"{angelegt} in den Pool, {uebersprungen} übersprungen",
          request=request)
    db.commit()
    return {"angelegt": angelegt, "uebersprungen": uebersprungen,
            "url": f"/stammdaten/jahrgaenge/{j.id}/zuordnen"}


@router.post("/api/schueler/{sid}/zuordnen")
def schueler_zuordnen(
    sid: int,
    payload: Zuordnen,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Eine Karte der Wisch-Zuordnung. Wird SOFORT gespeichert — anders als in den
    Assistenten, wo erst am Ende geschrieben wird: Bei 30 Karten wäre ein
    versehentlicher Reload sonst fatal. `schulklasse_id: null` ist das Undo."""
    s = _schueler(db, user, sid)
    if payload.schulklasse_id is None:
        s.schulklasse_id = None
        s.klassen_key = ""
        db.commit()
        return {"ok": True}

    k = _klasse(db, user, payload.schulklasse_id)
    s.schulklasse_id = k.id
    s.jahrgang_id = k.jahrgang_id
    s.klassen_key = _klassen_key_fuer(db, user, k)
    db.commit()
    return {"ok": True}


@router.get("/api/jahrgang/{jid}/klassen")
def jahrgang_klassen(
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Klassen eines Jahrgangs + wie viele Schüler noch im Pool warten."""
    j = db.get(TtJahrgang, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404)
    klassen = db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.jahrgang_id == j.id,
                                    TtSchulklasse.active.is_(True))
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all()
    pool = db.scalar(select(func.count()).select_from(Student).where(
        Student.owner_user_id == user.id, Student.jahrgang_id == j.id,
        Student.schulklasse_id.is_(None))) or 0
    return {
        "klassen": [{"id": k.id, "name": k.name} for k in klassen],
        "pool": pool,
    }
