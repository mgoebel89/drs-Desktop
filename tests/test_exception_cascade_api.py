"""Kaskade über den echten Exception-Endpoint: Ausfall verschiebt die Themen,
Aufheben stellt sie her; Vertretung nur bei move_mode='verschieben'."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.routers import timetable_exceptions as tex
from app.models import LessonNote


@pytest.fixture()
def client(db, plan):
    app = FastAPI()
    app.include_router(tex.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: plan["user"]
    return TestClient(app)


def _set(db, user, d, bs, theme):
    db.add(LessonNote(user_id=user.id, lesson_date=d, klassen_key="MT",
                      subjects_key="BBU", block_start=bs, theme=theme))
    db.commit()


def _theme(db, user, d, bs):
    n = db.query(LessonNote).filter_by(
        user_id=user.id, lesson_date=d, klassen_key="MT", subjects_key="BBU",
        block_start=bs).first()
    return n.theme if n else None


def test_ausfall_endpoint_shifts_and_delete_reverts(client, db, plan):
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    _set(db, u, d["B1"], bs, "T1")
    _set(db, u, d["B2"], bs, "T2")
    _set(db, u, d["B3"], bs, "T3")  # B4 leer = Senke

    r = client.post("/api/timetable/exception", json={
        "kind": "ausfall", "date": d["B2"], "block_start": bs,
        "klassen": "MT", "subjects": "BBU"})
    assert r.status_code == 200 and r.json()["ok"]
    eid = r.json()["id"]

    # T2 -> B3, T3 -> B4
    assert _theme(db, u, d["B2"], bs) is None
    assert _theme(db, u, d["B3"], bs) == "T2"
    assert _theme(db, u, d["B4"], bs) == "T3"

    r2 = client.post(f"/api/timetable/exception/{eid}/delete")
    assert r2.status_code == 200 and r2.json()["ok"]
    assert _theme(db, u, d["B2"], bs) == "T2"
    assert _theme(db, u, d["B3"], bs) == "T3"
    assert _theme(db, u, d["B4"], bs) is None


def test_vertretung_weiterlaufen_does_not_shift(client, db, plan):
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    _set(db, u, d["B2"], bs, "T2")
    _set(db, u, d["B3"], bs, "T3")
    r = client.post("/api/timetable/exception", json={
        "kind": "vertretung", "date": d["B2"], "block_start": bs,
        "klassen": "MT", "subjects": "BBU", "vertretung_name": "Müller",
        "move_mode": "weiterlaufen"})
    assert r.status_code == 200 and r.json()["ok"]
    assert _theme(db, u, d["B2"], bs) == "T2"   # bleibt
    assert _theme(db, u, d["B3"], bs) == "T3"


def test_vertretung_verschieben_shifts(client, db, plan):
    u, d, bs = plan["user"], plan["days"], plan["bs"]
    _set(db, u, d["B2"], bs, "T2")   # B3 leer = Senke
    r = client.post("/api/timetable/exception", json={
        "kind": "vertretung", "date": d["B2"], "block_start": bs,
        "klassen": "MT", "subjects": "BBU", "vertretung_name": "Müller",
        "move_mode": "verschieben"})
    assert r.status_code == 200 and r.json()["ok"]
    assert _theme(db, u, d["B2"], bs) is None
    assert _theme(db, u, d["B3"], bs) == "T2"
