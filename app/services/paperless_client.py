"""Paperless-ngx als Dokumentenspeicher — Backend-Proxy.

Vorbild ist das Dokumente-Modul der Gemeindeverwaltung (`backend/paperless.js`),
hier für FastAPI neu geschrieben. Der API-Token bleibt im Server; der Browser
spricht ausschließlich mit unseren eigenen `/api/dokumente/*`-Endpoints.

Der Unterschied zur Gemeindeverwaltung — und der Grund für dieses Modul:
Paperless ist ein gemeinsamer Speicher für alles Mögliche. Damit hier nur die
schulischen Dokumente auftauchen, filtert die Ansicht auf **Anzeige-Tags**
(ODER-Verknüpfung: eines der Tags reicht), und jeder Upload aus dieser App
bekommt automatisch den **Upload-Tag** und den eingestellten **Speicherpfad**.
Beides wird pro Nutzer im Profil aus den in Paperless vorhandenen Tags bzw.
Pfaden ausgewählt — die App legt dort selbst nichts an.

Konfiguration wie bei Vikunja: AES-GCM-verschlüsseltes JSON in
`users.paperless_cfg_enc`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import httpx

from app.crypto import decrypt_secret, encrypt_secret
from app.models import User

log = logging.getLogger(__name__)

_TIMEOUT = 20.0        # Uploads dauern länger als ein Listenabruf
_MAX_PAGES = 20        # Sicherheitsdeckel beim Durchblättern von Stammlisten
PAGE_SIZE = 24

# Sortierungen, die die Oberfläche anbietet (Wert = Paperless-`ordering`).
ORDERINGS = {
    "-created": "Neueste zuerst",
    "created": "Älteste zuerst",
    "title": "Titel A–Z",
    "-added": "Zuletzt hinzugefügt",
}


class PaperlessError(Exception):
    """Fehler beim Sprechen mit Paperless. `status` ist der HTTP-Code, den wir
    an den Browser weiterreichen (502 = Instanz nicht erreichbar)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class PaperlessConfig:
    url: str = ""                                    # Basis-URL ohne /api
    token: str = ""                                  # Paperless: API-Token
    view_tag_ids: list[int] = field(default_factory=list)   # Anzeigefilter (ODER)
    upload_tag_id: int = 0                           # bekommt jeder Upload
    storage_path_id: int = 0                         # Ablagepfad für Uploads


# ── Konfiguration ────────────────────────────────────────────────────────

def _int_list(raw) -> list[int]:
    out: list[int] = []
    for v in (raw or []):
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def load_config(user: User) -> PaperlessConfig | None:
    if not user.paperless_cfg_enc:
        return None
    try:
        raw = json.loads(decrypt_secret(user.paperless_cfg_enc))
    except Exception:
        log.warning("Paperless-Konfiguration von %s nicht lesbar", user.username)
        return None
    return PaperlessConfig(
        url=str(raw.get("url", "")).rstrip("/"),
        token=str(raw.get("token", "")),
        view_tag_ids=_int_list(raw.get("view_tag_ids")),
        upload_tag_id=int(raw.get("upload_tag_id") or 0),
        storage_path_id=int(raw.get("storage_path_id") or 0),
    )


def save_config(user: User, cfg: PaperlessConfig) -> None:
    user.paperless_cfg_enc = encrypt_secret(json.dumps({
        "url": cfg.url.rstrip("/"),
        "token": cfg.token,
        "view_tag_ids": _int_list(cfg.view_tag_ids),
        "upload_tag_id": int(cfg.upload_tag_id or 0),
        "storage_path_id": int(cfg.storage_path_id or 0),
    }))


def clear_config(user: User) -> None:
    user.paperless_cfg_enc = None


def is_configured(user: User) -> bool:
    cfg = load_config(user)
    return bool(cfg and cfg.url and cfg.token)


# ── HTTP ─────────────────────────────────────────────────────────────────

def _require_cfg(user: User) -> PaperlessConfig:
    cfg = load_config(user)
    if not cfg or not cfg.url or not cfg.token:
        raise PaperlessError(
            "Paperless ist nicht eingerichtet — im Profil URL und Token "
            "hinterlegen.", status=400)
    return cfg


def _headers(cfg: PaperlessConfig) -> dict[str, str]:
    return {"Authorization": f"Token {cfg.token}", "Accept": "application/json"}


def _call(cfg: PaperlessConfig, method: str, path: str, *,
          params: dict | None = None, json_body: dict | None = None,
          files=None, data=None) -> dict:
    """Ein Aufruf gegen Paperless. Antworten ohne Body (204) werden zu {}."""
    url = f"{cfg.url}{path}"
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = client.request(method, url, headers=_headers(cfg),
                               params=params, json=json_body,
                               files=files, data=data)
    except httpx.HTTPError as e:
        raise PaperlessError(f"Paperless nicht erreichbar: {e}") from e

    if r.status_code == 401 or r.status_code == 403:
        raise PaperlessError("Paperless lehnt den Token ab (401/403).", status=401)
    if r.status_code == 404:
        raise PaperlessError("In Paperless nicht gefunden.", status=404)
    if r.status_code >= 400:
        raise PaperlessError(
            f"Paperless meldet {r.status_code}: {r.text[:200]}", status=502)
    if not r.content:
        return {}
    try:
        out = r.json()
    except ValueError:
        # post_document liefert die Task-UUID als nackten String in Anführungszeichen
        return {"raw": r.text.strip().strip('"')}
    return out if isinstance(out, dict) else {"results": out}


