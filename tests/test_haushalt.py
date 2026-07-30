"""Haushalt: Geldumrechnung, Verbrauch, Restmittel und die Jahresgrenze.

Die wichtigste Regel steht im letzten Test: Mittel verfallen zum Jahresende.
Wenn ein Verbrauch je über die Jahresgrenze wanderte, zeigte die App Geld an,
das es nicht mehr gibt.
"""
from __future__ import annotations

import pytest

from app import models as m
from app.services import haushalt as hh
from app.services import vorgaenge as vg


@pytest.fixture()
def budget(db):
    user = m.User(username="h", password_hash="x")
    db.add(user)
    db.flush()

    verw = m.HhPosten(user_id=user.id, jahr=2026, art="verwaltung",
                      bezeichnung="Verbrauchsmaterial", betrag_cent=85_000)
    verm = m.HhPosten(user_id=user.id, jahr=2026, art="vermoegen",
                      bezeichnung="Prüfplatz", betrag_cent=1_200_000)
    alt = m.HhPosten(user_id=user.id, jahr=2025, art="verwaltung",
                     bezeichnung="Altjahr", betrag_cent=50_000)
    db.add_all([verw, verm, alt])
    db.flush()

    v = m.Vorgang(user_id=user.id, titel="Beschaffung", haushaltsjahr=2026)
    db.add(v)
    db.flush()
    return {"user": user, "v": v, "verw": verw, "verm": verm, "alt": alt}


def _kosten(db, vorgang, posten, cent):
    db.add(m.VorgangEintrag(vorgang_id=vorgang.id, typ="kosten", datum="2026-05-01",
                            betrag_cent=cent, hh_posten_id=posten.id,
                            payload_json="{}"))
    db.flush()


# ── Geld ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("eingabe,cent", [
    (249.90, 24990), ("249,90", 24990), ("1.234,56", 123456),
    ("1234.56", 123456), ("", 0), (None, 0), ("Unfug", 0), (0, 0),
])
def test_to_cent(eingabe, cent):
    assert hh.to_cent(eingabe) == cent


def test_summen_driften_nicht():
    """Der Grund für Cent statt Fließkomma: 3 × 0,10 € muss 0,30 € bleiben."""
    summe = sum(hh.to_cent("0,10") for _ in range(3))
    assert hh.to_euro(summe) == 0.30


def test_art_vorschlag_an_der_grenze():
    assert hh.art_fuer(hh.to_cent("999,99")) == "verwaltung"
    assert hh.art_fuer(hh.to_cent("1000,00")) == "vermoegen"


# ── Verbrauch und Restmittel ─────────────────────────────────────────────

def test_restmittel_nach_buchung(db, budget):
    _kosten(db, budget["v"], budget["verw"], 24_990)
    view = hh.posten_view(db, budget["user"], 2026)
    zeile = view["toepfe"]["verwaltung"]["posten"][0]
    assert zeile["budget"] == 850.0
    assert zeile["verbrauch"] == 249.9
    assert zeile["rest"] == 600.1
    assert zeile["ueberzogen"] is False


def test_ueberziehung_wird_erkannt(db, budget):
    _kosten(db, budget["v"], budget["verw"], 90_000)
    zeile = hh.posten_view(db, budget["user"], 2026)["toepfe"]["verwaltung"]["posten"][0]
    assert zeile["rest"] == -50.0
    assert zeile["ueberzogen"] is True


def test_angebot_mindert_die_restmittel_nicht(db, budget):
    """Ein Angebot trägt einen Preis, ist aber noch kein ausgegebenes Geld."""
    db.add(m.VorgangEintrag(vorgang_id=budget["v"].id, typ="angebot",
                            datum="2026-05-01", betrag_cent=1_150_000,
                            hh_posten_id=budget["verm"].id, payload_json="{}"))
    db.flush()
    zeile = hh.posten_view(db, budget["user"], 2026)["toepfe"]["vermoegen"]["posten"][0]
    assert zeile["verbrauch"] == 0.0
    assert zeile["rest"] == 12000.0


