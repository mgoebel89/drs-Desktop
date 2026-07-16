"""Vikunja-Client: Aufgaben aus EINEM fest konfigurierten Projekt.

Anders als in der Gemeindeverwaltung gibt es hier bewusst keine Projekt-
Auswahl im Alltag: Der Lehrer legt in seinem Profil einmal URL, API-Token
und die Projekt-ID fest; alle Aufgaben leben in diesem einen Projekt.

- Konfiguration pro Nutzer, AES-GCM-verschlüsselt (wie die Untis-Creds):
  JSON {url, token, project_id} in `users.vikunja_cfg_enc`.
- Der Token verlässt den Server nie — das Frontend spricht nur mit unseren
  eigenen Endpoints, die hierher proxyen.
- Vikunja liefert unbelegte Datumsfelder als "0001-01-01T00:00:00Z" → None.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.crypto import decrypt_secret, encrypt_secret
from app.models import User

log = logging.getLogger(__name__)

_TIMEOUT = 12.0
_MAX_PAGES = 10  # Sicherheitsdeckel beim Durchblättern
BERLIN = ZoneInfo("Europe/Berlin")

PRIORITY_LABELS = {
    0: "", 1: "Niedrig", 2: "Mittel", 3: "Hoch", 4: "Dringend", 5: "DRINGEND!",
}


class VikunjaError(Exception):
    """Fehler beim Sprechen mit Vikunja. `status` ist der HTTP-Code, den wir
    an den Browser weiterreichen (502 = Instanz nicht erreichbar)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class VikunjaConfig:
    url: str = ""          # Basis-URL ohne /api/v1, z. B. http://192.168.2.40:3456
    token: str = ""        # API-Token (Vikunja: Einstellungen → API-Tokens)
    project_id: int = 0    # das EINE Projekt, aus dem gearbeitet wird


# ── Konfiguration ────────────────────────────────────────────────────────

def load_config(user: User) -> VikunjaConfig | None:
    if not user.vikunja_cfg_enc:
        return None
    try:
        raw = json.loads(decrypt_secret(user.vikunja_cfg_enc))
    except Exception:
        log.warning("Vikunja-Konfiguration von %s nicht lesbar", user.username)
        return None
    return VikunjaConfig(
        url=str(raw.get("url", "")).rstrip("/"),
        token=str(raw.get("token", "")),
        project_id=int(raw.get("project_id") or 0),
    )


def save_config(user: User, cfg: VikunjaConfig) -> None:
    user.vikunja_cfg_enc = encrypt_secret(json.dumps({
        "url": cfg.url.rstrip("/"),
        "token": cfg.token,
        "project_id": cfg.project_id,
    }))


def clear_config(user: User) -> None:
    user.vikunja_cfg_enc = None


def is_configured(user: User) -> bool:
    cfg = load_config(user)
    return bool(cfg and cfg.url and cfg.token and cfg.project_id)


# ── HTTP ─────────────────────────────────────────────────────────────────

def _require_cfg(user: User, need_project: bool = True) -> VikunjaConfig:
    cfg = load_config(user)
    if not cfg or not cfg.url or not cfg.token:
        raise VikunjaError(
            "Vikunja ist nicht konfiguriert (URL und Token im Profil hinterlegen).", 503)
    if need_project and not cfg.project_id:
        raise VikunjaError(
            "Kein Vikunja-Projekt gewählt (im Profil festlegen).", 503)
    return cfg