def _fetch_all(cfg: PaperlessConfig, path: str) -> list[dict]:
    """Eine vollständige Stammliste (Tags, Pfade, …) über alle Seiten."""
    out: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        d = _call(cfg, "GET", path, params={"page": page, "page_size": 100})
        out.extend(d.get("results") or [])
        if not d.get("next"):
            break
        page += 1
    return out


# ── Stammlisten (für Filter und Upload-Dialog) ───────────────────────────

def _slim(items: list[dict], keys: list[str]) -> list[dict]:
    return [{k: it.get(k) for k in keys} for it in items]


def list_tags(user: User) -> list[dict]:
    cfg = _require_cfg(user)
    return _slim(_fetch_all(cfg, "/api/tags/"), ["id", "name", "color"])


def list_storage_paths(user: User) -> list[dict]:
    cfg = _require_cfg(user)
    return _slim(_fetch_all(cfg, "/api/storage_paths/"), ["id", "name", "path"])


def list_correspondents(user: User) -> list[dict]:
    cfg = _require_cfg(user)
    return _slim(_fetch_all(cfg, "/api/correspondents/"), ["id", "name"])


def list_document_types(user: User) -> list[dict]:
    cfg = _require_cfg(user)
    return _slim(_fetch_all(cfg, "/api/document_types/"), ["id", "name"])


def stammlisten(user: User) -> dict:
    """Alles, was der Upload-Dialog und die Filterleiste brauchen — in einem
    Aufruf, damit das Frontend nicht vier Anfragen hintereinander hängt."""
    return {
        "tags": list_tags(user),
        "storage_paths": list_storage_paths(user),
        "correspondents": list_correspondents(user),
        "document_types": list_document_types(user),
    }


# ── Dokumente ────────────────────────────────────────────────────────────

def search_documents(user: User, *, query: str = "", tag_ids: list[int] | None = None,
                     correspondent: int = 0, document_type: int = 0,
                     ordering: str = "-created", page: int = 1) -> dict:
    """Dokumentenliste, immer eingeschränkt auf die Anzeige-Tags.

    `tags__id__in` ist die ODER-Verknüpfung (mindestens eines der Tags) —
    bewusst nicht `tags__id__all`, das wäre ein UND. Wählt der Nutzer in der
    Filterleiste zusätzlich Tags, schneiden wir sie mit den Anzeige-Tags,
    damit der Filter nie mehr zeigt als die Einstellung erlaubt.
    """
    cfg = _require_cfg(user)
    wanted = _int_list(tag_ids)
    if cfg.view_tag_ids:
        wanted = [t for t in wanted if t in cfg.view_tag_ids] or cfg.view_tag_ids

    params: dict = {
        "page": max(1, int(page or 1)),
        "page_size": PAGE_SIZE,
        "ordering": ordering if ordering in ORDERINGS else "-created",
    }
    if wanted:
        params["tags__id__in"] = ",".join(str(t) for t in wanted)
    if query.strip():
        params["title_content"] = query.strip()
    if correspondent:
        params["correspondent__id"] = int(correspondent)
    if document_type:
        params["document_type__id"] = int(document_type)

    d = _call(cfg, "GET", "/api/documents/", params=params)
    return {
        "count": d.get("count") or 0,
        "has_next": bool(d.get("next")),
        "results": [_slim_document(x) for x in (d.get("results") or [])],
    }


def _slim_document(doc: dict) -> dict:
    """Nur die Felder, die die Oberfläche zeigt — der Rest bleibt im Server."""
    return {
        "id": doc.get("id"),
        "title": doc.get("title") or "",
        "created": (doc.get("created_date") or doc.get("created") or "")[:10],
        "added": (doc.get("added") or "")[:10],
        "correspondent": doc.get("correspondent"),
        "document_type": doc.get("document_type"),
        "storage_path": doc.get("storage_path"),
        "tags": doc.get("tags") or [],
        "notes": doc.get("notes") or [],
        "archive_serial_number": doc.get("archive_serial_number"),
    }


def get_document(user: User, doc_id: int) -> dict:
    cfg = _require_cfg(user)
    return _slim_document(_call(cfg, "GET", f"/api/documents/{int(doc_id)}/"))


