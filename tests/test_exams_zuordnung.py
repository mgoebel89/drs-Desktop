"""Prüfungs-Zuordnung: Klasse → Lerngruppe auflösen, Teilnehmerliste, kein 500er,
Feedbackpunkte ID-stabil speichern."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.routers import exams as ex_router
from app.models import Exam, ExamFeedbackPoint, ExamResult, ExamStudent
from app.services.lerngruppen import lerngruppe_der_klasse, schueler_der_lerngruppe


@pytest.fixture()
def client(db, stamm):
    app = FastAPI()
    app.include_router(ex_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: stamm["user"]
    return TestClient(app)


def _exam(db, stamm, **kw):
    ex = Exam(owner_user_id=stamm["user"].id, title="Test", datum="2026-09-01", **kw)
    db.add(ex)
    db.commit()
    return ex


# ── Klasse → Lerngruppe ───────────────────────────────────────────────────

def test_klasse_loest_auf_ihre_lerngruppe_auf(db, stamm):
    lg = lerngruppe_der_klasse(db, stamm["user"], stamm["klasse_a"].id)
    assert lg is not None
    assert lg.id == stamm["lg_a"].id
    assert lg.klassen_key == "BSMT26a"


def test_schueler_der_lerngruppe_ueber_die_klasse(db, stamm):
    namen = [s.nachname for s in schueler_der_lerngruppe(db, stamm["user"], stamm["lg_a"])]
    assert namen == ["Ahrens", "Bloch", "Curt"]
    assert schueler_der_lerngruppe(db, stamm["user"], stamm["lg_b"]) == []


# ── Zuordnung setzen ──────────────────────────────────────────────────────

def test_zuordnung_setzt_key_und_waehlt_schueler_vor(client, db, stamm):
    ex = _exam(db, stamm)
    r = client.post(f"/exams/{ex.id}/save", json={
        "tab": "einstellungen", "title": "Klassenarbeit 1",
        "datum": "2026-09-10", "lerngruppe_id": stamm["lg_a"].id})
    assert r.status_code == 200

    db.refresh(ex)
    assert ex.lerngruppe_id == stamm["lg_a"].id
    # echter Schlüssel, nicht der Anzeigename — daran hängt der Stundenplan
    assert ex.klassen_key == "BSMT26a"
    mitglieder = db.query(ExamStudent).filter_by(exam_id=ex.id).count()
    assert mitglieder == 3


def test_klassen_liste_wirft_keinen_500er_mehr(client, db, stamm):
    """Früher: NameError auf _add_class_members → HTTP 500."""
    ex = _exam(db, stamm)
    r = client.post(f"/exams/{ex.id}/save", json={
        "tab": "einstellungen", "title": "Alt", "datum": "2026-09-10",
        "klassen": ["BSMT 26 a", "BSMT 26 b"]})
    assert r.status_code == 200
    db.refresh(ex)
    assert ex.klassen_key == "BSMT 26 a, BSMT 26 b"


def test_teilupdate_leert_keine_anderen_felder(client, db, stamm):
    """Das Zuordnungs-Overlay schickt NUR die Lerngruppe — Titel, Datum und
    Skala dürfen dabei nicht verlorengehen."""
    ex = _exam(db, stamm, lerngruppe_id=stamm["lg_a"].id)
    ex.title = "Wichtiger Titel"
    ex.datum = "2026-09-30"
    ex.grading_scale_key = "builtin:mss_punkte"
    db.commit()

    r = client.post(f"/exams/{ex.id}/save", json={
        "tab": "einstellungen", "lerngruppe_id": stamm["lg_b"].id})
    assert r.status_code == 200

    db.refresh(ex)
    assert ex.lerngruppe_id == stamm["lg_b"].id     # geändert
    assert ex.title == "Wichtiger Titel"            # unberührt
    assert ex.datum == "2026-09-30"
    assert ex.grading_scale_key == "builtin:mss_punkte"


# ── Teilnehmerliste ───────────────────────────────────────────────────────

def test_roster_zeigt_lerngruppe_und_fremde_teilnehmer(db, stamm):
    ex = _exam(db, stamm, lerngruppe_id=stamm["lg_a"].id)
    # ein Teilnehmer aus einer anderen Klasse (z. B. Moodle-Import)
    from app.models import Student
    fremd = Student(owner_user_id=stamm["user"].id, klassen_key="",
                    nachname="Zieger", vorname="Zoe", active=False)
    db.add(fremd)
    db.flush()
    db.add(ExamStudent(exam_id=ex.id, student_id=fremd.id, group_label=""))
    db.commit()

    roster = ex_router._exam_roster(db, stamm["user"], ex)
    namen = [r["student"].nachname for r in roster]
    assert namen == ["Ahrens", "Bloch", "Curt", "Zieger"]
    # der Fremde ist Mitglied, die Lerngruppen-Schüler (noch) nicht
    assert [r["member"] for r in roster] == [False, False, False, True]


def test_roster_bei_altbestand_ohne_lerngruppe(db, stamm):
    """Alte Prüfung ohne lerngruppe_id: Teilnehmer müssen trotzdem sichtbar sein."""
    ex = _exam(db, stamm, klassen_key="BSMT 26 a")
    db.add(ExamStudent(exam_id=ex.id, student_id=stamm["schueler"][0].id,
                       group_label=""))
    db.commit()
    roster = ex_router._exam_roster(db, stamm["user"], ex)
    assert [r["student"].nachname for r in roster] == ["Ahrens"]
    assert roster[0]["member"] is True


# ── Feedbackpunkte ID-stabil ──────────────────────────────────────────────

def test_feedbackpunkte_behalten_bewertungen_beim_umsortieren(client, db, stamm):
    ex = _exam(db, stamm, lerngruppe_id=stamm["lg_a"].id, bewertung_mode="punkte")
    a = ExamFeedbackPoint(exam_id=ex.id, position=0, name="A", max_points=10,
                          scope="individual", eval_type="punkte")
    b = ExamFeedbackPoint(exam_id=ex.id, position=1, name="B", max_points=20,
                          scope="individual", eval_type="punkte")
    db.add_all([a, b])
    db.flush()
    sid = stamm["schueler"][0].id
    db.add(ExamResult(exam_id=ex.id, student_id=sid,
                      erreicht_json=json.dumps({str(a.id): 7, str(b.id): 15})))
    db.commit()
    a_id, b_id = a.id, b.id

    # A und B tauschen die Reihenfolge — mit ihren IDs
    r = client.post(f"/exams/{ex.id}/save", json={
        "tab": "feedbackpunkte", "feedback_points": [
            {"id": b_id, "name": "B", "max_points": 20, "scope": "individual",
             "eval_type": "punkte", "weight_pct": 0},
            {"id": a_id, "name": "A", "max_points": 10, "scope": "individual",
             "eval_type": "punkte", "weight_pct": 0}]})
    assert r.status_code == 200

    res = db.query(ExamResult).filter_by(exam_id=ex.id, student_id=sid).first()
    werte = json.loads(res.erreicht_json)
    # Die Werte hängen weiter an IHREM Punkt, nicht an der Position
    assert werte[str(a_id)] == 7
    assert werte[str(b_id)] == 15
    fps = {f.name: f.position for f in db.query(ExamFeedbackPoint).filter_by(exam_id=ex.id)}
    assert fps == {"B": 0, "A": 1}


# ── Anlege-Assistent ──────────────────────────────────────────────────────

def test_pickers_trennt_klassen_und_lerngruppen(client, db, stamm):
    from app import models as m
    # eine Kombi-Lerngruppe — nur die soll unter "lerngruppen" auftauchen
    kombi = m.TtKlasse(user_id=stamm["user"].id, klassen_key="BSMT26ab",
                       display_name="BSMT 26 a+b", art="kombi",
                       jahrgang_id=stamm["jahrgang"].id)
    db.add(kombi)
    db.commit()

    body = client.get("/api/exams/pickers").json()
    assert body["ok"]
    klassen = {k["name"]: k for k in body["klassen"]}
    assert set(klassen) == {"BSMT 26 a", "BSMT 26 b"}
    assert klassen["BSMT 26 a"]["lerngruppe_id"] == stamm["lg_a"].id
    assert klassen["BSMT 26 a"]["anzahl"] == 3
    # Die 1:1-Lerngruppen stehen NICHT zusätzlich in der Lerngruppen-Liste
    assert [g["name"] for g in body["lerngruppen"]] == ["BSMT 26 a+b"]
    assert body["default_scale"]


def test_anlegen_ueber_klasse_loest_lerngruppe_auf(client, db, stamm):
    r = client.post("/api/exams", json={
        "title": "Pneumatik-Test", "datum": "2026-09-15",
        "ziel_typ": "klasse", "ziel_id": stamm["klasse_a"].id,
        "bewertung_mode": "punkte",
        "feedback_points": [
            {"name": "Aufbau", "max_points": 10, "scope": "individual",
             "eval_type": "punkte", "weight_pct": 0}]})
    assert r.status_code == 200
    ex = db.get(Exam, r.json()["id"])
    assert ex.lerngruppe_id == stamm["lg_a"].id
    assert ex.klassen_key == "BSMT26a"
    assert db.query(ExamStudent).filter_by(exam_id=ex.id).count() == 3
    assert db.query(ExamFeedbackPoint).filter_by(exam_id=ex.id).count() == 1


def test_anlegen_ohne_lerngruppe_erklaert_das_problem(client, db, stamm):
    from app import models as m
    waise = m.TtSchulklasse(user_id=stamm["user"].id,
                            jahrgang_id=stamm["jahrgang"].id, name="Waise")
    db.add(waise)
    db.commit()
    r = client.post("/api/exams", json={
        "title": "X", "ziel_typ": "klasse", "ziel_id": waise.id})
    assert r.status_code == 400
    assert "Stammdaten" in r.json()["detail"]


def test_anlegen_ohne_ziel_wird_abgelehnt(client, db, stamm):
    r = client.post("/api/exams", json={"title": "X"})
    assert r.status_code == 400


def test_geloeschter_feedbackpunkt_raeumt_bewertungen_auf(client, db, stamm):
    ex = _exam(db, stamm, lerngruppe_id=stamm["lg_a"].id, bewertung_mode="punkte")
    a = ExamFeedbackPoint(exam_id=ex.id, position=0, name="A", max_points=10,
                          scope="individual", eval_type="punkte")
    b = ExamFeedbackPoint(exam_id=ex.id, position=1, name="B", max_points=20,
                          scope="individual", eval_type="punkte")
    db.add_all([a, b])
    db.flush()
    sid = stamm["schueler"][0].id
    db.add(ExamResult(exam_id=ex.id, student_id=sid,
                      erreicht_json=json.dumps({str(a.id): 7, str(b.id): 15})))
    db.commit()
    a_id, b_id = a.id, b.id

    client.post(f"/exams/{ex.id}/save", json={
        "tab": "feedbackpunkte", "feedback_points": [
            {"id": a_id, "name": "A", "max_points": 10, "scope": "individual",
             "eval_type": "punkte", "weight_pct": 0}]})

    res = db.query(ExamResult).filter_by(exam_id=ex.id, student_id=sid).first()
    werte = json.loads(res.erreicht_json)
    assert werte == {str(a_id): 7}          # B ist raus
    assert db.query(ExamFeedbackPoint).filter_by(exam_id=ex.id).count() == 1