def test_toepfe_bleiben_getrennt(db, budget):
    _kosten(db, budget["v"], budget["verw"], 20_000)
    _kosten(db, budget["v"], budget["verm"], 500_000)
    toepfe = hh.posten_view(db, budget["user"], 2026)["toepfe"]
    assert toepfe["verwaltung"]["summe_verbrauch"] == 200.0
    assert toepfe["vermoegen"]["summe_verbrauch"] == 5000.0


def test_mittel_verfallen_zum_jahresende(db, budget):
    """Ein Posten von 2025 taucht in der Ansicht 2026 nicht auf — weder mit
    Budget noch mit Restmitteln. Es gibt keinen Übertrag."""
    _kosten(db, budget["v"], budget["alt"], 10_000)

    view2026 = hh.posten_view(db, budget["user"], 2026)
    namen2026 = [p["bezeichnung"] for p in view2026["toepfe"]["verwaltung"]["posten"]]
    assert "Altjahr" not in namen2026
    assert view2026["toepfe"]["verwaltung"]["summe_budget"] == 850.0

    view2025 = hh.posten_view(db, budget["user"], 2025)
    zeile = view2025["toepfe"]["verwaltung"]["posten"][0]
    assert zeile["bezeichnung"] == "Altjahr"
    assert zeile["rest"] == 400.0


# ── Entscheidungsmatrix ──────────────────────────────────────────────────

def test_matrix_gewichtet_und_empfiehlt():
    payload = {
        "kriterien": [{"id": "k1", "name": "Preis", "gewicht": 3},
                      {"id": "k2", "name": "Erweiterbarkeit", "gewicht": 2}],
        "teilnehmer": [
            {"id": "t1", "name": "A", "punkte": {"k1": 5, "k2": 2}},   # 15+4 = 19
            {"id": "t2", "name": "B", "punkte": {"k1": 2, "k2": 5}},   # 6+10 = 16
        ],
        "gewaehlt": "t2",
    }
    aus = vg.matrix_auswertung(payload)
    assert aus["punkte"] == {"t1": 19, "t2": 16}
    assert aus["empfehlung"] == "t1"          # rechnerisch vorn
    assert aus["gewaehlt"] == "t2"            # bewusst anders entschieden


def test_matrix_zaehlt_fehlende_punkte_als_null():
    payload = {
        "kriterien": [{"id": "k1", "name": "Preis", "gewicht": 4}],
        "teilnehmer": [{"id": "t1", "name": "A", "punkte": {}}],
    }
    assert vg.matrix_auswertung(payload)["punkte"] == {"t1": 0}


# ── Payload-Normalisierung ───────────────────────────────────────────────

def test_payload_nimmt_nur_bekannte_felder():
    p = vg.normalize_payload("notiz", {"text": "Hallo", "betrag": 999,
                                       "schadcode": "<script>"})
    assert p == {"text": "Hallo"}


def test_weiterleitung_verwirft_leere_empfaenger():
    p = vg.normalize_payload("weiterleitung", {
        "info": "Info",
        "empfaenger": [
            {"name": "Frau Weber", "weg": "email", "datum": "2026-07-30", "erledigt": True},
            {"name": "   ", "weg": "email"},
            {"name": "Herr Klein", "weg": "quatsch"},
        ],
    })
    assert [e["name"] for e in p["empfaenger"]] == ["Frau Weber", "Herr Klein"]
    # Unbekannter Weg fällt auf den Standard zurück, statt durchzurutschen.
    assert p["empfaenger"][1]["weg"] == "persoenlich"


def test_docs_nur_mit_numerischer_id():
    p = vg.normalize_payload("dokument", {
        "titel": "Angebote",
        "docs": [{"id": 7, "title": "Angebot A"}, {"id": "x", "title": "kaputt"}],
    })
    assert p["docs"] == [{"id": 7, "title": "Angebot A"}]
