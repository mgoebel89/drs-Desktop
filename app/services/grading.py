"""Notenskalen.

Zwei Typen: MSS-Noten (1 … 6 mit +/−, KEIN 1+) und MSS-Punkte (15 … 0).
Pro Stufe (label, min_pct, max_pct) — Grenzen inklusiv.

- **Built-in-Skalen** stehen immer zur Verfügung (Referenz "builtin:<key>").
- **Custom-Skalen** liegen in der DB-Tabelle grading_scales und werden
  über die Referenz "custom:<id>" angesprochen. Sie übernehmen die fixen
  Labels ihres Typs, erlauben aber editierbare Prozentgrenzen.

Referenz-Strings (in exams.grading_scale_key gespeichert):
  "builtin:mss_noten" | "builtin:mss_punkte" | "custom:<id>"
Bare Altwerte ("mss_noten"/"mss_punkte") werden als Built-in interpretiert.
"""
from __future__ import annotations

import json


# ── Typ-Definitionen: fixe Label-Leiter + Default-Grenzen ────────────────

# MSS-Noten: 1+ entfällt, Top-Note "1" reicht bis 100 %.
_MSS_NOTEN_DEFAULT = [
    ("1",  92, 100),
    ("1-", 88, 91),
    ("2+", 84, 87),
    ("2",  80, 83),
    ("2-", 76, 79),
    ("3+", 72, 75),
    ("3",  68, 71),
    ("3-", 64, 67),
    ("4+", 60, 63),
    ("4",  55, 59),
    ("4-", 50, 54),
    ("5+", 45, 49),
    ("5",  40, 44),
    ("5-", 33, 39),
    ("6",   0, 32),
]

_MSS_PUNKTE_DEFAULT = [
    ("15", 95, 100),
    ("14", 90, 94),
    ("13", 85, 89),
    ("12", 80, 84),
    ("11", 75, 79),
    ("10", 70, 74),
    ("9",  65, 69),
    ("8",  60, 64),
    ("7",  55, 59),
    ("6",  50, 54),
    ("5",  45, 49),
    ("4",  40, 44),
    ("3",  33, 39),
    ("2",  27, 32),
    ("1",  20, 26),
    ("0",   0, 19),
]

SCALE_TYPES: dict[str, dict] = {
    "mss_noten": {"label": "MSS Schulnoten", "default_stufen": _MSS_NOTEN_DEFAULT},
    "mss_punkte": {"label": "MSS Punkte", "default_stufen": _MSS_PUNKTE_DEFAULT},
}


# ── Built-in-Skalen ──────────────────────────────────────────────────────

BUILTINS: dict[str, dict] = {
    "mss_noten": {"label": "MSS Schulnoten (1 … 6)", "type": "mss_noten",
                  "stufen": _MSS_NOTEN_DEFAULT},
    "mss_punkte": {"label": "MSS Punkte (15 … 0)", "type": "mss_punkte",
                   "stufen": _MSS_PUNKTE_DEFAULT},
}

# Rückwärtskompatibler Alias (alte Aufrufer nutzen grading.SCALES)
SCALES = BUILTINS

DEFAULT_SCALE = "builtin:mss_noten"


# ── Typ-Helfer (für den Skalen-Editor) ───────────────────────────────────

def list_scale_types() -> list[tuple[str, str]]:
    return [(k, v["label"]) for k, v in SCALE_TYPES.items()]


def labels_for(scale_type: str) -> list[str]:
    t = SCALE_TYPES.get(scale_type) or SCALE_TYPES["mss_noten"]
    return [lbl for lbl, _, _ in t["default_stufen"]]


def default_stufen_for(scale_type: str) -> list[dict]:
    """Default-Grenzen je Typ als Dict-Liste (für JSON/Template-Editor)."""
    t = SCALE_TYPES.get(scale_type) or SCALE_TYPES["mss_noten"]
    return [{"label": lbl, "min_pct": lo, "max_pct": hi}
            for lbl, lo, hi in t["default_stufen"]]


# ── Referenz-Auflösung ───────────────────────────────────────────────────

def _normalize_ref(ref: str | None) -> str:
    if not ref:
        return DEFAULT_SCALE
    if ref.startswith("builtin:") or ref.startswith("custom:"):
        return ref
    # bare Altwert
    if ref in BUILTINS:
        return f"builtin:{ref}"
    return DEFAULT_SCALE


