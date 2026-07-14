"""JSON-API der Stammdaten — Futter für die Assistenten und die Detail-Modals.

Getrennt von `stammdaten.py` (dort leben die HTML-Seiten und die klassischen
Formular-Routen). Die Oberfläche ist server-gerendert; nur Anlegen und Bearbeiten
laufen über diese Endpunkte, damit ein Assistent ohne Seitenneuladen durchläuft.

Zwei Regeln stecken hier drin:

* **Ein Assistent schreibt in EINEM Request.** `POST /api/stammdaten/jahrgang`
  legt Jahrgang + Klassen + Lerngruppen + Lernfelder gemeinsam an. Bricht etwas
  ab, wird nichts committet — kein halber Jahrgang.
* **`klassen_key` ist unveränderlich.** Er wird beim Anlegen vergeben und
  danach nie wieder angefasst; an ihm hängen die Stundennotizen (key4).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import (Exam, LessonNote, Student, TtFach, TtJahrgang,
                        TtJahrgangFach, TtKlasse, TtLerngruppeKlasse,
                        TtLerngruppeStudent, TtRow, TtSchulklasse, User)
from app.services.lerngruppen import klassen_der_lerngruppe

router = APIRouter(prefix="/api/stammdaten")


# ── Eingaben ─────────────────────────────────────────────────────────────

class KlasseIn(BaseModel):
    name: str
    kuerzel: str = ""
    klassen_key: str = ""   # leer = Name übernehmen


class FachIn(BaseModel):
    fach_id: int | None = None      # aus dem Katalog
    subjects_key: str = ""          # oder neu anlegen
    display_name: str = ""
    stundenansatz: int = 0
    zeitraum_von: str = ""
    zeitraum_bis: str = ""


class JahrgangIn(BaseModel):
    name: str
    kuerzel: str = ""
    klassen: list[KlasseIn] = Field(default_factory=list)
    faecher: list[FachIn] = Field(default_factory=list)


class JahrgangSave(BaseModel):
    name: str
    kuerzel: str = ""
    active: bool = True


class KlasseSave(BaseModel):
    name: str
    kuerzel: str = ""
    active: bool = True


class LerngruppeSave(BaseModel):
    display_name: str
    kuerzel: str = ""
    active: bool = True


class LerngruppeIn(BaseModel):
    art: str                        # kombi | gruppe
    jahrgang_id: int
    klassen_key: str
    display_name: str = ""
    schulklasse_ids: list[int] = Field(default_factory=list)
    student_ids: list[int] = Field(default_factory=list)


# ── Helfer ───────────────────────────────────────────────────────────────

def _jahrgang(db: Session, user: User, jid: int) -> TtJahrgang:
    j = db.get(TtJahrgang, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404, "Jahrgang nicht gefunden.")
    return j


def _klasse(db: Session, user: User, kid: int) -> TtSchulklasse:
    k = db.get(TtSchulklasse, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404, "Klasse nicht gefunden.")
    return k


def _lerngruppe(db: Session, user: User, lgid: int) -> TtKlasse:
    lg = db.get(TtKlasse, lgid)
    if not lg or lg.user_id != user.id:
        raise HTTPException(404, "Lerngruppe nicht gefunden.")
    return lg


def _fakt(wert: int, singular: str, plural: str) -> dict:
    """Ein Posten für das Auswirkungs-Modal — die Zahlform passt der Server an,
    damit im Dialog nicht „1 Lerngruppen" steht."""
    return {"label": singular if wert == 1 else plural, "wert": wert}


def _key_frei(db: Session, user: User, key: str) -> bool:
    return not db.scalar(select(TtKlasse.id).where(
        TtKlasse.user_id == user.id, TtKlasse.klassen_key == key))


