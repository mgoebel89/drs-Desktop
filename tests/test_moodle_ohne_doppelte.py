"""Moodle-Import ohne doppelte Schüler, Aufräumen der Altlasten, Gesamt-PDF.

Früher legte „⬆ Moodle-Test" für jeden Namen einen neuen Schüler an; nach dem
Zuordnen einer Klasse stand jeder doppelt in der Prüfung. Diese Tests halten
fest: Es wird nur noch zugeordnet, neu angelegt nur auf ausdrücklichen Wunsch,
und die alten Doppelten lassen sich zusammenführen.
"""
from __future__ import annotations

import io
import json
import re
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.auth import require_user
from app.db import get_db
from app.models import (Exam, ExamFeedbackPoint, ExamResult, ExamStudent,
                        Student, TtKlasse, TtLerngruppeKlasse,
                        TtLerngruppeStudent)
from app.routers import exams as ex_router


@pytest.fixture()
def client(db, stamm):
    app = FastAPI()
    app.include_router(ex_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: stamm["user"]
    return TestClient(app)


def _datei(eintraege):
    roh = [[{"nachname": e[0], "vorname": e[1], "abteilung": "MT",
             "bewertung10000": e[2]} for e in eintraege]]
    return {"datei": ("moodle.json", io.BytesIO(
        json.dumps(roh, ensure_ascii=False).encode("utf-8")), "application/json")}


def _teilgruppe(db, stamm, mitglieder):
    """Teilgruppe aus Schülern der Klasse a — wie der Stammdaten-Assistent sie
    anlegt: Mitglieder + Herkunftsklasse."""
    lg = TtKlasse(user_id=stamm["user"].id, klassen_key="BSMT26a-1",
                  display_name="BSMT 26 a Gruppe 1", art="gruppe",
                  jahrgang_id=stamm["jahrgang"].id)
    db.add(lg)
    db.flush()
    for s in mitglieder:
        db.add(TtLerngruppeStudent(lerngruppe_id=lg.id, student_id=s.id))
    db.add(TtLerngruppeKlasse(lerngruppe_id=lg.id, schulklasse_id=stamm["klasse_a"].id))
    db.commit()
    return lg


def _gast(db, stamm, nachname, vorname):
    """So hat der alte Moodle-Import Schüler angelegt."""
    g = Student(owner_user_id=stamm["user"].id, klassen_key="",
                nachname=nachname, vorname=vorname, active=False)
    db.add(g)
    db.flush()
    return g


# ── Neue Prüfung aus Moodle ───────────────────────────────────────────────

def test_vorschau_plant_gegen_die_gewaehlte_klasse(client, stamm):
    r = client.post("/api/exams/moodle/vorschau",
                    data={"ziel_typ": "klasse", "ziel_id": str(stamm["klasse_a"].id)},
                    files=_datei([("Ahrens", "Ada", "80,00"), ("Bloch", "", "50,00"),
                                  ("Neu", "Nina", "70,00")]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert [z["status"] for z in d["zeilen"]] == ["sicher", "frage", "keiner"]
    assert d["lerngruppe"]["id"] == stamm["lg_a"].id


def test_vorschau_ohne_ziel_wird_abgewiesen(client):
    r = client.post("/api/exams/moodle/vorschau",
                    files=_datei([("Ahrens", "Ada", "80,00")]))
    assert r.status_code == 400


def test_import_legt_keine_doppelten_an(client, db, stamm):
    ada, ben, cem = stamm["schueler"]
    vorher = db.query(Student).count()
    r = client.post("/api/exams/moodle", json={
        "titel": "Moodle LF3", "datum": "2026-10-20",
        "ziel_typ": "klasse", "ziel_id": stamm["klasse_a"].id,
        "zeilen": [
            {"nachname": "Ahrens", "vorname": "Ada", "percent": 80.0, "student_id": ada.id},
            {"nachname": "Bloch", "vorname": "", "percent": 50.0, "student_id": ben.id},
            {"nachname": "Fremd", "vorname": "F", "percent": 90.0, "student_id": None},
        ],
    })
    assert r.status_code == 200, r.text
    assert db.query(Student).count() == vorher

    ex = db.get(Exam, r.json()["id"])
    assert ex.lerngruppe_id == stamm["lg_a"].id
    assert ex.klassen_key == "BSMT26a"
    # Teilnehmer sind die drei echten Schüler — Cem ohne Ergebnis
    teilnehmer = {es.student_id for es in db.query(ExamStudent).filter_by(exam_id=ex.id)}
    assert teilnehmer == {ada.id, ben.id, cem.id}
    fp = db.query(ExamFeedbackPoint).filter_by(exam_id=ex.id).one()
    werte = {r.student_id: json.loads(r.erreicht_json)[str(fp.id)]
             for r in db.query(ExamResult).filter_by(exam_id=ex.id)}
    assert werte == {ada.id: 80.0, ben.id: 50.0}


def test_neu_anlegen_nur_auf_wunsch_und_in_der_klasse(client, db, stamm):
    r = client.post("/api/exams/moodle", json={
        "ziel_typ": "klasse", "ziel_id": stamm["klasse_a"].id,
        "zeilen": [{"nachname": "Neu", "vorname": "Nina", "percent": 70.0,
                    "student_id": None, "neu_klasse_id": stamm["klasse_a"].id}],
    })
    assert r.status_code == 200, r.text
    nina = db.query(Student).filter_by(nachname="Neu").one()
    assert nina.active is True
    assert nina.schulklasse_id == stamm["klasse_a"].id
    assert nina.klassen_key == "BSMT26a"
    assert nina.jahrgang_id == stamm["jahrgang"].id


def test_neu_anlegen_in_fremder_klasse_wird_abgewiesen(client, db, stamm):
    vorher = db.query(Exam).count()
    r = client.post("/api/exams/moodle", json={
        "ziel_typ": "klasse", "ziel_id": stamm["klasse_a"].id,
        "zeilen": [{"nachname": "Neu", "vorname": "Nina", "percent": 70.0,
                    "neu_klasse_id": stamm["klasse_b"].id}],
    })
    assert r.status_code == 400
    db.rollback()
    assert db.query(Student).filter_by(nachname="Neu").count() == 0
    assert db.query(Exam).count() == vorher


def test_ein_schueler_darf_nicht_zwei_zeilen_bekommen(client, stamm):
    ada = stamm["schueler"][0]
    r = client.post("/api/exams/moodle", json={
        "ziel_typ": "klasse", "ziel_id": stamm["klasse_a"].id,
        "zeilen": [
            {"nachname": "Ahrens", "vorname": "Ada", "percent": 80.0, "student_id": ada.id},
            {"nachname": "Ahrens", "vorname": "A.", "percent": 20.0, "student_id": ada.id},
        ],
    })
    assert r.status_code == 400
    assert "mehreren Zeilen" in r.json()["detail"]


# ── Teilgruppen ───────────────────────────────────────────────────────────

def test_teilgruppe_fragt_die_andere_haelfte_gesammelt_ab(client, db, stamm):
    ada, ben, cem = stamm["schueler"]
    lg = _teilgruppe(db, stamm, [ada, ben])
    r = client.post("/api/exams/moodle/vorschau",
                    data={"ziel_typ": "lerngruppe", "ziel_id": str(lg.id)},
                    files=_datei([("Ahrens", "Ada", "80,00"), ("Curt", "Cem", "60,00")]))
    assert r.status_code == 200, r.text
    zeilen = r.json()["zeilen"]
    assert [z["status"] for z in zeilen] == ["sicher", "teilgruppe"]
    assert zeilen[1]["student_id"] == cem.id


def test_teilgruppe_aufgenommener_schueler_wird_teilnehmer(client, db, stamm):
    ada, ben, cem = stamm["schueler"]
    lg = _teilgruppe(db, stamm, [ada, ben])
    r = client.post("/api/exams/moodle", json={
        "ziel_typ": "lerngruppe", "ziel_id": lg.id,
        "zeilen": [
            {"nachname": "Ahrens", "vorname": "Ada", "percent": 80.0, "student_id": ada.id},
            {"nachname": "Curt", "vorname": "Cem", "percent": 60.0, "student_id": cem.id},
        ],
    })
    assert r.status_code == 200, r.text
    teilnehmer = {es.student_id for es in
                  db.query(ExamStudent).filter_by(exam_id=r.json()["id"])}
    assert teilnehmer == {ada.id, ben.id, cem.id}


def test_neu_angelegter_kommt_auch_in_die_teilgruppe(client, db, stamm):
    ada, ben, _ = stamm["schueler"]
    lg = _teilgruppe(db, stamm, [ada, ben])
    r = client.post("/api/exams/moodle", json={
        "ziel_typ": "lerngruppe", "ziel_id": lg.id,
        "zeilen": [{"nachname": "Neu", "vorname": "Nina", "percent": 70.0,
                    "neu_klasse_id": stamm["klasse_a"].id}],
    })
    assert r.status_code == 200, r.text
    nina = db.query(Student).filter_by(nachname="Neu").one()
    assert db.get(TtLerngruppeStudent, {"lerngruppe_id": lg.id, "student_id": nina.id})


# ── Altlasten zusammenführen ──────────────────────────────────────────────

@pytest.fixture()
def altfall(db, stamm):
    """Prüfung wie nach altem Import + späterer Zuordnung: echte Schüler UND
    Gäste mit den Moodle-Werten."""
    ada, ben, cem = stamm["schueler"]
    ex = Exam(owner_user_id=stamm["user"].id, title="Alt", datum="2026-09-01",
              lerngruppe_id=stamm["lg_a"].id, klassen_key="BSMT26a",
              bewertung_mode="punkte")
    db.add(ex)
    db.flush()
    fp_m = ExamFeedbackPoint(exam_id=ex.id, position=0, name="Gesamtbewertung",
                             max_points=100.0, scope="individual", eval_type="punkte")
    fp_h = ExamFeedbackPoint(exam_id=ex.id, position=1, name="Hand",
                             max_points=10.0, scope="individual", eval_type="punkte")
    db.add_all([fp_m, fp_h])
    db.flush()
    g_ada = _gast(db, stamm, "Ahrens", "Ada")
    g_ben = _gast(db, stamm, "Bloch", "Ben")
    g_x = _gast(db, stamm, "Xaver", "Xia")
    for s in (ada, ben, cem, g_ada, g_ben, g_x):
        db.add(ExamStudent(exam_id=ex.id, student_id=s.id,
                           group_label="G1" if s is g_ben else ""))
    db.add(ExamResult(exam_id=ex.id, student_id=g_ada.id,
                      erreicht_json=json.dumps({str(fp_m.id): 80.0}), comment="gut"))
    db.add(ExamResult(exam_id=ex.id, student_id=g_ben.id,
                      erreicht_json=json.dumps({str(fp_m.id): 50.0})))
    db.add(ExamResult(exam_id=ex.id, student_id=g_x.id,
                      erreicht_json=json.dumps({str(fp_m.id): 30.0})))
    # Ben hat schon einen Handwert — der muss bleiben
    db.add(ExamResult(exam_id=ex.id, student_id=ben.id,
                      erreicht_json=json.dumps({str(fp_h.id): 7.0})))
    db.commit()
    return {"ex": ex, "fp_m": fp_m, "fp_h": fp_h,
            "g_ada": g_ada, "g_ben": g_ben, "g_x": g_x}


def test_gaeste_plan_erkennt_die_doppelten(client, stamm, altfall):
    r = client.get(f"/api/exams/{altfall['ex'].id}/gaeste")
    assert r.status_code == 200, r.text
    zeilen = {z["gast_id"]: z for z in r.json()["zeilen"]}
    ada, ben, _ = stamm["schueler"]
    assert zeilen[altfall["g_ada"].id]["student_id"] == ada.id
    assert zeilen[altfall["g_ada"].id]["status"] == "sicher"
    assert zeilen[altfall["g_ben"].id]["student_id"] == ben.id
    assert zeilen[altfall["g_x"].id]["status"] == "keiner"


def test_gaeste_zusammenfuehren(client, db, stamm, altfall):
    ada, ben, _ = stamm["schueler"]
    ex, fp_m, fp_h = altfall["ex"], altfall["fp_m"], altfall["fp_h"]
    r = client.post(f"/api/exams/{ex.id}/gaeste/zusammenfuehren", json={"zeilen": [
        {"gast_id": altfall["g_ada"].id, "student_id": ada.id},
        {"gast_id": altfall["g_ben"].id, "student_id": ben.id},
        {"gast_id": altfall["g_x"].id, "student_id": None},   # übersprungen
    ]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["zusammengefuehrt"], d["geloescht"]) == (2, 2)

    db.expire_all()
    ergebnis = {r.student_id: r for r in db.query(ExamResult).filter_by(exam_id=ex.id)}
    assert json.loads(ergebnis[ada.id].erreicht_json) == {str(fp_m.id): 80.0}
    assert ergebnis[ada.id].comment == "gut"
    # Ben: Moodle-Wert dazu, Handwert bleibt
    assert json.loads(ergebnis[ben.id].erreicht_json) == {
        str(fp_h.id): 7.0, str(fp_m.id): 50.0}
    # Gruppe wandert mit
    assert db.get(ExamStudent, {"exam_id": ex.id, "student_id": ben.id}).group_label == "G1"
    # Gäste weg, der übersprungene bleibt
    assert db.get(Student, altfall["g_ada"].id) is None
    assert db.get(Student, altfall["g_ben"].id) is None
    assert db.get(Student, altfall["g_x"].id) is not None


def test_gast_in_die_klasse_aufnehmen_statt_neu_anlegen(client, db, stamm, altfall):
    vorher = db.query(Student).count()
    r = client.post(f"/api/exams/{altfall['ex'].id}/gaeste/zusammenfuehren", json={
        "zeilen": [{"gast_id": altfall["g_x"].id,
                    "neu_klasse_id": stamm["klasse_a"].id}]})
    assert r.status_code == 200, r.text
    assert db.query(Student).count() == vorher
    x = db.get(Student, altfall["g_x"].id)
    assert x.active is True and x.schulklasse_id == stamm["klasse_a"].id
    assert x.klassen_key == "BSMT26a"


def test_gast_der_noch_in_anderer_pruefung_steht_bleibt(client, db, stamm, altfall):
    andere = Exam(owner_user_id=stamm["user"].id, title="Andere", datum="2026-09-02")
    db.add(andere)
    db.flush()
    db.add(ExamStudent(exam_id=andere.id, student_id=altfall["g_ada"].id, group_label=""))
    db.commit()
    r = client.post(f"/api/exams/{altfall['ex'].id}/gaeste/zusammenfuehren", json={
        "zeilen": [{"gast_id": altfall["g_ada"].id,
                    "student_id": stamm["schueler"][0].id}]})
    assert r.json()["geloescht"] == 0
    assert db.get(Student, altfall["g_ada"].id) is not None


def test_gaeste_brauchen_eine_zuordnung(client, db, stamm):
    ex = Exam(owner_user_id=stamm["user"].id, title="Ohne", datum="2026-09-01")
    db.add(ex)
    db.commit()
    r = client.get(f"/api/exams/{ex.id}/gaeste")
    assert r.status_code == 400
    assert "zuerst" in r.json()["detail"]


def test_pool_und_ausgetretene_sind_keine_gaeste(db, stamm):
    pool = Student(owner_user_id=stamm["user"].id, nachname="P", vorname="",
                   jahrgang_id=stamm["jahrgang"].id, active=True)
    weg = Student(owner_user_id=stamm["user"].id, nachname="W", vorname="",
                  schulklasse_id=stamm["klasse_a"].id, klassen_key="BSMT26a",
                  active=False)
    assert not ex_router._ist_moodle_gast(pool)
    assert not ex_router._ist_moodle_gast(weg)


# ── Gesamt-PDF ────────────────────────────────────────────────────────────

def _leeres_pdf(seiten: int) -> bytes:
    w = PdfWriter()
    for _ in range(seiten):
        w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture()
def bewertet(db, stamm, monkeypatch):
    """Prüfung, in der Curt und Ahrens bewertet sind, Bloch nicht. Das Rendern
    wird ersetzt: jeder Bogen 1 Seite, die Reihenfolge wird mitgeschrieben."""
    ada, ben, cem = stamm["schueler"]
    ex = Exam(owner_user_id=stamm["user"].id, title="Klassenarbeit",
              datum="2026-10-01", lerngruppe_id=stamm["lg_a"].id,
              klassen_key="BSMT26a", bewertung_mode="punkte")
    db.add(ex)
    db.flush()
    fp = ExamFeedbackPoint(exam_id=ex.id, position=0, name="A1", max_points=10.0,
                           scope="individual", eval_type="punkte")
    db.add(fp)
    db.flush()
    # Gruppen so gewählt, dass die Bewertungs-Reihenfolge (Gruppe zuerst)
    # von der alphabetischen abweicht
    for s, g in ((ada, "Z"), (ben, ""), (cem, "")):
        db.add(ExamStudent(exam_id=ex.id, student_id=s.id, group_label=g))
    for s in (ada, cem):
        db.add(ExamResult(exam_id=ex.id, student_id=s.id,
                          erreicht_json=json.dumps({str(fp.id): 5.0})))
    db.commit()

    reihenfolge = []

    async def fake_render(html):
        reihenfolge.append(re.search(r"<title>([^,]+),", html).group(1).strip())
        return _leeres_pdf(1)
    monkeypatch.setattr(ex_router, "render_pdf", fake_render)
    return {"ex": ex, "reihenfolge": reihenfolge}


def test_gesamt_pdf_alphabetisch_ohne_unbewertete(client, bewertet):
    r = client.get(f"/exams/{bewertet['ex'].id}/export.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert bewertet["reihenfolge"] == ["Ahrens", "Curt"]
    assert len(PdfReader(io.BytesIO(r.content)).pages) == 2
    assert unquote(r.headers["x-ohne-bewertung"]) == "Bloch, Ben"


def test_gesamt_pdf_duplex_fuegt_leerseiten_ein(client, bewertet):
    r = client.get(f"/exams/{bewertet['ex'].id}/export.pdf?duplex=1")
    assert r.status_code == 200, r.text
    assert len(PdfReader(io.BytesIO(r.content)).pages) == 4


def test_gesamt_pdf_ohne_bewertungen(client, db, stamm):
    ex = Exam(owner_user_id=stamm["user"].id, title="Leer", datum="2026-10-01")
    db.add(ex)
    db.flush()
    db.add(ExamStudent(exam_id=ex.id, student_id=stamm["schueler"][0].id, group_label=""))
    db.commit()
    r = client.get(f"/exams/{ex.id}/export.pdf")
    assert r.status_code == 400


# ── Zwei Teilgruppen-JSONs in EINE Prüfung ────────────────────────────────

@pytest.fixture()
def klassenpruefung(db, stamm):
    """Über den Assistenten angelegt (Notenmodus), Teil 1 schon importiert:
    Ada hat 80 % auf „Moodle-Test"."""
    ada = stamm["schueler"][0]
    ex = Exam(owner_user_id=stamm["user"].id, title="KA", datum="2026-10-01",
              lerngruppe_id=stamm["lg_a"].id, klassen_key="BSMT26a",
              bewertung_mode="note")
    db.add(ex)
    db.flush()
    fp = ExamFeedbackPoint(exam_id=ex.id, position=0, name="Moodle-Test",
                           max_points=100.0, scope="individual", eval_type="punkte")
    db.add(fp)
    db.flush()
    for s in stamm["schueler"]:
        db.add(ExamStudent(exam_id=ex.id, student_id=s.id, group_label=""))
    db.add(ExamResult(exam_id=ex.id, student_id=ada.id,
                      erreicht_json=json.dumps({str(fp.id): 80.0})))
    db.commit()
    return {"ex": ex, "fp": fp}


def test_vorschau_schlaegt_den_vorhandenen_moodle_punkt_vor(client, klassenpruefung):
    ex = klassenpruefung["ex"]
    r = client.post(f"/api/exams/{ex.id}/moodle/vorschau",
                    files=_datei([("Ahrens", "Ada", "-"), ("Curt", "Cem", "40,00")]))
    assert r.status_code == 200, r.text
    assert r.json()["vorschlag_fp_id"] == klassenpruefung["fp"].id


def test_kein_vorschlag_ohne_moodle_punkt(client, db, stamm):
    ex = Exam(owner_user_id=stamm["user"].id, title="Hand", datum="2026-10-01",
              lerngruppe_id=stamm["lg_a"].id, klassen_key="BSMT26a")
    db.add(ex)
    db.flush()
    db.add(ExamFeedbackPoint(exam_id=ex.id, position=0, name="Aufgabe 1",
                             max_points=10.0, scope="individual", eval_type="punkte"))
    db.commit()
    r = client.post(f"/api/exams/{ex.id}/moodle/vorschau",
                    files=_datei([("Curt", "Cem", "40,00")]))
    assert r.json()["vorschlag_fp_id"] is None


def test_teil_zwei_landet_in_derselben_spalte(client, db, stamm, klassenpruefung):
    ada, _, cem = stamm["schueler"]
    ex, fp = klassenpruefung["ex"], klassenpruefung["fp"]
    r = client.post(f"/api/exams/{ex.id}/moodle/import", json={
        "zuordnung": [{"student_id": cem.id, "percent": 40.0}], "fp_id": fp.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(ExamFeedbackPoint).filter_by(exam_id=ex.id).count() == 1
    werte = {r.student_id: json.loads(r.erreicht_json)
             for r in db.query(ExamResult).filter_by(exam_id=ex.id)}
    assert werte == {ada.id: {str(fp.id): 80.0}, cem.id: {str(fp.id): 40.0}}


# ── Schüler-PDF: Punkte-Layout und leere Zeilen ───────────────────────────

def _pdf_html(client, ex, student, monkeypatch):
    erfasst = {}

    async def fake_render(html):
        erfasst["html"] = html
        return _leeres_pdf(1)
    monkeypatch.setattr(ex_router, "render_pdf", fake_render)
    r = client.get(f"/exams/{ex.id}/export/pdf", params={"student_id": student.id})
    assert r.status_code == 200, r.text
    return erfasst["html"]


def test_pdf_punkte_layout_auch_im_notenmodus(client, db, stamm, klassenpruefung,
                                               monkeypatch):
    """Nur Punkte-Feedbackpunkte → Erreicht | Max | Prozent, nicht „Note"."""
    html = _pdf_html(client, klassenpruefung["ex"], stamm["schueler"][0], monkeypatch)
    kopf = re.sub(r"\s+", " ", html.split("<thead>")[1].split("</thead>")[0])
    assert "Erreicht" in kopf and "Max" in kopf and "Prozent" in kopf
    assert "Gewichtung" not in kopf
    assert "80 %" in html or "80,0 %" in html


def test_pdf_blendet_punkte_ohne_wert_aus(client, db, stamm, klassenpruefung,
                                          monkeypatch):
    """Der zweite Moodle-Teil, den dieser Schüler nicht geschrieben hat, fällt weg."""
    ex = klassenpruefung["ex"]
    db.add(ExamFeedbackPoint(exam_id=ex.id, position=1, name="Moodle-Test Teil 2",
                             max_points=100.0, scope="individual", eval_type="punkte"))
    db.commit()
    html = _pdf_html(client, ex, stamm["schueler"][0], monkeypatch)
    tbody = html.split("<tbody>")[1].split("</tbody>")[0]
    assert "Moodle-Test" in tbody
    assert "Teil 2" not in tbody
