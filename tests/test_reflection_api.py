"""Reflexion: Upsert am key4, nur erlaubte Stufen, Leeren löscht den Datensatz."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.routers import timetable as tt
from app.models import LessonReflection


@pytest.fixture()
def client(db, plan):
    app = FastAPI()
    app.include_router(tt.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: plan["user"]
    return TestClient(app)


def _key(plan):
    return {"date": plan["days"]["B1"], "klassen": "MT", "subjects": "BBU",
            "block_start": plan["bs"]}


def test_save_and_get_reflection(client, db, plan):
    k = _key(plan)
    r = client.post("/api/lesson-reflection", json={
        **k, "ratings": {"her1": "voll", "kla2": "eher_nicht", "xx": "quatsch"},
        "free_text": "lief gut"})
    assert r.status_code == 200 and r.json()["saved"]

    got = client.get("/api/lesson-reflection", params={
        "date": k["date"], "klassen": "MT", "subjects": "BBU",
        "block_start": plan["bs"]}).json()["reflection"]
    # ungültiger Wert 'xx' wurde verworfen
    assert got["ratings"] == {"her1": "voll", "kla2": "eher_nicht"}
    assert got["free_text"] == "lief gut"


def test_empty_reflection_is_deleted(client, db, plan):
    k = _key(plan)
    client.post("/api/lesson-reflection", json={**k, "ratings": {"her1": "voll"}})
    # nun leeren → Datensatz weg
    r = client.post("/api/lesson-reflection", json={**k, "ratings": {}, "free_text": ""})
    assert r.json().get("deleted") is True
    assert db.query(LessonReflection).count() == 0
