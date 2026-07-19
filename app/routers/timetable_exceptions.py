"""Einmalige Stundenplan-Änderungen (Rechtsklick im Grid).

Vier Arten, alle an ein konkretes Datum gebunden:
  ausfall       — Stunde entfällt ersatzlos
  verschiebung  — Unterricht findet an anderem Tag/Block statt
  vertretung    — ein Kollege hält die Stunde (bleibt dokumentierbar)
  zusatz        — fremder Unterricht, den der Lehrer übernimmt (Betreuung)

Alles strukturiert gespeichert (Art, Grund, Datum, Block), damit sich später
auswerten lässt, wie viele Stunden gehalten, ausgefallen, vertreten oder
zusätzlich übernommen wurden.

Der heikle Teil ist die Verschiebung: Eine vorhandene Stundennotiz muss mit der
Stunde mitwandern, sonst steht die Dokumentation plötzlich an einem leeren Platz.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import audit, require_user
from app.db import get_db
from app.models import LessonNote, TtException, TtFach, TtSlot, User
from app.services import plan_cascade, schulkalender, timetable_grid
from app.services.lerngruppen import lerngruppen

router = APIRouter()

KINDS = ("ausfall", "verschiebung", "vertretung", "zusatz")


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "").strip())
    except ValueError:
        return None


@router.get("/api/timetable/blocks")
def api_blocks(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    week: str = "",
):
    """Blöcke + Tage einer Woche — füttert den Ziel-Picker beim Verschieben.
    Freie Tage werden mitgeliefert, damit die Auswahl sie ausgraut."""
    ref = _parse_date(week) or date.today()
    grid = timetable_grid.get_week_grid(db, user, ref)
    return JSONResponse({
        "ok": True,
        "monday": grid["monday"].isoformat(),
        "slots": [{"name": s["name"], "start": s["start"], "end": s["end"]}
                  for s in grid["slots"]],
        "days": [{"date": d["date"].isoformat(), "name": d["weekday_name"],
                  "free": d["free"], "free_label": d["free_label"]}
                 for d in grid["days"]],
    })


@router.get("/api/timetable/stammdaten")
def api_stammdaten(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Lerngruppen + Fächer für den Zusatzstunden-Dialog.

    Die Lerngruppen kommen über den Service, damit auch die Gruppen stillgelegter
    Jahrgänge verschwinden. Das Fach bleibt hier bewusst frei eintippbar: Eine
    Zusatzstunde ist oft eine Vertretung in einer fremden Klasse, die gar nicht in
    den eigenen Stammdaten steht."""
    klassen = lerngruppen(db, user)
    faecher = db.scalars(
        select(TtFach).where(TtFach.user_id == user.id,
                             TtFach.active == True)  # noqa: E712
        .order_by(TtFach.position)).all()
    return JSONResponse({
        "ok": True,
        "klassen": [{"key": k.klassen_key, "name": k.display_name} for k in klassen],
        "faecher": [{"key": f.subjects_key, "name": f.display_name} for f in faecher],
    })


def _note_at(db: Session, user: User, d: str, kk: str, sk: str,
             bs: str) -> LessonNote | None:
    return db.scalars(
        select(LessonNote).where(
            LessonNote.user_id == user.id, LessonNote.lesson_date == d,
            LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
            LessonNote.block_start == bs)).first()


