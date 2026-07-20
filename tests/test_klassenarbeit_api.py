"""Klassenarbeit: Block wird Prüfung + Thema (feld-erhaltend); Themen-seit-KA
grenzt an der letzten Prüfung ab. Vikunja ist im Test nicht konfiguriert."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.routers import timetable as tt
from app.models import LessonNote


@pytest.fixture()
def client(db, plan):
    app = FastAPI()
    app.include_router(tt.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: plan["user"]
    return TestClient(app)


def _set(db, user, d, bs, theme="", is_exam=False):
    db.add(LessonNote(user_id=user.id, lesson_date=d, klassen_key="MT",
                      subjects_key="BBU", block_start=bs, theme=theme,
                      is_exam=is_exam))
    db.commit()


def test_themes_since_last_exam_boundary(client, db, plan):
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    _set(db, u, d["B1"], bs, theme="Alt-vor-KA")
    _set(db, u, d["B2"], bs, theme="KA1", is_exam=True)   # Grenze
    _set(db, u, d["B3"], bs, theme="Neu-1")
    _set(db, u, d["B4"], bs, theme="Neu-2")

    r = client.get("/api/timetable/themes-since-last-exam",
                   params={"klassen": "MT", "datum": d["B5"]})
    assert r.status_code == 200
    body = r.json()
    assert body["since"] == d["B2"]
    themes = [t["theme"] for t in body["themes"]]
    assert themes == ["Neu-1", "Neu-2"]  # Alt-vor-KA und KA1 fallen raus


def test_klassenarbeit_legt_pruefung_an_und_verknuepft_block(client, db, plan):
    """Etappe 4: Die Klassenarbeit erzeugt gleich die passende Prüfung."""
    from app.models import Exam, ExamStudent, LessonNote, Student
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    # Die Lerngruppe 'MT' aus der plan-Fixture bekommt einen Schüler über eine
    # Schulklasse, damit Teilnehmer vorausgewählt werden können.
    from app import models as m
    jg = m.TtJahrgang(user_id=u.id, name="J")
    db.add(jg); db.flush()
    kl = m.TtSchulklasse(user_id=u.id, jahrgang_id=jg.id, name="MT-Klasse")
    db.add(kl); db.flush()
    lg = db.query(m.TtKlasse).filter_by(user_id=u.id, klassen_key="MT").first()
    db.add(m.TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=kl.id))
    db.add(Student(owner_user_id=u.id, klassen_key="MT", schulklasse_id=kl.id,
                   nachname="Test", vorname="Tim", active=True))
    db.commit()

    r = client.post("/api/timetable/klassenarbeit", json={
        "klassen": "MT", "subjects_key": "BBU", "datum": d["B3"],
        "block_start": bs, "theme": "Pneumatik-Test"})
    assert r.status_code == 200
    ex_id = r.json()["exam_id"]
    assert ex_id is not None

    ex = db.get(Exam, ex_id)
    note = db.query(LessonNote).filter_by(
        user_id=u.id, lesson_date=d["B3"], klassen_key="MT",
        subjects_key="BBU", block_start=bs).first()
    assert ex.title == "Pneumatik-Test"
    assert ex.datum == d["B3"]
    assert ex.lerngruppe_id == lg.id
    assert ex.klassen_key == "MT"
    assert ex.lesson_note_id == note.id          # Verknüpfung zum Block
    assert db.query(ExamStudent).filter_by(exam_id=ex.id).count() == 1


def test_klassenarbeit_ohne_lerngruppe_legt_keine_pruefung_an(client, db, plan):
    """Ohne passende Lerngruppe bleibt die Klassenarbeit trotzdem bestehen."""
    from app.models import LessonNote
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    r = client.post("/api/timetable/klassenarbeit", json={
        "klassen": "GIBTESNICHT", "subjects_key": "BBU", "datum": d["B4"],
        "block_start": bs, "theme": "X"})
    assert r.status_code == 200
    assert r.json()["exam_id"] is None
    n = db.query(LessonNote).filter_by(
        user_id=u.id, lesson_date=d["B4"], klassen_key="GIBTESNICHT").first()
    assert n is not None and n.is_exam is True


def test_klassenarbeit_marks_exam_and_preserves(client, db, plan):
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    # Block hat schon Notizen — die müssen bleiben
    db.add(LessonNote(user_id=u.id, lesson_date=d["B3"], klassen_key="MT",
                      subjects_key="BBU", block_start=bs, notes="vorbereitet"))
    db.commit()

    r = client.post("/api/timetable/klassenarbeit", json={
        "klassen": "MT", "subjects_key": "BBU", "datum": d["B3"],
        "block_start": bs, "theme": "Pneumatik-Test"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["task_created"] is False
    assert "Vikunja" in body["warn"]  # nicht eingerichtet

    n = db.query(LessonNote).filter_by(
        user_id=u.id, lesson_date=d["B3"], klassen_key="MT",
        subjects_key="BBU", block_start=bs).first()
    assert n.is_exam is True
    assert n.theme == "Pneumatik-Test"
    assert n.notes == "vorbereitet"  # erhalten