def _call(cfg: VikunjaConfig, method: str, path: str,
          params: dict | None = None, body: dict | None = None) -> tuple:
    """Ein JSON-Request gegen Vikunja. Liefert (data, headers)."""
    headers = {"Authorization": f"Bearer {cfg.token}", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.request(
                method, f"{cfg.url}{path}",
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                json=body, headers=headers,
            )
    except httpx.TimeoutException:
        raise VikunjaError("Vikunja: Zeitüberschreitung.", 504)
    except httpx.HTTPError as e:
        raise VikunjaError(f"Vikunja nicht erreichbar: {e}", 502)

    if resp.status_code == 401:
        raise VikunjaError("Vikunja: Token ungültig oder abgelaufen.", 401)
    if resp.status_code >= 400:
        raise VikunjaError(
            f"Vikunja {resp.status_code}: {resp.text[:200]}", resp.status_code)
    if resp.status_code == 204 or not resp.content:
        return None, resp.headers
    try:
        return resp.json(), resp.headers
    except ValueError:
        raise VikunjaError("Vikunja lieferte kein JSON.", 502)


def _clean_date(v) -> str | None:
    """Vikunjas Null-Datum ("0001-…") → None."""
    if not v or not isinstance(v, str) or v.startswith("0001-"):
        return None
    return v


def _normalize(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "title": t.get("title") or "(ohne Titel)",
        "done": bool(t.get("done")),
        "due_date": _clean_date(t.get("due_date")),
        "priority": t.get("priority") if isinstance(t.get("priority"), int) else 0,
        "description": t.get("description") or "",
        "identifier": t.get("identifier") or "",
        "labels": [
            {"id": lb.get("id"), "title": lb.get("title", ""),
             "hex_color": lb.get("hex_color", "")}
            for lb in (t.get("labels") or []) if isinstance(lb, dict)
        ],
    }


def _to_vikunja_datetime(value: str) -> str:
    """'YYYY-MM-DD' oder 'YYYY-MM-DDTHH:MM' (lokale Eingabe des Lehrers) →
    ISO-8601 in UTC. Leere Eingabe = keine Fälligkeit → Vikunjas Null-Datum.

    Die Eingabe ist Wandzeit in Europe/Berlin; wir hängen die Zeitzone an und
    lassen die Umrechnung nach UTC den echten Zeitpunkt bestimmen."""
    v = (value or "").strip()
    if not v:
        return "0001-01-01T00:00:00Z"
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(v, fmt)
        except ValueError:
            continue
        utc = naive.replace(tzinfo=BERLIN).astimezone(timezone.utc)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    raise VikunjaError("Ungültiges Datum.", 400)


# ── Operationen ──────────────────────────────────────────────────────────

def list_open_tasks(user: User) -> list[dict]:
    """Offene Aufgaben des konfigurierten Projekts, fällige zuerst.
    Aufgaben ohne Fälligkeit sortiert Vikunja ans Ende (Null-Datum)."""
    cfg = _require_cfg(user)
    tasks: list[dict] = []
    page, total_pages = 1, 1
    while page <= total_pages and page <= _MAX_PAGES:
        data, headers = _call(cfg, "GET", f"/api/v1/projects/{cfg.project_id}/tasks", params={
            "filter": "done = false",
            "sort_by": "due_date",
            "order_by": "asc",
            "page": page,
        })
        for t in (data or []):
            if isinstance(t, dict) and not t.get("done"):
                tasks.append(_normalize(t))
        try:
            total_pages = int(headers.get("x-pagination-total-pages") or 1)
        except ValueError:
            total_pages = 1
        page += 1

    # Fällige zuerst, undatierte ans Ende — Vikunjas Null-Datum sortiert sonst
    # nach vorn.
    tasks.sort(key=lambda t: (t["due_date"] is None, t["due_date"] or ""))
    return tasks


def list_projects(user: User) -> list[dict]:
    """Projekte zur Auswahl im Profil. Pseudo-Projekte (id ≤ 0) fliegen raus."""
    cfg = _require_cfg(user, need_project=False)
    data, _ = _call(cfg, "GET", "/api/v1/projects")
    return [
        {"id": p["id"], "title": p.get("title") or f"Projekt {p['id']}"}
        for p in (data or [])
        if isinstance(p, dict) and isinstance(p.get("id"), int) and p["id"] > 0
    ]


def create_task(user: User, title: str, due_date: str = "",
                priority: int = 0, description: str = "",
                bucket_id: int | None = None,
                label_ids: list[int] | None = None) -> dict:
    """Aufgabe anlegen. Vikunja nimmt beim Anlegen weder Bucket noch Labels
    entgegen — beides wird danach nachgezogen (Bucket per Move-Endpoint, Labels
    einzeln). Ohne `bucket_id` landet die Aufgabe in Vikunjas Standard-Bucket."""
    cfg = _require_cfg(user)
    title = (title or "").strip()
    if not title:
        raise VikunjaError("Titel fehlt.", 400)
    body: dict = {"title": title[:250]}
    if due_date.strip():
        body["due_date"] = _to_vikunja_datetime(due_date)
    if priority:
        body["priority"] = max(0, min(5, int(priority)))
    if description.strip():
        body["description"] = description.strip()
    data, _ = _call(cfg, "PUT", f"/api/v1/projects/{cfg.project_id}/tasks", body=body)
    task = _normalize(data or {})
    task_id = task.get("id")
    if not task_id:
        return task

    if bucket_id:
        move_task(user, int(bucket_id), int(task_id))
    for lid in (label_ids or []):
        add_label(user, int(task_id), int(lid))
    if label_ids:
        # Labels stecken nicht in der Anlege-Antwort — einmal nachladen, damit
        # die frisch eingefügte Karte im Board vollständig ist.
        raw, _ = _call(cfg, "GET", f"/api/v1/tasks/{task_id}")
        if raw:
            task = _normalize(raw)
    return task


def set_done(user: User, task_id: int, done: bool = True) -> dict:
    """Vikunjas Task-Update ersetzt das ganze Modell — darum erst den Roh-Task
    laden, `done` setzen und alles zurückschreiben, sonst würden nicht
    mitgesendete Felder geleert."""
    cfg = _require_cfg(user, need_project=False)
    raw, _ = _call(cfg, "GET", f"/api/v1/tasks/{task_id}")
    if not raw:
        raise VikunjaError("Aufgabe nicht gefunden.", 404)
    raw["done"] = bool(done)
    data, _ = _call(cfg, "POST", f"/api/v1/tasks/{task_id}", body=raw)
    return _normalize(data or raw)


def delete_task(user: User, task_id: int) -> None:
    cfg = _require_cfg(user, need_project=False)
    _call(cfg, "DELETE", f"/api/v1/tasks/{task_id}")


def update_task(user: User, task_id: int, *, title: str | None = None,
                due_date: str | None = None, priority: int | None = None,
                description: str | None = None) -> dict:
    """Felder einer Aufgabe ändern. Read-modify-write wie `set_done`: Vikunjas
    Task-Update ersetzt das ganze Modell, darum erst laden und nur die
    übergebenen Felder überschreiben. `None` = Feld unverändert lassen."""
    cfg = _require_cfg(user, need_project=False)
    raw, _ = _call(cfg, "GET", f"/api/v1/tasks/{task_id}")
    if not raw:
        raise VikunjaError("Aufgabe nicht gefunden.", 404)
    if title is not None:
        t = title.strip()
        if not t:
            raise VikunjaError("Titel fehlt.", 400)
        raw["title"] = t[:250]
    if description is not None:
        raw["description"] = description
    if priority is not None:
        raw["priority"] = max(0, min(5, int(priority)))
    if due_date is not None:
        raw["due_date"] = _to_vikunja_datetime(due_date)  # "" → Null-Datum
    data, _ = _call(cfg, "POST", f"/api/v1/tasks/{task_id}", body=raw)
    return _normalize(data or raw)


# ── Kanban-Board (Views-API ab Vikunja 0.22) ─────────────────────────────

# Die View-ID ändert sich praktisch nie, wird aber bei jedem Board-Aufruf und
# jedem Verschieben gebraucht. Prozessweiter Cache je (Instanz, Projekt); wird
# verworfen, sobald ein Aufruf damit ins Leere läuft.
_view_cache: dict[tuple[str, int], int] = {}


def get_kanban_view_id(cfg: VikunjaConfig, *, refresh: bool = False) -> int:
    """Die Kanban-View des Projekts finden. Seit 0.22 hängen Buckets an einer
    View, nicht mehr direkt am Projekt. `view_kind` kann als String ('kanban')
    oder als Enum-Index (3) kommen — beides akzeptieren."""
    key = (cfg.url, cfg.project_id)
    if not refresh and key in _view_cache:
        return _view_cache[key]
    data, _ = _call(cfg, "GET", f"/api/v1/projects/{cfg.project_id}/views")
    for v in (data or []):
        if not isinstance(v, dict):
            continue
        kind = v.get("view_kind")
        if str(kind).lower() == "kanban" or kind == 3:
            _view_cache[key] = int(v["id"])
            return _view_cache[key]
    raise VikunjaError("Keine Kanban-Ansicht im Projekt gefunden.", 502)


def _looks_like_bucket(item: dict) -> bool:
    """Bucket oder Task? Beide haben `title`, aber nur der Bucket trägt eine
    Aufgabenliste bzw. den Bezug zur View."""
    return "tasks" in item or "project_view_id" in item or "limit" in item


def _fetch_buckets(cfg: VikunjaConfig, view_id: int) -> list[dict]:
    """Die Kanban-Spalten samt Aufgaben holen.

    **Nicht** über `…/views/{view}/buckets` — dieser Endpoint liefert nur die
    Spalten-Metadaten, seine `tasks` bleiben leer (genau daran hing das Board
    mit lauter 0-Spalten). Vikunja gibt die Aufgaben über den TASKS-Endpoint
    der View aus: Ist die View vom Typ Kanban, antwortet er mit den Buckets
    *inklusive* ihrer Aufgaben statt mit einer flachen Liste.
    """
    data, _ = _call(
        cfg, "GET",
        f"/api/v1/projects/{cfg.project_id}/views/{view_id}/tasks",
        params={"per_page": 100})   # Deckel je Spalte
    items = [i for i in (data or []) if isinstance(i, dict)]
    if items and any(_looks_like_bucket(i) for i in items):
        return items
    # Ältere Instanzen (ohne Bucket-Konfiguration an der View) antworten hier
    # flach — dann trägt der Buckets-Endpoint die Aufgaben noch selbst.
    data, _ = _call(
        cfg, "GET", f"/api/v1/projects/{cfg.project_id}/views/{view_id}/buckets")
    return [b for b in (data or []) if isinstance(b, dict)]


def list_board(user: User) -> dict:
    """Die Spalten (Buckets) der Kanban-View samt ihrer Aufgaben."""
    cfg = _require_cfg(user)
    view_id = get_kanban_view_id(cfg)
    buckets = []
    for b in _fetch_buckets(cfg, view_id):
        tasks = [_normalize(t) for t in (b.get("tasks") or [])
                 if isinstance(t, dict)]
        buckets.append({
            "id": b.get("id"),
            "title": b.get("title") or "(ohne Titel)",
            "limit": b.get("limit") or 0,
            "is_done_bucket": bool(b.get("is_done_bucket")),
            "tasks": tasks,
        })
    return {"view_id": view_id, "buckets": buckets}


def move_task(user: User, bucket_id: int, task_id: int,
              position: float | None = None) -> None:
    """Aufgabe in einen anderen Bucket schieben.

    Ab Vikunja 0.24 ignoriert das Task-Update ein `bucket_id` — Verschieben
    läuft ausschließlich über diesen dedizierten Endpoint. Ins „Erledigt"-Bucket
    zu schieben hakt die Aufgabe serverseitig automatisch ab (und umgekehrt)."""
    cfg = _require_cfg(user)

    def _post(view_id: int) -> None:
        body: dict = {"task_id": int(task_id), "bucket_id": int(bucket_id),
                      "project_view_id": view_id}
        if position is not None:
            body["position"] = position
        _call(cfg, "POST",
              f"/api/v1/projects/{cfg.project_id}/views/{view_id}"
              f"/buckets/{bucket_id}/tasks", body=body)

    try:
        _post(get_kanban_view_id(cfg))
    except VikunjaError as e:
        if e.status != 404:
            raise
        # Gecachte View-ID war veraltet (View neu gebaut) — einmal frisch holen.
        _post(get_kanban_view_id(cfg, refresh=True))


# ── Labels ───────────────────────────────────────────────────────────────

def list_labels(user: User) -> list[dict]:
    """Alle Labels des Nutzers (für die Auswahl in der Edit-Karte)."""
    cfg = _require_cfg(user, need_project=False)
    data, _ = _call(cfg, "GET", "/api/v1/labels")
    return [
        {"id": lb["id"], "title": lb.get("title", ""),
         "hex_color": lb.get("hex_color", "")}
        for lb in (data or []) if isinstance(lb, dict) and lb.get("id")
    ]


KLASSE_LABEL_PREFIX = "Klasse: "
KLASSE_LABEL_COLOR = "1a4f7a"   # DRS-Blau, damit Klassen-Labels sofort auffallen


def klasse_label_title(name: str) -> str:
    return f"{KLASSE_LABEL_PREFIX}{(name or '').strip()}"


def ensure_label(user: User, title: str, hex_color: str = "") -> dict:
    """Label mit diesem Titel holen — oder anlegen, wenn es es noch nicht gibt.

    So wird die Lerngruppe einer Aufgabe zu einem ganz normalen Vikunja-Label:
    auch in Vikunja selbst sichtbar und filterbar, ohne eigene Tabelle bei uns.
    Der Abgleich läuft über den Titel (ohne Groß-/Kleinschreibung), weil das
    Label die einzige Wahrheit ist."""
    cfg = _require_cfg(user, need_project=False)
    wanted = (title or "").strip()
    if not wanted:
        raise VikunjaError("Label ohne Titel.", 400)
    for lb in list_labels(user):
        if lb["title"].strip().lower() == wanted.lower():
            return lb
    body = {"title": wanted[:250]}
    if hex_color:
        body["hex_color"] = hex_color
    data, _ = _call(cfg, "PUT", "/api/v1/labels", body=body)
    data = data or {}
    return {"id": data.get("id"), "title": data.get("title") or wanted,
            "hex_color": data.get("hex_color") or hex_color}


def add_label(user: User, task_id: int, label_id: int) -> None:
    cfg = _require_cfg(user, need_project=False)
    _call(cfg, "PUT", f"/api/v1/tasks/{task_id}/labels",
          body={"label_id": int(label_id)})


def remove_label(user: User, task_id: int, label_id: int) -> None:
    cfg = _require_cfg(user, need_project=False)
    _call(cfg, "DELETE", f"/api/v1/tasks/{task_id}/labels/{label_id}")


def test_connection(user: User) -> tuple[bool, str]:
    """Für den „Verbindung testen"-Knopf im Profil."""
    try:
        cfg = _require_cfg(user, need_project=False)
        projects = list_projects(user)
        if not cfg.project_id:
            return True, f"Verbunden — {len(projects)} Projekte gefunden. Jetzt Projekt wählen."
        hit = next((p for p in projects if p["id"] == cfg.project_id), None)
        if not hit:
            return False, f"Verbunden, aber Projekt {cfg.project_id} ist nicht (mehr) sichtbar."
        offen = len(list_open_tasks(user))
        titel = hit["title"]
        return True, f"Verbunden mit Projekt {titel} — {offen} offene Aufgaben."
    except VikunjaError as e:
        return False, str(e)
    except Exception as e:  # pragma: no cover
        return False, f"Unerwarteter Fehler: {e}"