@router.post("/api/timetable/exception")
def exception_create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(...),
):
    kind = (payload.get("kind") or "").strip()
    if kind not in KINDS:
        return _err("Unbekannte Änderungsart.")

    d = _parse_date(payload.get("date", ""))
    if not d:
        return _err("Datum fehlt.")
    block_start = (payload.get("block_start") or "").strip()
    slot = db.scalar(select(TtSlot.id).where(
        TtSlot.user_id == user.id, TtSlot.start_time == block_start))
    if not slot:
        return _err("Dieser Block steht nicht im Zeitraster.")

    kk = (payload.get("klassen") or "").strip()
    sk = (payload.get("subjects") or "").strip()
    grund = (payload.get("grund") or "").strip()[:255]
    # Bei Vertretung entscheidet der Lehrer, ob die geplanten Themen weiterlaufen
    # oder wie bei Ausfall auf die nächste eigene Stunde verschoben werden.
    move_mode = (payload.get("move_mode") or "weiterlaufen").strip()

    frei, frei_label = schulkalender.is_free(db, user, d)
    if frei and kind != "zusatz":
        return _err(f"An diesem Tag ist ohnehin kein Unterricht ({frei_label}).")

    # ── Zusatzstunde ─────────────────────────────────────────────────────
    if kind == "zusatz":
        # Klasse darf Freitext sein — fremde Klassen stehen nicht in den
        # Stammdaten des Lehrers.
        if not kk:
            return _err("Klasse fehlt.")
        fach_text = (payload.get("fach_text") or "").strip()[:200]
        if not sk:
            sk = fach_text  # Freitext-Fach wird selbst zum Schlüssel
        exc = TtException(
            user_id=user.id, kind="zusatz", lesson_date=d.isoformat(),
            block_start=block_start, klassen_key=kk, subjects_key=sk,
            snap_klassen_display=(payload.get("klassen_display") or kk)[:200],
            snap_fach_display=fach_text or sk,
            fach_text=fach_text,
            raum=(payload.get("raum") or "").strip()[:60],
            fuer_kollege=(payload.get("fuer_kollege") or "").strip()[:120],
            grund=grund,
        )
        db.add(exc)
        audit(db, "tt_exception_added", actor=user, target=f"zusatz {d} {block_start}",
              detail=f"{kk} / {fach_text}", request=request)
        db.commit()
        return JSONResponse({"ok": True, "id": exc.id})

    # ── Ausfall / Vertretung / Verschiebung ──────────────────────────────
    if not kk or not sk:
        return _err("Klasse oder Fach fehlt.")

    # Eine bereits verschobene Stunde nicht ein zweites Mal verschieben —
    # sonst entstünden Ketten, deren Notiz-Wanderung nicht mehr eindeutig ist.
    kette = db.scalars(select(TtException).where(
        TtException.user_id == user.id,
        TtException.kind == "verschiebung",
        TtException.target_date == d.isoformat(),
        TtException.target_block_start == block_start,
        TtException.klassen_key == kk,
        TtException.subjects_key == sk)).first()
    if kette:
        return _err("Diese Stunde wurde bereits hierher verlegt. Heb erst die "
                    "bestehende Verlegung auf.")

    # Bestehende Ausnahme für denselben Block ersetzen (eine pro Stunde)
    alt = db.scalars(select(TtException).where(
        TtException.user_id == user.id,
        TtException.kind != "zusatz",
        TtException.lesson_date == d.isoformat(),
        TtException.block_start == block_start,
        TtException.klassen_key == kk,
        TtException.subjects_key == sk)).first()
    if alt:
        if alt.kind in ("ausfall", "vertretung"):
            plan_cascade.cascade_revert(db, user, alt)
        else:
            _undo_note_move(db, user, alt)
        db.delete(alt)
        db.flush()

    exc = TtException(
        user_id=user.id, kind=kind, lesson_date=d.isoformat(),
        block_start=block_start, klassen_key=kk, subjects_key=sk,
        snap_klassen_display=(payload.get("klassen_display") or kk)[:200],
        snap_fach_display=(payload.get("fach_display") or sk)[:200],
        snap_raum=(payload.get("raum") or "").strip()[:60],
        grund=grund,
    )

    warn = ""
    if kind == "vertretung":
        exc.vertretung_name = (payload.get("vertretung_name") or "").strip()[:120]
        if not exc.vertretung_name:
            return _err("Name der Vertretung fehlt.")

    if kind == "verschiebung":
        ziel = _parse_date(payload.get("target_date", ""))
        ziel_block = (payload.get("target_block_start") or "").strip()
        if not ziel or not ziel_block:
            return _err("Ziel (Datum und Block) fehlt.")
        if ziel.isoformat() == d.isoformat() and ziel_block == block_start:
            return _err("Ziel und Ursprung sind derselbe Block.")
        if not db.scalar(select(TtSlot.id).where(
                TtSlot.user_id == user.id, TtSlot.start_time == ziel_block)):
            return _err("Der Zielblock steht nicht im Zeitraster.")
        ziel_frei, ziel_label = schulkalender.is_free(db, user, ziel)
        if ziel_frei:
            return _err(f"Am Zieltag ist kein Unterricht ({ziel_label}).")
        exc.target_date = ziel.isoformat()
        exc.target_block_start = ziel_block

        # Die Notiz wandert mit der Stunde mit — sonst stünde die Dokumentation
        # an einem Platz, an dem gar kein Unterricht mehr stattfindet.
        note = _note_at(db, user, d.isoformat(), kk, sk, block_start)
        if note:
            besetzt = _note_at(db, user, ziel.isoformat(), kk, sk, ziel_block)
            if besetzt:
                # Ziel-key4 ist unique — die Notiz bleibt, wo sie ist.
                warn = ("Am Zielplatz gibt es bereits eine Notiz. Die Notiz der "
                        "verlegten Stunde bleibt deshalb am Ursprungstermin.")
            else:
                note.lesson_date = ziel.isoformat()
                note.block_start = ziel_block

    db.add(exc)
    db.flush()  # exc.id für das Kaskaden-Journal

    # Themen-Kaskade: Ausfall verschiebt immer, Vertretung nur auf Wunsch.
    # (Die Notiz-Wanderung der 'verschiebung' läuft weiter über den Zielpfad oben.)
    if kind == "ausfall" or (kind == "vertretung" and move_mode == "verschieben"):
        cwarn = plan_cascade.cascade_shift(db, user, exc)
        if cwarn:
            warn = (warn + " " + cwarn).strip() if warn else cwarn

    audit(db, "tt_exception_added", actor=user,
          target=f"{kind} {d} {block_start}", detail=f"{kk} / {sk}", request=request)
    db.commit()
    return JSONResponse({"ok": True, "id": exc.id, "warn": warn})


def _undo_note_move(db: Session, user: User, exc: TtException) -> None:
    """Beim Aufheben einer Verschiebung die Notiz zurückholen."""
    if exc.kind != "verschiebung" or not exc.target_date:
        return
    note = _note_at(db, user, exc.target_date, exc.klassen_key,
                    exc.subjects_key, exc.target_block_start)
    if not note:
        return
    # Nur zurückschieben, wenn der Ursprungsplatz frei ist.
    if _note_at(db, user, exc.lesson_date, exc.klassen_key,
                exc.subjects_key, exc.block_start):
        return
    note.lesson_date = exc.lesson_date
    note.block_start = exc.block_start


@router.post("/api/timetable/exception/{eid}/delete")
def exception_delete(
    request: Request,
    eid: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    exc = db.get(TtException, eid)
    if not exc or exc.user_id != user.id:
        return _err("Änderung nicht gefunden.", 404)
    if exc.kind in ("ausfall", "vertretung"):
        plan_cascade.cascade_revert(db, user, exc)
    else:
        _undo_note_move(db, user, exc)
    label = f"{exc.kind} {exc.lesson_date} {exc.block_start}"
    db.delete(exc)
    audit(db, "tt_exception_removed", actor=user, target=label, request=request)
    db.commit()
    return JSONResponse({"ok": True})
