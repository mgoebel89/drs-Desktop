"""Der Upload-Weg gegen ein nachgebautes Paperless.

Gemockt wird nur der HTTP-Transport (httpx), nicht unser Client — so läuft der
komplette eigene Code echt durch: Formular-Kodierung, Antwort-Auswertung,
Task-Polling. Der Mock bildet Paperless dort nach, wo es eigenwillig ist:
`post_document` antwortet mit der **nackten Task-UUID als JSON-String**, nicht
mit einem Objekt.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import models as m
from app.crypto import encrypt_secret
from app.services import paperless_client as pl


@pytest.fixture()
def user(db):
    u = m.User(username="p", password_hash="x")
    u.paperless_cfg_enc = encrypt_secret(json.dumps({
        "url": "http://paperless.test",
        "token": "geheim",
        "view_tag_ids": [3, 4],
        "upload_tag_id": 7,
        "storage_path_id": 2,
    }))
    db.add(u)
    db.flush()
    return u


class Aufzeichnung:
    """Merkt sich, was rausging — darüber prüfen wir die Formularfelder."""

    def __init__(self):
        self.requests: list[httpx.Request] = []


@pytest.fixture()
def paperless(monkeypatch):
    aufz = Aufzeichnung()

    def handler(request: httpx.Request) -> httpx.Response:
        aufz.requests.append(request)
        pfad = request.url.path
        if pfad == "/api/documents/post_document/":
            # Genau so antwortet Paperless: ein JSON-String, kein Objekt.
            return httpx.Response(200, json="d9d1b6a0-1111-2222-3333-444455556666")
        if pfad == "/api/tasks/":
            return httpx.Response(200, json=[{
                "status": "SUCCESS", "related_document": 42, "result": "",
            }])
        if pfad == "/api/documents/":
            return httpx.Response(200, json={"count": 0, "next": None, "results": []})
        return httpx.Response(404, json={"detail": "nix"})

    transport = httpx.MockTransport(handler)
    echter_client = httpx.Client

    def client_mit_mock(*a, **kw):
        kw["transport"] = transport
        return echter_client(*a, **kw)

    monkeypatch.setattr(pl.httpx, "Client", client_mit_mock)
    return aufz


def _formularfelder(request: httpx.Request) -> dict[str, list[str]]:
    """Multipart-Body grob zerlegen: Feldname → alle gesendeten Werte."""
    roh = request.content.decode("utf-8", "replace")
    felder: dict[str, list[str]] = {}
    for teil in roh.split("--" + request.headers["content-type"].split("boundary=")[1]):
        if 'name="' not in teil:
            continue
        name = teil.split('name="', 1)[1].split('"', 1)[0]
        if 'filename="' in teil:
            felder.setdefault(name, []).append("<datei>")
            continue
        wert = teil.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0] if "\r\n\r\n" in teil else ""
        felder.setdefault(name, []).append(wert)
    return felder


def test_upload_liefert_die_task_id(user, paperless):
    """Der Fehler, der den Upload zerlegt hat: Die Antwort ist ein JSON-String.
    Wer nur Objekte erwartet, verliert die ID und pollt danach ins Leere."""
    task_id = pl.upload_document(
        user, filename="rechnung.pdf", content=b"%PDF-1.4 test",
        mimetype="application/pdf", title="Rechnung Conrad")
    assert task_id == "d9d1b6a0-1111-2222-3333-444455556666"


def test_upload_setzt_tag_und_speicherpfad(user, paperless):
    """Der Kern der Anpassung: Jeder Upload bekommt den eingestellten
    Upload-Tag und den Speicherpfad — zusätzlich gewählte Tags kommen dazu."""
    pl.upload_document(
        user, filename="angebot.pdf", content=b"%PDF-1.4",
        title="Angebot", extra_tag_ids=[3])

    felder = _formularfelder(paperless.requests[0])
    assert felder["title"] == ["Angebot"]
    assert felder["storage_path"] == ["2"]
    assert felder["document"] == ["<datei>"]
    # Mehrere Tags müssen als mehrere Formularfelder rausgehen.
    assert sorted(felder["tags"]) == ["3", "7"]


def test_upload_ohne_zusatztags_setzt_nur_den_upload_tag(user, paperless):
    pl.upload_document(user, filename="a.pdf", content=b"x", title="A")
    assert _formularfelder(paperless.requests[0])["tags"] == ["7"]


def test_leere_felder_gehen_nicht_mit(user, paperless):
    """Ein leeres `created` würde Paperless als ungültiges Datum ablehnen."""
    pl.upload_document(user, filename="a.pdf", content=b"x", title="A", created="")
    felder = _formularfelder(paperless.requests[0])
    assert "created" not in felder
    assert "correspondent" not in felder


def test_task_polling_meldet_das_fertige_dokument(user, paperless):
    d = pl.get_task(user, "d9d1b6a0-1111-2222-3333-444455556666")
    assert d["status"] == "SUCCESS"
    assert d["document_id"] == 42


def test_fehler_von_paperless_wird_lesbar_weitergereicht(user, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Unsupported file type")

    transport = httpx.MockTransport(handler)
    echter = httpx.Client
    monkeypatch.setattr(pl.httpx, "Client",
                        lambda *a, **kw: echter(*a, **{**kw, "transport": transport}))

    with pytest.raises(pl.PaperlessError) as ex:
        pl.upload_document(user, filename="a.exe", content=b"x", title="A")
    assert "Unsupported file type" in str(ex.value)