def update_document(user: User, doc_id: int, patch: dict) -> dict:
    """Metadaten ändern. Nur bekannte Felder werden durchgereicht."""
    cfg = _require_cfg(user)
    allowed = ("title", "created_date", "correspondent", "document_type",
               "storage_path", "tags", "archive_serial_number")
    body = {k: v for k, v in (patch or {}).items() if k in allowed}
    if not body:
        return get_document(user, doc_id)
    return _slim_document(
        _call(cfg, "PATCH", f"/api/documents/{int(doc_id)}/", json_body=body))


def fetch_file(user: User, doc_id: int, kind: str = "preview") -> tuple[bytes, str]:
    """Vorschau, Thumbnail oder Original als Bytes + Content-Type.

    Läuft bewusst über den Server: so braucht der Browser weder den Token noch
    eine direkte Verbindung zu Paperless.
    """
    cfg = _require_cfg(user)
    suffix = {"preview": "preview", "thumb": "thumb",
              "download": "download"}.get(kind, "preview")
    url = f"{cfg.url}/api/documents/{int(doc_id)}/{suffix}/"
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, headers={"Authorization": f"Token {cfg.token}"})
    except httpx.HTTPError as e:
        raise PaperlessError(f"Paperless nicht erreichbar: {e}") from e
    if r.status_code >= 400:
        raise PaperlessError(f"Datei nicht abrufbar ({r.status_code}).",
                             status=404 if r.status_code == 404 else 502)
    return r.content, r.headers.get("content-type", "application/octet-stream")


# ── Upload ───────────────────────────────────────────────────────────────

def upload_document(user: User, *, filename: str, content: bytes,
                    mimetype: str = "application/pdf", title: str = "",
                    created: str = "", correspondent: int = 0,
                    document_type: int = 0,
                    extra_tag_ids: list[int] | None = None) -> str:
    """Legt ein Dokument in Paperless ab und liefert die Task-UUID.

    Upload-Tag und Speicherpfad aus der Konfiguration werden IMMER gesetzt —
    genau dafür gibt es die Einstellung. Paperless verarbeitet den Upload
    asynchron (OCR); die Dokument-ID gibt es erst über `get_task`.
    """
    cfg = _require_cfg(user)

    tags = _int_list(extra_tag_ids)
    if cfg.upload_tag_id and cfg.upload_tag_id not in tags:
        tags.append(cfg.upload_tag_id)

    data: list[tuple[str, str]] = []
    if title.strip():
        data.append(("title", title.strip()))
    if created.strip():
        data.append(("created", created.strip()))
    if correspondent:
        data.append(("correspondent", str(int(correspondent))))
    if document_type:
        data.append(("document_type", str(int(document_type))))
    if cfg.storage_path_id:
        data.append(("storage_path", str(cfg.storage_path_id)))
    # Mehrere Tags = das Feld mehrfach senden (so will es post_document).
    for t in tags:
        data.append(("tags", str(t)))

    d = _call(cfg, "POST", "/api/documents/post_document/",
              files={"document": (filename, content, mimetype)}, data=data)
    return str(d.get("raw") or d.get("task_id") or "")


def get_task(user: User, task_id: str) -> dict:
    """Status eines Upload-Tasks. Liefert {status, document_id, error}."""
    cfg = _require_cfg(user)
    d = _call(cfg, "GET", "/api/tasks/", params={"task_id": task_id})
    items = d.get("results") if isinstance(d.get("results"), list) else []
    if not items:
        return {"status": "PENDING", "document_id": None, "error": ""}
    t = items[0]
    return {
        "status": t.get("status") or "PENDING",
        "document_id": t.get("related_document"),
        "error": t.get("result") if t.get("status") == "FAILURE" else "",
    }


# ── Notizen ──────────────────────────────────────────────────────────────

def list_notes(user: User, doc_id: int) -> list[dict]:
    cfg = _require_cfg(user)
    d = _call(cfg, "GET", f"/api/documents/{int(doc_id)}/notes/")
    items = d.get("results") if isinstance(d.get("results"), list) else []
    return _slim(items, ["id", "note", "created"])


def add_note(user: User, doc_id: int, note: str) -> list[dict]:
    cfg = _require_cfg(user)
    _call(cfg, "POST", f"/api/documents/{int(doc_id)}/notes/",
          json_body={"note": note})
    return list_notes(user, doc_id)


def delete_note(user: User, doc_id: int, note_id: int) -> list[dict]:
    cfg = _require_cfg(user)
    # Paperless erwartet die Notiz-ID als Query-Parameter, nicht im Pfad.
    _call(cfg, "DELETE", f"/api/documents/{int(doc_id)}/notes/",
          params={"id": int(note_id)})
    return list_notes(user, doc_id)


# ── Verbindungstest fürs Profil ──────────────────────────────────────────

def test_connection(user: User) -> tuple[bool, str]:
    try:
        cfg = _require_cfg(user)
        d = _call(cfg, "GET", "/api/documents/", params={"page_size": 1})
        return True, f"Verbindung steht — {d.get('count') or 0} Dokumente sichtbar."
    except PaperlessError as e:
        return False, str(e)
