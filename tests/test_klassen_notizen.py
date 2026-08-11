"""Klassenmodul: Notiz-Endpoints und die Kennzahlen der Übersicht."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.models import Exam, StudentNotiz, User
from app.routers import klassen as kl_router
from app.services import klassen as kl


@pytest.fixture()
def client(db, stamm):
    app = FastAPI()
    app.include_router(kl_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: stamm["user"]
    return TestClient(app)


# ── Notizen anlegen, ändern, löschen ──────────────────────────────────────

def test_notiz_anlegen_und_lesen(client, db, stamm):
    sid = stamm["schueler"][0].id
    r = client.post(f"/api/schueler/{sid}/notizen", json={
        "datum": "2026-09-15", "kategorie": "gespraech",
        "text": "Elterngespräch vereinbart",
    })
    assert r.status_code == 200, r.text
    n = r.json()["notiz"]
    assert n["kategorie"] == "gespraech"
    assert n["kategorie_label"] == "Gespräch"

    d = client.get(f"/api/schueler/{sid}/notizen").json()
    assert [x["text"] for x in d["notizen"]] == ["Elterngespräch vereinbart"]


def test_notiz_ohne_text_wird_abgewiesen(client, stamm):
    sid = stamm["schueler"][0].id
    r = client.post(f"/api/schueler/{sid}/notizen", json={"text": "   "})
    assert r.status_code == 400


def test_unbekannte_kategorie_faellt_auf_den_standard(client, stamm):
    sid = stamm["schueler"][0].id
    r = client.post(f"/api/schueler/{sid}/notizen",
                    json={"text": "x", "kategorie": "erfunden"})
    assert r.json()["notiz"]["kategorie"] == "beobachtung"


def test_teil_update_leert_die_uebrigen_felder_nicht(client, db, stamm):
    """Dieselbe Falle wie im Prüfungsformular: Wer nur die Kategorie schickt,
    darf Datum und Text nicht verlieren."""
    sid = stamm["schueler"][0].id
    n = client.post(f"/api/schueler/{sid}/notizen", json={
        "datum": "2026-09-15", "text": "Kommt regelmäßig zu spät",
    }).json()["notiz"]

    r = client.post(f"/api/schueler-notizen/{n['id']}/save",
                    json={"kategorie": "vereinbarung"})
    assert r.status_code == 200, r.text
    nach = r.json()["notiz"]
    assert nach["kategorie"] == "vereinbarung"
    assert nach["datum"] == "2026-09-15"
    assert nach["text"] == "Kommt regelmäßig zu spät"


def test_notiz_loeschen(client, db, stamm):
    sid = stamm["schueler"][0].id
    n = client.post(f"/api/schueler/{sid}/notizen", json={"text": "weg damit"}).json()["notiz"]
    assert client.post(f"/api/schueler-notizen/{n['id']}/delete").status_code == 200
    assert db.query(StudentNotiz).count() == 0


def test_fremde_notiz_ist_nicht_erreichbar(client, db, stamm):
    """Die Notizen eines anderen Lehrers dürfen weder lesbar noch löschbar sein."""
    fremd = User(username="fremd", password_hash="x")
    db.add(fremd)
    db.flush()
    n = StudentNotiz(student_id=stamm["schueler"][0].id, owner_user_id=fremd.id,
                     datum="2026-09-01", kategorie="beobachtung", text="privat")
    db.add(n)
    db.commit()

    assert client.post(f"/api/schueler-notizen/{n.id}/save",
                       json={"text": "geklaut"}).status_code == 404
    assert client.post(f"/api/schueler-notizen/{n.id}/delete").status_code == 404
    # Auch die Liste des Schülers zeigt sie nicht
    d = client.get(f"/api/schueler/{stamm['schueler'][0].id}/notizen").json()
    assert d["notizen"] == []


def test_notizen_sortieren_juengste_zuerst(client, stamm):
    sid = stamm["schueler"][0].id
    for datum in ("2026-09-01", "2026-11-04", "2026-10-02"):
        client.post(f"/api/schueler/{sid}/notizen", json={"datum": datum, "text": datum})
    d = client.get(f"/api/schueler/{sid}/notizen").json()
    assert [x["datum"] for x in d["notizen"]] == ["2026-11-04", "2026-10-02", "2026-09-01"]


# ── Übersicht ─────────────────────────────────────────────────────────────

def test_uebersicht_zaehlt_schueler_und_notizen(db, stamm, client):
    sid = stamm["schueler"][0].id
    client.post(f"/api/schueler/{sid}/notizen", json={"datum": "2026-09-15", "text": "a"})
    client.post(f"/api/schueler/{sid}/notizen", json={"datum": "2026-10-01", "text": "b"})

    zeilen = kl.uebersicht(db, stamm["user"])
    a = next(z for z in zeilen if z["klasse"].id == stamm["klasse_a"].id)
    assert a["schueler"] == 3
    assert a["notizen"] == 2
    assert a["letzte_notiz"] == "2026-10-01"
    # Die zweite Klasse ist leer, taucht aber auf
    b = next(z for z in zeilen if z["klasse"].id == stamm["klasse_b"].id)
    assert b["schueler"] == 0 and b["notizen"] == 0


def test_uebersicht_zeigt_die_naechste_pruefung_ueber_die_lerngruppe(db, stamm):
    db.add(Exam(owner_user_id=stamm["user"].id, title="Spätere",
                datum="2099-05-05", lerngruppe_id=stamm["lg_a"].id))
    db.add(Exam(owner_user_id=stamm["user"].id, title="Nächste",
                datum="2099-01-05", lerngruppe_id=stamm["lg_a"].id))
    db.add(Exam(owner_user_id=stamm["user"].id, title="Vergangene",
                datum="2000-01-01", lerngruppe_id=stamm["lg_a"].id))
    db.commit()

    zeilen = kl.uebersicht(db, stamm["user"])
    a = next(z for z in zeilen if z["klasse"].id == stamm["klasse_a"].id)
    assert a["naechste_pruefung"].title == "Nächste"


def test_uebersicht_laesst_stillgelegte_jahrgaenge_weg(db, stamm):
    stamm["jahrgang"].active = False
    db.commit()
    assert kl.uebersicht(db, stamm["user"]) == []


def test_bewertungen_zeigen_dieselbe_note_wie_der_bewertungsbogen(db, stamm):
    """Die Schülerseite rechnet nicht selbst, sondern über exam_scoring."""
    from app.models import ExamFeedbackPoint, ExamResult, ExamStudent
    import json as _json

    ex = Exam(owner_user_id=stamm["user"].id, title="LF3", datum="2026-09-01",
              lerngruppe_id=stamm["lg_a"].id, bewertung_mode="punkte")
    db.add(ex)
    db.flush()
    fp = ExamFeedbackPoint(exam_id=ex.id, position=0, name="Aufgabe 1",
                           max_points=20.0, scope="individual", eval_type="punkte")
    db.add(fp)
    db.flush()
    ada = stamm["schueler"][0]
    db.add(ExamStudent(exam_id=ex.id, student_id=ada.id, group_label=""))
    db.add(ExamResult(exam_id=ex.id, student_id=ada.id,
                      erreicht_json=_json.dumps({str(fp.id): 15.0})))
    db.commit()

    rows = kl.bewertungen(db, stamm["user"], ada)
    assert len(rows) == 1
    assert rows[0]["titel"] == "LF3"
    assert rows[0]["bewertet"] is True
    assert rows[0]["prozent"] == 75.0
    assert rows[0]["note"]        # ein Notenlabel aus dem Schlüssel


def test_schueler_ohne_pruefung_hat_leere_bewertungen(db, stamm):
    assert kl.bewertungen(db, stamm["user"], stamm["schueler"][2]) == []