def _lerngruppe_fuer_klasse(db: Session, user: User, k: TtSchulklasse,
                            key: str, pos: int) -> TtKlasse:
    """1:1-Lerngruppe zu einer Klasse. Existiert der Schlüssel schon (Bestand aus
    dem Backfill), wird die vorhandene Gruppe verknüpft statt eine zweite anzulegen."""
    lg = db.scalar(select(TtKlasse).where(TtKlasse.user_id == user.id,
                                          TtKlasse.klassen_key == key))
    if lg is None:
        lg = TtKlasse(user_id=user.id, klassen_key=key, display_name=k.name,
                      kuerzel=k.kuerzel, position=pos, jahrgang_id=k.jahrgang_id,
                      art="klasse")
        db.add(lg)
        db.flush()
    elif lg.jahrgang_id is None:
        lg.jahrgang_id = k.jahrgang_id
    db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=k.id))
    return lg


# ── Katalog (für die Assistenten) ────────────────────────────────────────

@router.get("/katalog")
def katalog(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    faecher = db.scalars(
        select(TtFach).where(TtFach.user_id == user.id, TtFach.active.is_(True))
        .order_by(TtFach.position, TtFach.subjects_key)).all()
    jahrgaenge = db.scalars(
        select(TtJahrgang).where(TtJahrgang.user_id == user.id,
                                 TtJahrgang.active.is_(True))
        .order_by(TtJahrgang.position, TtJahrgang.name)).all()
    klassen = db.scalars(
        select(TtSchulklasse).where(TtSchulklasse.user_id == user.id,
                                    TtSchulklasse.active.is_(True))
        .order_by(TtSchulklasse.position, TtSchulklasse.name)).all()
    return {
        "faecher": [{"id": f.id, "key": f.subjects_key,
                     "name": f.display_name or f.subjects_key} for f in faecher],
        "jahrgaenge": [{"id": j.id, "name": j.name} for j in jahrgaenge],
        "klassen": [{"id": k.id, "name": k.name, "jahrgang_id": k.jahrgang_id}
                    for k in klassen],
    }


@router.get("/key-frei")
def key_frei(
    key: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Live-Prüfung im Assistenten: Ist dieser Stundenplan-Schlüssel noch frei?"""
    return {"frei": _key_frei(db, user, key.strip())}


# ── Jahrgang anlegen (Assistent, ein Request) ────────────────────────────

@router.post("/jahrgang")
def jahrgang_create(
    request: Request,
    payload: JahrgangIn,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(400, "Der Jahrgang braucht einen Namen.")
    if db.scalar(select(TtJahrgang.id).where(TtJahrgang.user_id == user.id,
                                             TtJahrgang.name == name)):
        raise HTTPException(400, f"Den Jahrgang „{name}“ gibt es schon.")

    # Erst alle Schlüssel prüfen, dann schreiben — sonst entstünde bei einem
    # Dublettenfehler mittendrin ein halb angelegter Jahrgang.
    keys: list[str] = []
    for k in payload.klassen:
        key = (k.klassen_key.strip() or k.name.strip())[:255]
        if not k.name.strip():
            raise HTTPException(400, "Eine Klasse ohne Namen geht nicht.")
        if key in keys:
            raise HTTPException(400, f"Der Schlüssel „{key}“ kommt doppelt vor.")
        keys.append(key)

    pos = db.scalar(select(func.count()).select_from(TtJahrgang)
                    .where(TtJahrgang.user_id == user.id)) or 0
    j = TtJahrgang(user_id=user.id, name=name,
                   kuerzel=payload.kuerzel.strip()[:40], position=pos)
    db.add(j)
    db.flush()

    lgpos = db.scalar(select(func.count()).select_from(TtKlasse)
                      .where(TtKlasse.user_id == user.id)) or 0
    for i, (k_in, key) in enumerate(zip(payload.klassen, keys)):
        k = TtSchulklasse(user_id=user.id, jahrgang_id=j.id,
                          name=k_in.name.strip()[:120],
                          kuerzel=k_in.kuerzel.strip()[:40], position=i)
        db.add(k)
        db.flush()
        _lerngruppe_fuer_klasse(db, user, k, key, lgpos + i)

    fpos = db.scalar(select(func.count()).select_from(TtFach)
                     .where(TtFach.user_id == user.id)) or 0
    for i, f_in in enumerate(payload.faecher):
        fach: TtFach | None = None
        if f_in.fach_id:
            fach = db.get(TtFach, f_in.fach_id)
            if not fach or fach.user_id != user.id:
                raise HTTPException(404, "Unbekanntes Fach.")
        else:
            key = (f_in.subjects_key.strip() or f_in.display_name.strip())[:255]
            if not key:
                raise HTTPException(400, "Das neue Lernfeld braucht einen Namen.")
            fach = db.scalar(select(TtFach).where(TtFach.user_id == user.id,
                                                  TtFach.subjects_key == key))
            if fach is None:
                fach = TtFach(user_id=user.id, subjects_key=key,
                              display_name=(f_in.display_name.strip() or key)[:200],
                              position=fpos + i)
                db.add(fach)
                db.flush()
        db.add(TtJahrgangFach(
            jahrgang_id=j.id, fach_id=fach.id,
            stundenansatz=max(0, f_in.stundenansatz),
            zeitraum_von=f_in.zeitraum_von.strip()[:10],
            zeitraum_bis=f_in.zeitraum_bis.strip()[:10], position=i))

    audit(db, "tt_jahrgang_wizard", actor=user, target=name,
          detail=f"{len(payload.klassen)} Klassen, {len(payload.faecher)} Lernfelder",
          request=request)
    db.commit()
    return {"id": j.id, "url": f"/stammdaten/jahrgaenge/{j.id}"}


# ── Nachträglich ergänzen (Modals auf der Jahrgangs-Seite) ───────────────

@router.post("/jahrgang/{jid}/klasse")
def klasse_add(
    request: Request,
    jid: int,
    payload: KlasseIn,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Klasse nachträglich anlegen — samt 1:1-Lerngruppe für den Stundenplan."""
    j = _jahrgang(db, user, jid)
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(400, "Die Klasse braucht einen Namen.")
    if db.scalar(select(TtSchulklasse.id).where(TtSchulklasse.user_id == user.id,
                                                TtSchulklasse.name == name)):
        raise HTTPException(400, f"Die Klasse „{name}“ gibt es schon.")

    pos = db.scalar(select(func.count()).select_from(TtSchulklasse)
                    .where(TtSchulklasse.jahrgang_id == j.id)) or 0
    k = TtSchulklasse(user_id=user.id, jahrgang_id=j.id, name=name,
                      kuerzel=payload.kuerzel.strip()[:40], position=pos)
    db.add(k)
    db.flush()

    lgpos = db.scalar(select(func.count()).select_from(TtKlasse)
                      .where(TtKlasse.user_id == user.id)) or 0
    _lerngruppe_fuer_klasse(db, user, k, (payload.klassen_key.strip() or name)[:255], lgpos)
    audit(db, "tt_klasse_added", actor=user, target=name, request=request)
    db.commit()
    return {"id": k.id}


@router.post("/jahrgang/{jid}/fach")
def jahrgang_fach_add(
    jid: int,
    payload: FachIn,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    j = _jahrgang(db, user, jid)
    if payload.fach_id:
        fach = db.get(TtFach, payload.fach_id)
        if not fach or fach.user_id != user.id:
            raise HTTPException(404, "Unbekanntes Fach.")
    else:
        key = (payload.subjects_key.strip() or payload.display_name.strip())[:255]
        if not key:
            raise HTTPException(400, "Das Lernfeld braucht einen Namen.")
        fach = db.scalar(select(TtFach).where(TtFach.user_id == user.id,
                                              TtFach.subjects_key == key))
        if fach is None:
            fpos = db.scalar(select(func.count()).select_from(TtFach)
                             .where(TtFach.user_id == user.id)) or 0
            fach = TtFach(user_id=user.id, subjects_key=key,
                          display_name=(payload.display_name.strip() or key)[:200],
                          position=fpos)
            db.add(fach)
            db.flush()

    if db.scalar(select(TtJahrgangFach.id).where(
            TtJahrgangFach.jahrgang_id == j.id, TtJahrgangFach.fach_id == fach.id)):
        raise HTTPException(400, "Dieses Lernfeld ist im Jahrgang schon eingetragen.")

    pos = db.scalar(select(func.count()).select_from(TtJahrgangFach)
                    .where(TtJahrgangFach.jahrgang_id == j.id)) or 0
    db.add(TtJahrgangFach(
        jahrgang_id=j.id, fach_id=fach.id,
        stundenansatz=max(0, payload.stundenansatz),
        zeitraum_von=payload.zeitraum_von.strip()[:10],
        zeitraum_bis=payload.zeitraum_bis.strip()[:10], position=pos))
    db.commit()
    return {"ok": True}


class JahrgangFachSave(BaseModel):
    stundenansatz: int = 0
    zeitraum_von: str = ""
    zeitraum_bis: str = ""


@router.post("/jahrgangfach/{jfid}/save")
def jahrgang_fach_save(
    jfid: int,
    payload: JahrgangFachSave,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    x = db.get(TtJahrgangFach, jfid)
    if not x:
        raise HTTPException(404)
    _jahrgang(db, user, x.jahrgang_id)
    x.stundenansatz = max(0, payload.stundenansatz)
    x.zeitraum_von = payload.zeitraum_von.strip()[:10]
    x.zeitraum_bis = payload.zeitraum_bis.strip()[:10]
    db.commit()
    return {"ok": True}


@router.post("/jahrgangfach/{jfid}/delete")
def jahrgang_fach_delete(
    jfid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Nimmt das Lernfeld aus dem Jahrgang. Der Katalogeintrag und alle bisherigen
    Stunden und Notizen bleiben unberührt."""
    x = db.get(TtJahrgangFach, jfid)
    if not x:
        raise HTTPException(404)
    _jahrgang(db, user, x.jahrgang_id)
    db.delete(x)
    db.commit()
    return {"ok": True}


# ── Lerngruppe bilden (Assistent) ────────────────────────────────────────

@router.post("/lerngruppe")
def lerngruppe_create(
    request: Request,
    payload: LerngruppeIn,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if payload.art not in ("kombi", "gruppe"):
        raise HTTPException(400, "Unbekannte Art.")
    j = _jahrgang(db, user, payload.jahrgang_id)
    key = payload.klassen_key.strip()[:255]
    if not key:
        raise HTTPException(400, "Der Stundenplan-Schlüssel fehlt.")
    if not _key_frei(db, user, key):
        raise HTTPException(400, f"Den Schlüssel „{key}“ gibt es schon.")
    if payload.art == "kombi" and len(payload.schulklasse_ids) < 2:
        raise HTTPException(400, "Zum Zusammenlegen mindestens zwei Klassen wählen.")
    if payload.art == "gruppe" and not payload.student_ids:
        raise HTTPException(400, "Für eine Teilgruppe mindestens einen Schüler wählen.")

    pos = db.scalar(select(func.count()).select_from(TtKlasse)
                    .where(TtKlasse.user_id == user.id)) or 0
    lg = TtKlasse(user_id=user.id, klassen_key=key,
                  display_name=(payload.display_name.strip() or key)[:200],
                  position=pos, jahrgang_id=j.id, art=payload.art)
    db.add(lg)
    db.flush()

    if payload.art == "kombi":
        for kid in payload.schulklasse_ids:
            k = _klasse(db, user, kid)
            db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=k.id))
    else:
        herkunft: set[int] = set()
        for sid in payload.student_ids:
            s = db.get(Student, sid)
            if not s or s.owner_user_id != user.id:
                raise HTTPException(404, "Unbekannter Schüler.")
            db.add(TtLerngruppeStudent(lerngruppe_id=lg.id, student_id=s.id))
            if s.schulklasse_id:
                herkunft.add(s.schulklasse_id)
        # Herkunftsklassen mitschreiben: so bleibt die Gruppe zuordenbar, auch
        # wenn ein Schüler später versetzt wird.
        for kid in herkunft:
            db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=kid))

    audit(db, "tt_lerngruppe_wizard", actor=user, target=key,
          detail=payload.art, request=request)
    db.commit()
    return {"id": lg.id}


# ── Detail-Modals: lesen, speichern, Auswirkungen, löschen ───────────────

@router.get("/jahrgang/{jid}")
def jahrgang_get(
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    j = _jahrgang(db, user, jid)
    return {"id": j.id, "name": j.name, "kuerzel": j.kuerzel, "active": j.active,
            "impact": _impact_jahrgang(db, j)}


def _impact_jahrgang(db: Session, j: TtJahrgang) -> list[dict]:
    klassen = db.scalar(select(func.count()).select_from(TtSchulklasse)
                        .where(TtSchulklasse.jahrgang_id == j.id)) or 0
    gruppen = db.scalar(select(func.count()).select_from(TtKlasse)
                        .where(TtKlasse.jahrgang_id == j.id)) or 0
    schueler = db.scalar(select(func.count()).select_from(Student)
                         .where(Student.jahrgang_id == j.id)) or 0
    return [_fakt(klassen, "Klasse", "Klassen"),
            _fakt(gruppen, "Lerngruppe", "Lerngruppen"),
            _fakt(schueler, "Schüler", "Schüler")]


@router.post("/jahrgang/{jid}/save")
def jahrgang_save(
    jid: int,
    payload: JahrgangSave,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    j = _jahrgang(db, user, jid)
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(400, "Der Name darf nicht leer sein.")
    doppelt = db.scalar(select(TtJahrgang.id).where(
        TtJahrgang.user_id == user.id, TtJahrgang.name == name,
        TtJahrgang.id != j.id))
    if doppelt:
        raise HTTPException(400, f"Den Jahrgang „{name}“ gibt es schon.")
    j.name = name
    j.kuerzel = payload.kuerzel.strip()[:40]
    j.active = payload.active
    db.commit()
    return {"ok": True}


@router.post("/jahrgang/{jid}/delete")
def jahrgang_delete(
    request: Request,
    jid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Hartes Löschen nur, wenn wirklich nichts mehr dranhängt.

    Sonst würde der Jahrgang Klassen und Lerngruppen mitreißen — und mit den
    Lerngruppen die Schlüssel, an denen die Stundennotizen hängen. Stilllegen
    (`/save` mit active=false) ist der vorgesehene Weg."""
    j = _jahrgang(db, user, jid)
    fakten = _impact_jahrgang(db, j)
    if any(f["wert"] for f in fakten):
        raise HTTPException(
            400, "Am Jahrgang hängen noch Klassen, Lerngruppen oder Schüler. "
                 "Leg ihn still statt ihn zu löschen.")
    name = j.name
    db.delete(j)
    audit(db, "tt_jahrgang_deleted", actor=user, target=name, request=request)
    db.commit()
    return {"ok": True}


@router.get("/klasse/{kid}")
def klasse_get(
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, kid)
    schueler = db.scalar(select(func.count()).select_from(Student)
                         .where(Student.schulklasse_id == k.id)) or 0
    gruppen = db.scalar(select(func.count()).select_from(TtLerngruppeKlasse)
                        .where(TtLerngruppeKlasse.schulklasse_id == k.id)) or 0
    return {"id": k.id, "name": k.name, "kuerzel": k.kuerzel, "active": k.active,
            "jahrgang_id": k.jahrgang_id,
            "impact": [_fakt(schueler, "Schüler", "Schüler"),
                       _fakt(gruppen, "Lerngruppe", "Lerngruppen")]}


@router.post("/klasse/{kid}/save")
def klasse_save(
    kid: int,
    payload: KlasseSave,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, kid)
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(400, "Der Name darf nicht leer sein.")
    doppelt = db.scalar(select(TtSchulklasse.id).where(
        TtSchulklasse.user_id == user.id, TtSchulklasse.name == name,
        TtSchulklasse.id != k.id))
    if doppelt:
        raise HTTPException(400, f"Die Klasse „{name}“ gibt es schon.")
    k.name = name
    k.kuerzel = payload.kuerzel.strip()[:40]
    k.active = payload.active
    db.commit()
    return {"ok": True}


@router.post("/klasse/{kid}/delete")
def klasse_delete(
    request: Request,
    kid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    k = _klasse(db, user, kid)
    schueler = db.scalar(select(func.count()).select_from(Student)
                         .where(Student.schulklasse_id == k.id)) or 0
    if schueler:
        raise HTTPException(
            400, f"In der Klasse sind noch {schueler} Schüler. "
                 "Versetze sie oder leg die Klasse still.")
    db.execute(TtLerngruppeKlasse.__table__.delete()
               .where(TtLerngruppeKlasse.schulklasse_id == k.id))
    name = k.name
    db.delete(k)
    audit(db, "tt_klasse_deleted", actor=user, target=name, request=request)
    db.commit()
    return {"ok": True}


@router.get("/lerngruppe/{lgid}")
def lerngruppe_get(
    lgid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lg = _lerngruppe(db, user, lgid)
    notizen = db.scalar(select(func.count()).select_from(LessonNote).where(
        LessonNote.user_id == user.id,
        LessonNote.klassen_key == lg.klassen_key)) or 0
    stunden = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.klasse_id == lg.id)) or 0
    pruefungen = db.scalar(select(func.count()).select_from(Exam).where(
        Exam.owner_user_id == user.id, Exam.lerngruppe_id == lg.id)) or 0
    return {
        "id": lg.id, "klassen_key": lg.klassen_key,
        "display_name": lg.display_name, "kuerzel": lg.kuerzel,
        "active": lg.active, "art": lg.art, "jahrgang_id": lg.jahrgang_id,
        "klassen": [k.name for k in klassen_der_lerngruppe(db, lg)],
        "impact": [_fakt(notizen, "Stundennotiz", "Stundennotizen"),
                   _fakt(stunden, "Stunde im Grundplan", "Stunden im Grundplan"),
                   _fakt(pruefungen, "Prüfung", "Prüfungen")],
    }


@router.post("/lerngruppe/{lgid}/save")
def lerngruppe_save(
    lgid: int,
    payload: LerngruppeSave,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lg = _lerngruppe(db, user, lgid)
    # klassen_key bleibt unangetastet — er ist Teil des key4.
    lg.display_name = (payload.display_name.strip() or lg.klassen_key)[:200]
    lg.kuerzel = payload.kuerzel.strip()[:40]
    lg.active = payload.active
    db.commit()
    return {"ok": True}


@router.post("/lerngruppe/{lgid}/delete")
def lerngruppe_delete(
    request: Request,
    lgid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lg = _lerngruppe(db, user, lgid)
    notizen = db.scalar(select(func.count()).select_from(LessonNote).where(
        LessonNote.user_id == user.id,
        LessonNote.klassen_key == lg.klassen_key)) or 0
    stunden = db.scalar(select(func.count()).select_from(TtRow)
                        .where(TtRow.klasse_id == lg.id)) or 0
    if notizen or stunden:
        raise HTTPException(
            400, "An dieser Lerngruppe hängen Stundennotizen oder Stunden im "
                 "Grundplan. Leg sie still statt sie zu löschen — sonst verlierst "
                 "du den Schlüssel, an dem die Notizen hängen.")
    key = lg.klassen_key
    db.execute(TtLerngruppeKlasse.__table__.delete()
               .where(TtLerngruppeKlasse.lerngruppe_id == lg.id))
    db.execute(TtLerngruppeStudent.__table__.delete()
               .where(TtLerngruppeStudent.lerngruppe_id == lg.id))
    db.delete(lg)
    audit(db, "tt_lerngruppe_deleted", actor=user, target=key, request=request)
    db.commit()
    return {"ok": True}