def resolve_stufen(db, user, ref: str | None) -> list[tuple[str, float, float]]:
    """Liefert die Stufen-Liste [(label, min_pct, max_pct), …] für eine
    Referenz. Custom-Skalen werden aus der DB geladen (nur eigene)."""
    ref = _normalize_ref(ref)
    if ref.startswith("builtin:"):
        key = ref.split(":", 1)[1]
        return list(BUILTINS.get(key, BUILTINS["mss_noten"])["stufen"])
    # custom:<id>
    try:
        scale_id = int(ref.split(":", 1)[1])
    except (ValueError, IndexError):
        return list(BUILTINS["mss_noten"]["stufen"])
    from app.models import GradingScale  # lazy, vermeidet Zirkularimport
    gs = db.get(GradingScale, scale_id)
    if not gs or (user is not None and gs.owner_user_id != user.id):
        return list(BUILTINS["mss_noten"]["stufen"])
    try:
        payload = json.loads(gs.payload_json) or []
    except Exception:
        payload = []
    out: list[tuple[str, float, float]] = []
    for row in payload:
        try:
            out.append((str(row["label"]), float(row["min_pct"]), float(row["max_pct"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out or list(BUILTINS["mss_noten"]["stufen"])


def list_scales_for(db, user) -> list[tuple[str, str]]:
    """Dropdown-Optionen: Built-ins + eigene Custom-Skalen.
    Liefert [(ref, label), …]."""
    out: list[tuple[str, str]] = [
        (f"builtin:{k}", v["label"]) for k, v in BUILTINS.items()
    ]
    if db is not None and user is not None:
        from app.models import GradingScale
        from sqlalchemy import select
        rows = db.scalars(
            select(GradingScale)
            .where(GradingScale.owner_user_id == user.id)
            .order_by(GradingScale.name)
        ).all()
        for gs in rows:
            type_lbl = SCALE_TYPES.get(gs.scale_type, {}).get("label", gs.scale_type)
            out.append((f"custom:{gs.id}", f"{gs.name} ({type_lbl})"))
    return out


def scale_label(db, user, ref: str | None) -> str:
    """Anzeigename einer Referenz (für Listen/PDF)."""
    ref = _normalize_ref(ref)
    if ref.startswith("builtin:"):
        key = ref.split(":", 1)[1]
        return BUILTINS.get(key, BUILTINS["mss_noten"])["label"]
    try:
        scale_id = int(ref.split(":", 1)[1])
    except (ValueError, IndexError):
        return "Unbekannt"
    from app.models import GradingScale
    gs = db.get(GradingScale, scale_id)
    return gs.name if gs else "Gelöschter Schlüssel"


# ── Noten-Berechnung ─────────────────────────────────────────────────────

def grade_from_stufen(stufen: list, pct: float) -> str:
    """Stufen-Label für Prozentwert aus einer aufgelösten Stufen-Liste."""
    if not stufen:
        return ""
    pct_clamped = max(0, min(100, int(round(pct))))
    for label, lo, hi in stufen:
        if lo <= pct_clamped <= hi:
            return str(label)
    return str(stufen[-1][0])


def grade_for_ref(db, user, ref: str | None, pct: float) -> str:
    """Note für eine Referenz (löst Built-in/Custom auf)."""
    return grade_from_stufen(resolve_stufen(db, user, ref), pct)


def percent_for_grade(stufen: list, label: str) -> float | None:
    """Mittelpunkt-Prozent des Stufen-Intervalls mit passendem Label.
    Für note-Items: eine direkt vergebene Note → vergleichbarer Prozentwert,
    damit sie in die gewichtete Mittelung einfließen kann."""
    if not label:
        return None
    target = str(label).strip().lower()
    for lbl, lo, hi in stufen:
        if str(lbl).strip().lower() == target:
            return (float(lo) + float(hi)) / 2.0
    return None


def label_to_decimal(label: str | None) -> float | None:
    """Konvertiert ein Noten-Label zu einer Dezimalzahl für CSV/Excel-Exporte.

    MSS-Schulnoten mit Tendenz: '+' → −0,3 · '-' → +0,3 (z. B. '2+' → 1,7,
    '2' → 2,0, '2-' → 2,3). Numerische Labels (MSS-Punkte '15' … '0') werden
    direkt zurückgegeben. Unbekannte Labels → None.
    """
    if label is None:
        return None
    s = str(label).strip()
    if not s:
        return None
    # Reine Zahl (MSS-Punkte oder bereits dezimal)
    try:
        return float(s.replace(",", "."))
    except ValueError:
        pass
    # Schulnote mit optionaler Tendenz
    tendenz = 0.0
    base = s
    if s.endswith("+"):
        tendenz = -0.3
        base = s[:-1].strip()
    elif s.endswith("-"):
        tendenz = +0.3
        base = s[:-1].strip()
    try:
        return round(float(base.replace(",", ".")) + tendenz, 1)
    except ValueError:
        return None


def weighted_final(items: list[tuple[float, float]]) -> float:
    """items = [(percent, weight), …]. Liefert gewichteten Prozent-Schnitt.
    Gewichte werden auf ihre Summe normiert; Gewicht 0 zählt als 1
    (Gleichgewichtung), sofern ALLE Gewichte 0 sind."""
    if not items:
        return 0.0
    total_w = sum(max(0.0, w) for _, w in items)
    if total_w <= 0:
        # alle 0 → gleichgewichten
        return sum(p for p, _ in items) / len(items)
    return sum(p * max(0.0, w) for p, w in items) / total_w


# ── Rückwärtskompatible Built-in-only-API (ohne db) ──────────────────────

def list_scales() -> list[tuple[str, str]]:
    """Nur Built-ins (Legacy). Neue Aufrufer: list_scales_for(db, user)."""
    return [(f"builtin:{k}", v["label"]) for k, v in BUILTINS.items()]


def get_scale(key: str | None) -> dict:
    ref = _normalize_ref(key)
    if ref.startswith("builtin:"):
        return BUILTINS.get(ref.split(":", 1)[1], BUILTINS["mss_noten"])
    return BUILTINS["mss_noten"]


def grade_for_percent(scale_key: str | None, pct: float) -> str:
    """Built-in-Pfad (kein db). Für Custom-Skalen grade_for_ref nutzen."""
    return grade_from_stufen(get_scale(scale_key)["stufen"], pct)


def grade_for_points(scale_key: str | None, erreicht: float, maximum: float) -> str:
    if maximum <= 0:
        return ""
    return grade_for_percent(scale_key, (erreicht / maximum) * 100.0)


def is_known_scale(key: str | None) -> bool:
    """Built-in bekannt? (bare oder builtin:-Form)."""
    if not key:
        return False
    k = key.split(":", 1)[1] if key.startswith("builtin:") else key
    return k in BUILTINS
