"""Unterrichtsbesuche: Vorgaben, Einstellungen, Besuch-Assistent, Einträge,
Fotos und das PDF-Protokoll."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from pypdf import PdfReader

from app.auth import require_user
from app.config import settings
from app.db import get_db
from app.models import (AppFile, UbAnwaerter, UbBesuch, UbEintrag, UbKategorie,
                        UbPhase, User)
from app.routers import unterrichtsbesuche as ub_router
from app.services import ub_protokoll_pdf
from app.services import unterrichtsbesuche as ub


@pytest.fixture()
def user(db):
    u = User(username="mg", password_hash="x", full_name="Matthias Göbel")
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def client(db, user, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    app = FastAPI()
    app.include_router(ub_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def _besuch(client, **extra) -> int:
    kat = client.get("/api/ub/katalog").json()["kriterien"]
    daten = {
        "neuer_anwaerter": {"name": "Anna Beispiel", "faecher": "Mechatronik"},
        "datum": "2026-10-05", "beginn": "08:00", "ende": "09:30",
        "klasse": "BSMT 26a", "raum": "B112", "thema": "Pneumatik: Wegeventile",
        "lernziele": "Die SuS unterscheiden 3/2- und 5/2-Wegeventile.",
        # Auswahl aus dem Katalog: 2. und 1. Beratungsschwerpunkt, dazu Müll
        "schwerpunkte": [kat[1]["id"], kat[0]["id"], "x", 99999, kat[1]["id"]],
    }
    daten.update(extra)
    r = client.post("/api/ub/besuche", json=daten)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Vorgaben & Einstellungen ─────────────────────────────────────────────

def test_eintrag_ohne_kategorie_wird_abgewiesen(client, db, user):
    """Keine Vorbelegung: Ereignisse kommen in beliebiger Folge, jeder Eintrag
    wird bewusst eingeordnet."""
    bid = _besuch(client)
    assert client.post(f"/api/ub/besuche/{bid}/eintraege",
                       json={"text": "ohne Kategorie"}).status_code == 400


def test_vorgaben_werden_genau_einmal_angelegt(db, user):
    k = ub.katalog(db, user)
    assert [x["name"] for x in k["kategorien"]] == ["Beobachtung", "Idee", "Anmerkung"]
    assert len(k["phasen"]) == len(ub.VORGABE_PHASEN)
    # Alles löschen → kein erneutes Seeden
    for p in db.query(UbPhase).all():
        db.delete(p)
    db.commit()
    assert ub.katalog(db, user)["phasen"] == []


def test_kategorie_anlegen_mit_ungueltigen_werten_faellt_auf_vorgaben(client, db, user):
    ub.einstellung(db, user)
    r = client.post("/api/ub/einstellungen/kategorien", json={
        "name": "Frage", "icon": "gibtsnicht", "farbe": "#123456", "spalte": "quer"})
    assert r.status_code == 200, r.text
    o = r.json()["obj"]
    assert (o["icon"], o["farbe"], o["spalte"]) == ("auge", "#00639C", "verlauf")
    assert o["position"] == 3


def test_einstellung_ohne_namen_wird_abgewiesen(client):
    assert client.post("/api/ub/einstellungen/phasen", json={"name": " "}).status_code == 400


def test_benutzte_kategorie_nur_stilllegen(client, db, user):
    ub.einstellung(db, user)
    bid = _besuch(client)
    kat = db.query(UbKategorie).filter_by(name="Idee").one()
    client.post(f"/api/ub/besuche/{bid}/eintraege",
                json={"kategorie_id": kat.id, "text": "Gruppen mischen", "zeit": "08:10"})
    r = client.post(f"/api/ub/einstellungen/kategorien/{kat.id}/delete")
    assert r.status_code == 409
    r = client.post(f"/api/ub/einstellungen/kategorien/{kat.id}/save", json={"active": False})
    assert r.json()["obj"]["active"] is False
    assert r.json()["obj"]["nutzung"] == 1


def test_reihenfolge(client, db, user):
    ids = [p["id"] for p in ub.katalog(db, user)["phasen"]]
    client.post("/api/ub/einstellungen/phasen/reihenfolge", json={"ids": ids[::-1]})
    assert [p["id"] for p in ub.katalog(db, user)["phasen"]] == ids[::-1]


# ── Besuch-Assistent ─────────────────────────────────────────────────────

def test_besuch_mit_neuem_anwaerter_in_einem_request(client, db):
    bid = _besuch(client)
    b = db.get(UbBesuch, bid)
    assert b.anwaerter.name == "Anna Beispiel"
    assert b.status == "geplant"
    d = client.get(f"/api/ub/besuche/{bid}").json()["besuch"]
    # Katalog-Reihenfolge, doppelte/fremde/ungültige IDs fallen heraus
    assert [s["text"] for s in d["schwerpunkte"]] == ub.VORGABE_KRITERIEN[:2]


def test_besuch_ohne_datum_hinterlaesst_keinen_anwaerter(client, db):
    r = client.post("/api/ub/besuche", json={"neuer_anwaerter": {"name": "X"}, "datum": ""})
    assert r.status_code == 400
    db.rollback()
    assert db.query(UbAnwaerter).count() == 0


def test_abwaehlen_nimmt_eintraegen_nicht_die_zuordnung(client, db, user):
    bid = _besuch(client)
    kat = ub.katalog(db, user)
    sp = client.get(f"/api/ub/besuche/{bid}").json()["besuch"]["schwerpunkte"]
    e = client.post(f"/api/ub/besuche/{bid}/eintraege", json={
        "kategorie_id": kat["kategorien"][0]["id"], "text": "x",
        "kriterium_id": sp[0]["id"]}).json()["eintrag"]
    client.post(f"/api/ub/besuche/{bid}/save", json={"schwerpunkte": [sp[1]["id"]]})
    neu = client.get(f"/api/ub/besuche/{bid}").json()["besuch"]
    assert [s["id"] for s in neu["schwerpunkte"]] == [sp[1]["id"]]
    assert neu["eintraege"][0]["kriterium_id"] == sp[0]["id"]


def test_gewaehlter_schwerpunkt_zaehlt_als_nutzung(client, db, user):
    bid = _besuch(client)
    kid = client.get(f"/api/ub/besuche/{bid}").json()["besuch"]["schwerpunkte"][0]["id"]
    assert client.post(f"/api/ub/einstellungen/kriterien/{kid}/delete").status_code == 409


def test_anwaerter_mit_besuchen_nicht_loeschbar(client, db):
    bid = _besuch(client)
    aid = db.get(UbBesuch, bid).anwaerter_id
    assert client.post(f"/api/ub/anwaerter/{aid}/delete").status_code == 409


# ── Einträge ─────────────────────────────────────────────────────────────

def test_eintraege_chronologisch_mit_phasen(client, db, user):
    bid = _besuch(client)
    k = ub.katalog(db, user)
    beob, idee = k["kategorien"][0]["id"], k["kategorien"][1]["id"]
    einstieg, erarbeitung = k["phasen"][0]["id"], k["phasen"][1]["id"]
    post = lambda d: client.post(f"/api/ub/besuche/{bid}/eintraege", json=d)
    post({"art": "phase", "phase_id": einstieg, "zeit": "08:00"})
    post({"kategorie_id": beob, "text": "Stummer Impuls", "zeit": "08:02"})
    post({"art": "phase", "phase_id": erarbeitung, "zeit": "08:15"})
    r = post({"kategorie_id": idee, "text": "Früher", "zeit": "08:01"})
    assert r.json()["status"] == "laufend"

    liste = ub.mit_phasen(ub.eintraege(db, bid))
    assert [(e.text or "P", ph) for e, ph in liste] == [
        ("P", einstieg), ("Früher", einstieg), ("Stummer Impuls", einstieg),
        ("P", erarbeitung)]


def test_zuordnung_setzen_und_aufheben(client, db, user):
    bid = _besuch(client)
    k = ub.katalog(db, user)
    e = client.post(f"/api/ub/besuche/{bid}/eintraege", json={
        "kategorie_id": k["kategorien"][0]["id"], "text": "x",
        "kriterium_id": k["kriterien"][3]["id"]}).json()["eintrag"]
    assert e["kriterium_id"] == k["kriterien"][3]["id"]
    e = client.post(f"/api/ub/eintraege/{e['id']}/save",
                    json={"kriterium_id": None}).json()["eintrag"]
    assert e["kriterium_id"] is None and e["text"] == "x"


def test_teil_update_und_wertung(client, db, user):
    bid = _besuch(client)
    kat = ub.katalog(db, user)["kategorien"][0]["id"]
    e = client.post(f"/api/ub/besuche/{bid}/eintraege", json={
        "kategorie_id": kat, "text": "Klare Arbeitsaufträge", "zeit": "08:20"}).json()["eintrag"]
    e = client.post(f"/api/ub/eintraege/{e['id']}/save",
                    json={"wertung": "staerke"}).json()["eintrag"]
    assert (e["wertung"], e["text"], e["zeit"]) == ("staerke", "Klare Arbeitsaufträge", "08:20")
    e = client.post(f"/api/ub/eintraege/{e['id']}/save",
                    json={"wertung": "quatsch"}).json()["eintrag"]
    assert e["wertung"] == ""


def test_eintrag_braucht_text_ausser_foto_folgt(client, db, user):
    bid = _besuch(client)
    kat = ub.katalog(db, user)["kategorien"][0]["id"]
    url = f"/api/ub/besuche/{bid}/eintraege"
    assert client.post(url, json={"kategorie_id": kat, "text": ""}).status_code == 400
    assert client.post(url, json={"kategorie_id": kat, "text": "",
                                  "foto_folgt": True}).status_code == 200


def test_fremde_kategorie_wird_abgewiesen(client, db, user):
    fremd = User(username="fremd", password_hash="x")
    db.add(fremd)
    db.commit()
    ub.einstellung(db, fremd)
    fremde_kat = db.query(UbKategorie).filter_by(user_id=fremd.id).first().id
    bid = _besuch(client)
    r = client.post(f"/api/ub/besuche/{bid}/eintraege",
                    json={"kategorie_id": fremde_kat, "text": "x"})
    assert r.status_code == 400


def test_fremder_besuch_ist_unsichtbar(client, db):
    fremd = User(username="fremd2", password_hash="x")
    db.add(fremd)
    db.flush()
    a = UbAnwaerter(user_id=fremd.id, name="Fremd")
    db.add(a)
    db.flush()
    b = UbBesuch(user_id=fremd.id, anwaerter_id=a.id, datum="2026-10-01")
    db.add(b)
    db.commit()
    assert client.get(f"/api/ub/besuche/{b.id}").status_code == 404
    assert client.post(f"/api/ub/besuche/{b.id}/delete").status_code == 404


def _jpeg(breite=800, hoehe=600) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (breite, hoehe), (0, 99, 156)).save(buf, "JPEG")
    return buf.getvalue()


def test_foto_ersetzen_und_loeschen_raeumt_auf(client, db, user):
    bid = _besuch(client)
    kat = ub.katalog(db, user)["kategorien"][0]["id"]
    eid = client.post(f"/api/ub/besuche/{bid}/eintraege",
                      json={"kategorie_id": kat, "text": "Tafelbild"}).json()["eintrag"]["id"]
    url = f"/api/ub/eintraege/{eid}/foto"
    r1 = client.post(url, files={"file": ("tafel.jpg", _jpeg(), "image/jpeg")})
    assert r1.status_code == 200, r1.text
    r2 = client.post(url, files={"file": ("tafel2.jpg", _jpeg(), "image/jpeg")})
    assert r1.json()["eintrag"]["foto"] != r2.json()["eintrag"]["foto"]
    assert db.query(AppFile).count() == 1
    assert client.post(url, files={"file": ("x.pdf", b"%PDF", "application/pdf")}).status_code == 400
    client.post(f"/api/ub/eintraege/{eid}/delete")
    assert db.query(AppFile).count() == 0


def test_besuch_loeschen_nimmt_eintraege_mit(client, db, user):
    bid = _besuch(client)
    kat = ub.katalog(db, user)["kategorien"][0]["id"]
    client.post(f"/api/ub/besuche/{bid}/eintraege", json={"kategorie_id": kat, "text": "x"})
    assert client.post(f"/api/ub/besuche/{bid}/delete").status_code == 200
    assert db.query(UbEintrag).count() == 0
    assert db.query(UbAnwaerter).count() == 1   # der Anwärter bleibt


# ── PDF ──────────────────────────────────────────────────────────────────

def test_pdf_enthaelt_verlauf_und_alle_piktogramme_sind_zeichenbar(client, db, user):
    bid = _besuch(client)
    k = ub.katalog(db, user)
    client.post(f"/api/ub/besuche/{bid}/eintraege",
                json={"art": "phase", "phase_id": k["phasen"][1]["id"], "zeit": "08:05"})
    eid = client.post(f"/api/ub/besuche/{bid}/eintraege", json={
        "kategorie_id": k["kategorien"][0]["id"], "zeit": "08:06",
        "text": "Lehrer gibt stummen Impuls 👀 → SuS reagieren", "wertung": "staerke",
    }).json()["eintrag"]["id"]
    client.post(f"/api/ub/eintraege/{eid}/foto",
                files={"file": ("tafel.jpg", _jpeg(600, 900), "image/jpeg")})

    # Jedes Icon einmal verwenden, damit der Pfad-Zeichner alle Befehle sieht
    for name in ub.ICONS:
        client.post("/api/ub/einstellungen/kategorien", json={"name": name, "icon": name})
    for kat in db.query(UbKategorie).filter_by(user_id=user.id).all():
        client.post(f"/api/ub/besuche/{bid}/eintraege",
                    json={"kategorie_id": kat.id, "text": f"Test {kat.name}", "zeit": "08:30"})

    r = client.get(f"/unterrichtsbesuche/{bid}/protokoll.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Pneumatik: Wegeventile" in text
    assert "Erarbeitung" in text
    assert "SuS reagieren" in text
    assert "Seite 1 von" in text


def test_pfad_parser_kennt_alle_befehle():
    class Fake:
        def __init__(self):
            self.ops = []

        def beginPath(self):
            return self

        def moveTo(self, *a): self.ops.append("M")
        def lineTo(self, *a): self.ops.append("L")
        def curveTo(self, *a): self.ops.append("C")
        def close(self): self.ops.append("Z")
        def drawPath(self, *a, **k): pass

    f = Fake()
    ub_protokoll_pdf._pfad(f, "M1 2 L3 4 5 6 H7 V8 C1 1 2 2 3 3 Q4 4 5 5 Z")
    assert f.ops == ["M", "L", "L", "L", "L", "C", "C", "Z"]


# ── Migration 0035: Freitext-Schwerpunkte → Katalog ──────────────────────

def test_migration_0035_uebernimmt_freitext_schwerpunkte(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    import sqlalchemy as sa

    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    url = f"sqlite:///{tmp_path / 'm.sqlite'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0034")

    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO users (id, username, password_hash, role, full_name, active, "
                          "must_change_pw, failed_attempts) VALUES (1,'u','x','teacher','',1,0,0)"))
        c.execute(sa.text("INSERT INTO ub_kriterien (id, user_id, name, position, active) "
                          "VALUES (7, 1, 'Ergebnissicherung', 0, 1)"))
        c.execute(sa.text("INSERT INTO ub_anwaerter (id, user_id, name) VALUES (1, 1, 'A')"))
        c.execute(sa.text("INSERT INTO ub_besuche (id, user_id, anwaerter_id, datum) "
                          "VALUES (1, 1, 1, '2026-09-29')"))
        c.execute(sa.text("INSERT INTO ub_schwerpunkte (id, besuch_id, text, position) VALUES "
                          "(1, 1, '  ergebnissicherung ', 0), (2, 1, 'Impulsgebung', 1), "
                          "(3, 1, 'Impulsgebung', 2)"))
        c.execute(sa.text("INSERT INTO ub_eintraege (id, besuch_id, art, schwerpunkt_id) VALUES "
                          "(1, 1, 'eintrag', 1), (2, 1, 'eintrag', 2), (3, 1, 'eintrag', 3)"))

    command.upgrade(cfg, "0035")
    with eng.connect() as c:
        krit = dict(c.execute(sa.text("SELECT name, id FROM ub_kriterien")).fetchall())
        assert set(krit) == {"Ergebnissicherung", "Impulsgebung"}   # gleicher Name → derselbe
        sp = c.execute(sa.text("SELECT kriterium_id FROM ub_schwerpunkte ORDER BY position")).fetchall()
        assert [r[0] for r in sp] == [7, krit["Impulsgebung"]]       # Dublette entfernt
        e = dict(c.execute(sa.text("SELECT id, kriterium_id FROM ub_eintraege")).fetchall())
        assert e == {1: 7, 2: krit["Impulsgebung"], 3: krit["Impulsgebung"]}
        assert c.execute(sa.text(
            "SELECT count(*) FROM ub_eintraege WHERE schwerpunkt_id IS NOT NULL")).scalar() == 0
    eng.dispose()
