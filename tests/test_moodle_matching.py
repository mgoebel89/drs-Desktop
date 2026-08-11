"""Moodle-Ergebnisse in eine bestehende Prüfung: Namens-Matching und Buchung."""
from __future__ import annotations

import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import require_user
from app.db import get_db
from app.models import Exam, ExamFeedbackPoint, ExamResult, ExamStudent
from app.routers import exams as ex_router
from app.services import moodle_quiz


@pytest.fixture()
def client(db, stamm):
    app = FastAPI()
    app.include_router(ex_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: stamm["user"]
    return TestClient(app)


@pytest.fixture()
def exam(db, stamm):
    ex = Exam(owner_user_id=stamm["user"].id, title="LF3 Test",
              datum="2026-09-01", lerngruppe_id=stamm["lg_a"].id,
              klassen_key="BSMT26a", bewertung_mode="punkte")
    db.add(ex)
    db.commit()
    return ex


def _datei(eintraege: list[dict]) -> dict:
    """Moodle-JSON so, wie der Export sie liefert (Liste in Liste)."""
    roh = [[{"nachname": e[0], "vorname": e[1], "abteilung": "MT",
             "bewertung10000": e[2]} for e in eintraege]]
    return {"datei": ("moodle.json", io.BytesIO(
        json.dumps(roh, ensure_ascii=False).encode("utf-8")), "application/json")}


# ── Namens-Normalisierung ─────────────────────────────────────────────────

def test_normalisiere_faengt_umlaute_und_trennzeichen():
    assert moodle_quiz.normalisiere("Müller") == moodle_quiz.normalisiere("Mueller")
    assert moodle_quiz.normalisiere("Meyer-Schmidt") == moodle_quiz.normalisiere("meyer schmidt")
    assert moodle_quiz.normalisiere("Weiß") == moodle_quiz.normalisiere("Weiss")
    # Ein kürzerer Name darf NICHT auf den längeren fallen
    assert moodle_quiz.normalisiere("Meyer") != moodle_quiz.normalisiere("Meyer-Schmidt")


def test_matche_voll_vor_nachname():
    kandidaten = [{"id": 1, "nachname": "Ahrens", "vorname": "Ada"},
                  {"id": 2, "nachname": "Bloch", "vorname": "Ben"}]
    zeilen = moodle_quiz.matche(
        [{"nachname": "ahrens", "vorname": "ADA", "percent": 80.0},
         {"nachname": "Bloch", "vorname": "", "percent": 50.0}], kandidaten)
    assert (zeilen[0]["student_id"], zeilen[0]["treffer"]) == (1, "voll")
    # Nur Nachname, aber eindeutig → Vorschlag mit erkennbar schwächerem Treffer
    assert (zeilen[1]["student_id"], zeilen[1]["treffer"]) == (2, "nachname")


def test_matche_raet_bei_gleichem_nachnamen_nicht():
    kandidaten = [{"id": 1, "nachname": "Bloch", "vorname": "Ben"},
                  {"id": 2, "nachname": "Bloch", "vorname": "Bea"}]
    zeilen = moodle_quiz.matche(
        [{"nachname": "Bloch", "vorname": "", "percent": 70.0}], kandidaten)
    assert zeilen[0]["student_id"] is None
    assert zeilen[0]["treffer"] == "keiner"


def test_matche_vergibt_einen_schueler_nur_einmal():
    kandidaten = [{"id": 1, "nachname": "Curt", "vorname": "Cem"}]
    zeilen = moodle_quiz.matche(
        [{"nachname": "Curt", "vorname": "Cem", "percent": 90.0},
         {"nachname": "Curt", "vorname": "Cem", "percent": 40.0}], kandidaten)
    assert zeilen[0]["student_id"] == 1
    assert zeilen[1]["student_id"] is None


def test_matche_bevorzugt_den_vollen_treffer_auch_bei_spaeterer_zeile():
    """Der Nachnamens-Treffer der ersten Zeile darf den Schüler nicht
    wegschnappen, den die zweite Zeile mit vollem Namen beansprucht."""
    kandidaten = [{"id": 1, "nachname": "Curt", "vorname": "Cem"}]
    zeilen = moodle_quiz.matche(
        [{"nachname": "Curt", "vorname": "Falsch", "percent": 10.0},
         {"nachname": "Curt", "vorname": "Cem", "percent": 90.0}], kandidaten)
    assert zeilen[1]["student_id"] == 1 and zeilen[1]["treffer"] == "voll"
    assert zeilen[0]["student_id"] is None


# ── Vorschau ──────────────────────────────────────────────────────────────

def test_vorschau_schlaegt_die_schueler_der_lerngruppe_vor(client, exam):
    r = client.post(f"/api/exams/{exam.id}/moodle/vorschau",
                    files=_datei([("Ahrens", "Ada", "80,00"),
                                  ("Unbekannt", "Uwe", "40,00")]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["zeilen"]) == 2
    assert d["zeilen"][0]["treffer"] == "voll"
    assert d["zeilen"][1]["student_id"] is None
    assert d["offen"] == 1
    # Die Auswahlliste kennt alle drei Schüler der Lerngruppe
    assert len(d["kandidaten"]) == 3


def test_vorschau_schreibt_nichts(client, exam, db):
    client.post(f"/api/exams/{exam.id}/moodle/vorschau",
                files=_datei([("Ahrens", "Ada", "80,00")]))
    assert db.query(ExamResult).count() == 0
    assert db.query(ExamStudent).count() == 0


# ── Import ────────────────────────────────────────────────────────────────

def test_import_legt_neuen_feedbackpunkt_an_und_bucht(client, exam, db, stamm):
    ada = stamm["schueler"][0]
    r = client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [{"student_id": ada.id, "percent": 80.0}],
        "fp_id": None, "fp_name": "Moodle-Test LF3",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["gebucht"] == 1 and d["neue_teilnehmer"] == 1

    fp = db.query(ExamFeedbackPoint).filter_by(exam_id=exam.id).one()
    assert fp.name == "Moodle-Test LF3" and fp.max_points == 100.0
    res = db.query(ExamResult).filter_by(exam_id=exam.id, student_id=ada.id).one()
    assert json.loads(res.erreicht_json)[str(fp.id)] == 80.0


def test_import_rechnet_prozent_auf_die_maximalpunkte_um(client, exam, db, stamm):
    fp = ExamFeedbackPoint(exam_id=exam.id, position=0, name="Aufgabe 1",
                           max_points=20.0, scope="individual", eval_type="punkte")
    db.add(fp)
    db.commit()
    ada = stamm["schueler"][0]
    r = client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [{"student_id": ada.id, "percent": 80.0}], "fp_id": fp.id,
    })
    assert r.status_code == 200, r.text
    res = db.query(ExamResult).filter_by(student_id=ada.id).one()
    assert json.loads(res.erreicht_json)[str(fp.id)] == 16.0


