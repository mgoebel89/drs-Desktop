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


def test_ordne_zu_voller_name_ist_sicher_nachname_nur_vorschlag():
    kern = [{"id": 1, "nachname": "Ahrens", "vorname": "Ada"},
            {"id": 2, "nachname": "Bloch", "vorname": "Ben"}]
    zeilen = moodle_quiz.ordne_zu(
        [{"nachname": "ahrens", "vorname": "ADA", "percent": 80.0},
         {"nachname": "Bloch", "vorname": "", "percent": 50.0}], kern)
    assert (zeilen[0]["status"], zeilen[0]["student_id"]) == ("sicher", 1)
    # Nur der Nachname passt → gefragt wird trotzdem, mit Vorschlag
    assert (zeilen[1]["status"], zeilen[1]["student_id"]) == ("frage", 2)
    assert zeilen[1]["optionen"] == [2]


def test_ordne_zu_raet_bei_gleichem_nachnamen_nicht():
    kern = [{"id": 1, "nachname": "Bloch", "vorname": "Ben"},
            {"id": 2, "nachname": "Bloch", "vorname": "Bea"}]
    zeilen = moodle_quiz.ordne_zu(
        [{"nachname": "Bloch", "vorname": "", "percent": 70.0}], kern)
    assert zeilen[0]["status"] == "frage"
    assert zeilen[0]["student_id"] is None
    assert sorted(zeilen[0]["optionen"]) == [1, 2]


def test_ordne_zu_vergibt_einen_schueler_nur_einmal():
    kern = [{"id": 1, "nachname": "Curt", "vorname": "Cem"}]
    zeilen = moodle_quiz.ordne_zu(
        [{"nachname": "Curt", "vorname": "Cem", "percent": 90.0},
         {"nachname": "Curt", "vorname": "Cem", "percent": 40.0}], kern)
    assert zeilen[0]["status"] == "sicher"
    assert zeilen[1]["status"] == "frage" and zeilen[1]["student_id"] is None
    assert "mehrfach in der Datei" in zeilen[1]["hinweis"]


def test_ordne_zu_bevorzugt_den_vollen_treffer_auch_bei_spaeterer_zeile():
    """Der Nachnamens-Treffer der ersten Zeile darf den Schüler nicht
    wegschnappen, den die zweite Zeile mit vollem Namen beansprucht."""
    kern = [{"id": 1, "nachname": "Curt", "vorname": "Cem"}]
    zeilen = moodle_quiz.ordne_zu(
        [{"nachname": "Curt", "vorname": "Falsch", "percent": 10.0},
         {"nachname": "Curt", "vorname": "Cem", "percent": 90.0}], kern)
    assert (zeilen[1]["status"], zeilen[1]["student_id"]) == ("sicher", 1)
    assert zeilen[0]["status"] == "frage"


def test_ordne_zu_erkennt_die_andere_teilgruppe():
    kern = [{"id": 1, "nachname": "Ahrens", "vorname": "Ada"}]
    weitere = [{"id": 2, "nachname": "Bloch", "vorname": "Ben"}]
    zeilen = moodle_quiz.ordne_zu(
        [{"nachname": "Bloch", "vorname": "Ben", "percent": 60.0},
         {"nachname": "Zander", "vorname": "Zoe", "percent": 30.0}], kern, weitere)
    assert (zeilen[0]["status"], zeilen[0]["student_id"]) == ("teilgruppe", 2)
    assert zeilen[1]["status"] == "keiner" and zeilen[1]["optionen"] == []


# ── Vorschau ──────────────────────────────────────────────────────────────

def test_vorschau_schlaegt_die_schueler_der_lerngruppe_vor(client, exam):
    r = client.post(f"/api/exams/{exam.id}/moodle/vorschau",
                    files=_datei([("Ahrens", "Ada", "80,00"),
                                  ("Unbekannt", "Uwe", "40,00")]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert [z["status"] for z in d["zeilen"]] == ["sicher", "keiner"]
    assert d["zahlen"]["sicher"] == 1 and d["zahlen"]["keiner"] == 1
    # Neu anlegen darf man in der Klasse der Lerngruppe
    assert [k["name"] for k in d["klassen"]] == ["BSMT 26 a"]


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
