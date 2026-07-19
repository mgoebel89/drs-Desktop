"""Themen-Kaskade bei Ausfall / verschobener Vertretung.

Fällt ein Block einer Reihe (Klasse + Fach) aus, wandert sein Planungspaket
(Thema + Notizen + Material) auf die nächste **gehaltene** Stunde derselben
Reihe; alle folgenden Pakete rücken einen gehaltenen Block weiter. Klassenarbeits-
Blöcke (`is_exam`) sind terminfest: Sie werden übersprungen und bleiben liegen.

Umgesetzt als physisches Umschreiben in `lesson_notes` (das key4 bleibt die
Wahrheit) plus ein Journal je Ausnahme (`plan_shift_journal`), damit das Aufheben
der Ausnahme die Kette exakt zurückschieben kann.

Anwenden der Kette von hinten (großes `seq` zuerst), Zurücknehmen von vorne
(kleines `seq` zuerst) — so ist der Zielblock beim Schreiben stets leer.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LessonNote, PlanShiftJournal, TtException, User
from app.services import timetable_grid

# Wie weit voraus eine Kette einen Folgetermin sucht. Großzügig (gut ein
# Schulhalbjahr), damit auch bei dünnen Reihen ein gehaltener Block gefunden wird.
HORIZON_WEEKS = 30

# Ein Block gilt als „gehalten", solange er nicht ausfällt oder wegverlegt ist.
HELD_STATUS = {"regulaer", "vertretung", "verlegt_hier", "zusatz"}


# ── kleine Helfer ─────────────────────────────────────────────────────────

def _note_at(db: Session, user: User, d: str, kk: str, sk: str,
             bs: str) -> LessonNote | None:
    return db.scalars(
        select(LessonNote).where(
            LessonNote.user_id == user.id, LessonNote.lesson_date == d,
            LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
            LessonNote.block_start == bs)).first()


def _pkg(note: LessonNote | None) -> tuple[str, str, str]:
    """Das wandernde Paket: (theme, notes, material)."""
    if not note:
        return ("", "", "")
    return (note.theme or "", note.notes or "", note.material or "")


def _pkg_nonempty(pkg: tuple[str, str, str]) -> bool:
    return any(bool((v or "").strip()) for v in pkg)


def _note_is_empty(note: LessonNote) -> bool:
    """Wie im Notiz-Auto-Save: ein Datensatz ohne Inhalt wird gelöscht.
    is_exam, forward_remarks, subject_override und die LS-Verknüpfung zählen als
    Inhalt — die wandern NICHT mit und dürfen den Ursprungsblock nicht verlieren."""
    return not (
        (note.theme or "").strip() or (note.notes or "").strip()
        or (note.material or "").strip() or (note.remarks or "").strip()
        or (note.forward_remarks or "").strip()
        or (note.subject_override or "").strip()
        or note.is_exam or note.learning_situation_id
    )


def _ensure_note(db: Session, user: User, d: str, kk: str, sk: str,
                 bs: str) -> LessonNote:
    note = _note_at(db, user, d, kk, sk, bs)
    if not note:
        note = LessonNote(user_id=user.id, lesson_date=d, klassen_key=kk,
                          subjects_key=sk, block_start=bs)
        db.add(note)
        db.flush()
    return note


def _move_pkg(db: Session, user: User, kk: str, sk: str,
              frm: tuple[str, str], to: tuple[str, str]) -> tuple[str, str, str]:
    """Verschiebt das Paket (theme/notes/material) live von `frm` nach `to`.

    Voraussetzung fürs Anwenden/Zurücknehmen: `to` ist beim Aufruf leer. Gibt das
    bewegte Paket zurück. Leert die Quelle und löscht sie, wenn danach nichts
    Bewahrenswertes mehr übrig ist."""
    src = _note_at(db, user, *(_kf(frm, kk, sk)))
    pkg = _pkg(src)
    if not _pkg_nonempty(pkg):
        return ("", "", "")
    dst = _ensure_note(db, user, to[0], kk, sk, to[1])
    dst.theme, dst.notes, dst.material = pkg
    src.theme = src.notes = src.material = ""
    if _note_is_empty(src):
        db.delete(src)
    db.flush()
    return pkg


def _kf(dbs: tuple[str, str], kk: str, sk: str) -> tuple[str, str, str, str]:
    """(date, block_start) + Reihe → Argumentliste für _note_at."""
    return (dbs[0], kk, sk, dbs[1])


# ── gehaltene Blöcke der Reihe ────────────────────────────────────────────

def iter_held_blocks(db: Session, user: User, kk: str, sk: str,
                     after_date: str, after_bs: str,
                     horizon_weeks: int = HORIZON_WEEKS
                     ) -> Iterator[tuple[str, str]]:
    """Chronologische, gehaltene Blöcke der Reihe (Klasse+Fach) **strikt nach**
    (after_date, after_bs). Ferien/freie Tage fallen über das Grid weg. KA-Blöcke
    werden NICHT hier gefiltert (das entscheidet der Aufrufer je nach Zweck)."""
    try:
        start = date.fromisoformat(after_date)
    except ValueError:
        return
    monday = start - timedelta(days=start.weekday())
    after = (after_date, after_bs)
    for w in range(horizon_weeks):
        ref = monday + timedelta(days=7 * w)
        grid = timetable_grid.get_week_grid(db, user, ref)
        for day in grid["days"]:
            if day["free"]:
                continue
            d_idx = (day["date"] - grid["monday"]).days
            d_iso = day["date"].isoformat()
            for slot in grid["slots"]:
                bs = slot["start"]
                if (d_iso, bs) <= after:
                    continue
                for l in grid["cells"].get((bs, d_idx), []):
                    if (l["klassen_key"] == kk and l["subjects_key"] == sk
                            and l["status"] in HELD_STATUS):
                        yield (d_iso, bs)
                        break


def held_blocks(db: Session, user: User, kk: str, sk: str,
                after_date: str, after_bs: str, limit: int = 200,
                horizon_weeks: int = HORIZON_WEEKS) -> list[tuple[str, str]]:
    """Bequeme, gedeckelte Liste von iter_held_blocks."""
    out: list[tuple[str, str]] = []
    for blk in iter_held_blocks(db, user, kk, sk, after_date, after_bs,
                                horizon_weeks):
        out.append(blk)
        if len(out) >= limit:
            break
    return out


# ── Kette berechnen ───────────────────────────────────────────────────────

def _plan_chain(db: Session, user: User, kk: str, sk: str,
                d0: str, bs0: str) -> tuple[list[dict], str]:
    """Berechnet (ohne zu schreiben) die Kette von Einzelschritten `from→to`.

    Startet am Auslöseblock (d0, bs0). Sein Paket rückt auf den nächsten
    gehaltenen Nicht-KA-Block; ein dort vorhandenes Paket rückt weiter, usw., bis
    ein leerer gehaltener Block die Kette aufnimmt. KA-Blöcke werden übersprungen.

    Rückgabe: (moves, warn). moves ist leer, wenn nichts zu verschieben ist.
    warn ≠ "" signalisiert, dass kein Folgetermin gefunden wurde (nichts bewegt)."""
    src = _note_at(db, user, d0, kk, sk, bs0)
    carried = _pkg(src)
    if not _pkg_nonempty(carried):
        return [], ""  # ausgefallener Block ohne Planung → nichts zu tun

    moves: list[dict] = []
    carried_from = (d0, bs0)
    for (cd, cbs) in iter_held_blocks(db, user, kk, sk, d0, bs0):
        note = _note_at(db, user, cd, kk, sk, cbs)
        if note and note.is_exam:
            continue  # Klassenarbeit ist terminfest → überspringen
        target_pkg = _pkg(note)
        moves.append({"from": carried_from, "to": (cd, cbs),
                      "moved": carried})
        if not _pkg_nonempty(target_pkg):
            return moves, ""  # leerer Block nimmt die Kette auf → fertig
        carried_from = (cd, cbs)
        carried = target_pkg

    # Horizont erschöpft, ohne einen freien gehaltenen Block zu finden.
    return [], ("Thema konnte nicht weitergeschoben werden — kein gehaltener "
                "Folgetermin in Sicht.")


# ── öffentliche API: Kaskade anwenden / zurücknehmen ──────────────────────

def cascade_shift(db: Session, user: User, exc: TtException) -> str:
    """Wendet die Kaskade für eine gerade angelegte Ausnahme an und schreibt das
    Journal. Gibt einen (ggf. leeren) Warnhinweis für die UI zurück.

    Nur sinnvoll für Ausfall / verschobene Vertretung — der Aufrufer entscheidet."""
    kk, sk = exc.klassen_key, exc.subjects_key
    moves, warn = _plan_chain(db, user, kk, sk, exc.lesson_date, exc.block_start)
    if not moves:
        return warn

    # Von hinten anwenden — so ist der Zielblock beim Schreiben stets leer.
    for seq in range(len(moves) - 1, -1, -1):
        m = moves[seq]
        _move_pkg(db, user, kk, sk, m["from"], m["to"])

    for seq, m in enumerate(moves):
        db.add(PlanShiftJournal(
            user_id=user.id, exception_id=exc.id, seq=seq,
            klassen_key=kk, subjects_key=sk,
            from_date=m["from"][0], from_block_start=m["from"][1],
            to_date=m["to"][0], to_block_start=m["to"][1],
            moved_theme=m["moved"][0], moved_notes=m["moved"][1],
            moved_material=m["moved"][2],
        ))
    db.flush()
    return ""


def cascade_revert(db: Session, user: User, exc: TtException) -> None:
    """Nimmt die Kaskade einer Ausnahme zurück: schiebt die Pakete entlang des
    Journals wieder an ihren Ursprung. Von vorne (kleines seq zuerst) — so ist der
    Rückgabeplatz beim Schreiben stets leer. Löscht das Journal danach."""
    rows = db.scalars(
        select(PlanShiftJournal).where(
            PlanShiftJournal.user_id == user.id,
            PlanShiftJournal.exception_id == exc.id)
        .order_by(PlanShiftJournal.seq)).all()
    kk, sk = exc.klassen_key, exc.subjects_key
    for r in rows:
        # Bewegt den aktuellen Inhalt am Ziel zurück zur Quelle — so reisen auch
        # zwischenzeitliche Handänderungen am Paket wieder mit.
        _move_pkg(db, user, kk, sk,
                  (r.to_date, r.to_block_start),
                  (r.from_date, r.from_block_start))
    for r in rows:
        db.delete(r)
    db.flush()
