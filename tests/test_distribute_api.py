"""Endpoint-Test für „Thema verteilen": plan-blocks liefert die Reihe,
distribute-theme schreibt feld-erhaltend und überspringt gesperrte Blöcke."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.routers import timetable as tt
from app.models import LessonNote, TtException
from app.services import plan_cascade as pc  # noqa: F401  (nur Import-Sanity)


@pytest.fixture()
def client(db, plan):
    app = FastAPI()
    app.include_router(tt.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: plan["user"]
    return TestClient(app)


def test_plan_blocks_lists_reihe_with_status(client, db, plan):
    d, bs = plan["days"], plan["bs"]
    # B2 fällt aus → muss als locked erscheinen
    db.add(TtException(user_id=plan["user"].id, kind="ausfall",
                       lesson_date=d["B2"], block_start=bs,
                       klassen_key="MT", subjects_key="BBU"))
    db.add(LessonNote(user_id=plan["user"].id, lesson_date=d["B1"],
                      klassen_key="MT", subjects_key="BBU", block_start=bs,
                      theme="Alt"))
    db.commit()

    r = client.get("/api/timetable/plan-blocks",
                   params={"klassen": "MT", "fach": "BBU",
                           "von": d["B1"], "bis": d["B5"]})
    assert r.status_code == 200
    blocks = {b["date"]: b for b in r.json()["blocks"]}
    assert len(blocks) == 5
    assert blocks[d["B1"]]["has_theme"] and blocks[d["B1"]]["existing_theme"] == "Alt"
    assert blocks[d["B2"]]["locked"] and blocks[d["B2"]]["status"] == "ausfall"
    assert not blocks[d["B3"]]["locked"]


def test_distribute_writes_theme_field_preserving(client, db, plan):
    d, bs = plan["days"], plan["bs"]
    # B3 hat bereits Notizen — die müssen erhalten bleiben
    db.add(LessonNote(user_id=plan["user"].id, lesson_date=d["B3"],
                      klassen_key="MT", subjects_key="BBU", block_start=bs,
                      notes="wichtige Notiz"))
    # B2 gesperrt (Ausfall) → muss übersprungen werden
    db.add(TtException(user_id=plan["user"].id, kind="ausfall",
                       lesson_date=d["B2"], block_start=bs,
                       klassen_key="MT", subjects_key="BBU"))
    db.commit()

    r = client.post("/api/timetable/distribute-theme", json={
        "klassen": "MT", "fach": "BBU", "theme": "Pneumatik",
        "blocks": [{"date": d["B1"], "block_start": bs},
                   {"date": d["B2"], "block_start": bs},
                   {"date": d["B3"], "block_start": bs}],
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "written": 2, "skipped": 1}

    def theme(dd):
        n = db.query(LessonNote).filter_by(
            user_id=plan["user"].id, lesson_date=dd, klassen_key="MT",
            subjects_key="BBU", block_start=bs).first()
        return n
    assert theme(d["B1"]).theme == "Pneumatik"
    n3 = theme(d["B3"])
    assert (n3.theme, n3.notes) == ("Pneumatik", "wichtige Notiz")  # erhalten
    assert theme(d["B2"]) is None  # gesperrt → nicht geschrieben
