"""Kaskade bei Ausfall: Kette rückt weiter, KA bleibt fix, Aufheben stellt her."""
from __future__ import annotations

from sqlalchemy import select

from app import models as m
from app.models import LessonNote
from app.services import plan_cascade as pc


def set_note(db, user, d, kk, sk, bs, *, theme="", notes="", material="",
             is_exam=False):
    n = LessonNote(user_id=user.id, lesson_date=d, klassen_key=kk,
                   subjects_key=sk, block_start=bs, theme=theme, notes=notes,
                   material=material, is_exam=is_exam)
    db.add(n)
    db.flush()
    return n


def note_at(db, user, d, kk, sk, bs):
    return db.scalars(select(LessonNote).where(
        LessonNote.user_id == user.id, LessonNote.lesson_date == d,
        LessonNote.klassen_key == kk, LessonNote.subjects_key == sk,
        LessonNote.block_start == bs)).first()


def make_ausfall(db, user, d, kk, sk, bs):
    exc = m.TtException(user_id=user.id, kind="ausfall", lesson_date=d,
                        block_start=bs, klassen_key=kk, subjects_key=sk)
    db.add(exc)
    db.flush()
    return exc


def _theme(db, user, d, kk, sk, bs):
    n = note_at(db, user, d, kk, sk, bs)
    return n.theme if n else ""


def test_held_blocks_lists_reihe_days(db, plan):
    u, kk, sk, bs = plan["user"], plan["kk"], plan["sk"], plan["bs"]
    d = plan["days"]
    got = pc.held_blocks(db, u, kk, sk, d["B1"], bs, limit=10, horizon_weeks=1)
    # Nach B1 (Mo) folgen Di–Fr derselben Woche.
    assert got == [(d["B2"], bs), (d["B3"], bs), (d["B4"], bs), (d["B5"], bs)]


def test_ausfall_shifts_chain_into_first_empty(db, plan):
    u, kk, sk, bs = plan["user"], plan["kk"], plan["sk"], plan["bs"]
    d = plan["days"]
    # B1=T1, B2=T2/N2, B3=T3, B4 leer, B5=T5
    set_note(db, u, d["B1"], kk, sk, bs, theme="T1")
    set_note(db, u, d["B2"], kk, sk, bs, theme="T2", notes="N2")
    set_note(db, u, d["B3"], kk, sk, bs, theme="T3")
    set_note(db, u, d["B5"], kk, sk, bs, theme="T5")

    exc = make_ausfall(db, u, d["B2"], kk, sk, bs)
    warn = pc.cascade_shift(db, u, exc)
    assert warn == ""

    # B2 leer; T2/N2 -> B3; T3 -> B4 (leerer Senkenblock); B1/B5 unberührt
    assert _theme(db, u, d["B1"], kk, sk, bs) == "T1"
    assert note_at(db, u, d["B2"], kk, sk, bs) is None
    n3 = note_at(db, u, d["B3"], kk, sk, bs)
    assert (n3.theme, n3.notes) == ("T2", "N2")
    assert _theme(db, u, d["B4"], kk, sk, bs) == "T3"
    assert _theme(db, u, d["B5"], kk, sk, bs) == "T5"


def test_ausfall_revert_restores_exactly(db, plan):
    u, kk, sk, bs = plan["user"], plan["kk"], plan["sk"], plan["bs"]
    d = plan["days"]
    set_note(db, u, d["B1"], kk, sk, bs, theme="T1")
    set_note(db, u, d["B2"], kk, sk, bs, theme="T2", notes="N2")
    set_note(db, u, d["B3"], kk, sk, bs, theme="T3")
    set_note(db, u, d["B5"], kk, sk, bs, theme="T5")

    exc = make_ausfall(db, u, d["B2"], kk, sk, bs)
    pc.cascade_shift(db, u, exc)
    pc.cascade_revert(db, u, exc)

    assert _theme(db, u, d["B1"], kk, sk, bs) == "T1"
    n2 = note_at(db, u, d["B2"], kk, sk, bs)
    assert (n2.theme, n2.notes) == ("T2", "N2")
    assert _theme(db, u, d["B3"], kk, sk, bs) == "T3"
    assert note_at(db, u, d["B4"], kk, sk, bs) is None
    assert _theme(db, u, d["B5"], kk, sk, bs) == "T5"


def test_klassenarbeit_block_is_barrier(db, plan):
    u, kk, sk, bs = plan["user"], plan["kk"], plan["sk"], plan["bs"]
    d = plan["days"]
    # B1=T1, B2=T2, B3=KA(is_exam), B4 leer, B5=T5
    set_note(db, u, d["B1"], kk, sk, bs, theme="T1")
    set_note(db, u, d["B2"], kk, sk, bs, theme="T2")
    set_note(db, u, d["B3"], kk, sk, bs, theme="KA", is_exam=True)
    set_note(db, u, d["B5"], kk, sk, bs, theme="T5")

    exc = make_ausfall(db, u, d["B1"], kk, sk, bs)
    pc.cascade_shift(db, u, exc)

    # T1 -> B2; altes T2 überspringt die KA (B3) und landet in B4
    assert note_at(db, u, d["B1"], kk, sk, bs) is None
    assert _theme(db, u, d["B2"], kk, sk, bs) == "T1"
    n3 = note_at(db, u, d["B3"], kk, sk, bs)
    assert (n3.theme, n3.is_exam) == ("KA", True)   # KA unberührt
    assert _theme(db, u, d["B4"], kk, sk, bs) == "T2"
    assert _theme(db, u, d["B5"], kk, sk, bs) == "T5"


def test_ausfall_of_empty_block_does_nothing(db, plan):
    u, kk, sk, bs = plan["user"], plan["kk"], plan["sk"], plan["bs"]
    d = plan["days"]
    set_note(db, u, d["B3"], kk, sk, bs, theme="T3")
    exc = make_ausfall(db, u, d["B1"], kk, sk, bs)  # B1 hat keine Planung
    warn = pc.cascade_shift(db, u, exc)
    assert warn == ""
    assert _theme(db, u, d["B3"], kk, sk, bs) == "T3"  # unverändert
