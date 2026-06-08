"""Notenskalen — hardcoded.

Pro Skala eine Liste (label, min_pct, max_pct) — Grenzen inklusiv.
Die Note für eine erreichte Prozentzahl wird über die erste passende
Stufe ermittelt.

Neue Skalen lassen sich hier ergänzen; das Dropdown im Exam-Formular
liest direkt aus dieser Datei.
"""
from __future__ import annotations


SCALES: dict[str, dict] = {
    "mss_noten": {
        "label": "MSS Schulnoten (1+ … 6)",
        "stufen": [
            ("1+", 96, 100),
            ("1",  92, 95),
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
        ],
    },
    "mss_punkte": {
        "label": "MSS Punkte (15 … 0)",
        "stufen": [
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
        ],
    },
}

DEFAULT_SCALE = "mss_noten"


def list_scales() -> list[tuple[str, str]]:
    """Liefert [(key, label), …] für Dropdown."""
    return [(k, v["label"]) for k, v in SCALES.items()]


def get_scale(key: str | None) -> dict:
    """Liefert die Skala. Fällt auf DEFAULT_SCALE zurück, wenn key unbekannt."""
    if not key or key not in SCALES:
        return SCALES[DEFAULT_SCALE]
    return SCALES[key]


def grade_for_percent(scale_key: str | None, pct: float) -> str:
    """Liefert das Stufen-Label für einen Prozentwert.
    pct wird auf 0..100 geklemmt und auf ganze Prozente gerundet."""
    pct_clamped = max(0, min(100, int(round(pct))))
    scale = get_scale(scale_key)
    for label, lo, hi in scale["stufen"]:
        if lo <= pct_clamped <= hi:
            return label
    # Sollte nicht passieren, aber Fallback auf letzte Stufe (schlechteste Note)
    return scale["stufen"][-1][0]


def grade_for_points(scale_key: str | None, erreicht: float, maximum: float) -> str:
    """Komfort-Wrapper: liefert Note für (erreichte / max) * 100."""
    if maximum <= 0:
        return ""
    return grade_for_percent(scale_key, (erreicht / maximum) * 100.0)


def is_known_scale(key: str | None) -> bool:
    return bool(key) and key in SCALES