def test_import_laesst_andere_feedbackpunkte_unberuehrt(client, exam, db, stamm):
    """Der Import darf nur seine eine Spalte schreiben — sonst räumt er die
    bereits von Hand erfassten Punkte desselben Schülers ab."""
    fp1 = ExamFeedbackPoint(exam_id=exam.id, position=0, name="Handarbeit",
                            max_points=10.0, scope="individual", eval_type="punkte")
    fp2 = ExamFeedbackPoint(exam_id=exam.id, position=1, name="Moodle",
                            max_points=100.0, scope="individual", eval_type="punkte")
    db.add_all([fp1, fp2])
    db.flush()
    ada = stamm["schueler"][0]
    db.add(ExamStudent(exam_id=exam.id, student_id=ada.id, group_label=""))
    db.add(ExamResult(exam_id=exam.id, student_id=ada.id,
                      erreicht_json=json.dumps({str(fp1.id): 7.0})))
    db.commit()

    r = client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [{"student_id": ada.id, "percent": 55.0}], "fp_id": fp2.id,
    })
    assert r.status_code == 200, r.text
    werte = json.loads(db.query(ExamResult).filter_by(student_id=ada.id).one().erreicht_json)
    assert werte[str(fp1.id)] == 7.0
    assert werte[str(fp2.id)] == 55.0


def test_import_weist_nicht_punkte_ziele_ab(client, exam, db, stamm):
    fp = ExamFeedbackPoint(exam_id=exam.id, position=0, name="Mündlich",
                           max_points=0.0, scope="individual", eval_type="note")
    db.add(fp)
    db.commit()
    r = client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [{"student_id": stamm["schueler"][0].id, "percent": 80.0}],
        "fp_id": fp.id,
    })
    assert r.status_code == 400
    assert "Punkte" in r.json()["detail"]


def test_import_ueberspringt_zeilen_ohne_schueler_oder_ergebnis(client, exam, db, stamm):
    ada = stamm["schueler"][0]
    r = client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [
            {"student_id": ada.id, "percent": 60.0},
            {"student_id": None, "percent": 90.0},
            {"student_id": stamm["schueler"][1].id, "percent": None},
        ],
        "fp_id": None, "fp_name": "Moodle",
    })
    assert r.status_code == 200, r.text
    assert r.json()["gebucht"] == 1
    assert db.query(ExamResult).count() == 1


def test_import_legt_keine_neuen_schueler_an(client, exam, db, stamm):
    """Kernpunkt gegenüber dem alten Weg: Es entstehen keine Karteileichen."""
    vorher = db.query(type(stamm["schueler"][0])).count()
    client.post(f"/api/exams/{exam.id}/moodle/import", json={
        "zuordnung": [{"student_id": stamm["schueler"][0].id, "percent": 70.0}],
        "fp_id": None, "fp_name": "Moodle",
    })
    assert db.query(type(stamm["schueler"][0])).count() == vorher
