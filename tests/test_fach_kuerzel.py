"""Im Stundenplan (und damit im Arbeitsplan-PDF) steht das Fach-Kürzel,
nicht der lange Anzeigename. Ohne Kürzel bleibt der Anzeigename stehen."""
from __future__ import annotations

from datetime import date

from app import models as m
from app.services import timetable_grid


def _lessons(db, user, ref):
    grid = timetable_grid.get_week_grid(db, user, ref=ref)
    out = []
    for lessons in grid["cells"].values():
        out.extend(lessons)
    return out


def test_grid_zeigt_kuerzel(db, plan):
    fach = db.query(m.TtFach).first()
    fach.display_name = "Elektrotechnik LF3"
    fach.kuerzel = "LF3"
    db.flush()

    lessons = _lessons(db, plan["user"], date(2026, 8, 3))
    assert lessons, "Der Testplan liefert Stunden"
    for l in lessons:
        assert l["fach_display"] == "LF3"
        assert l["subjects_long"] == ["LF3"]
        assert l["subjects_key"] == "BBU"   # der Schlüssel bleibt unberührt


def test_ohne_kuerzel_bleibt_anzeigename(db, plan):
    fach = db.query(m.TtFach).first()
    fach.display_name = "Elektrotechnik LF3"
    fach.kuerzel = ""
    db.flush()

    lessons = _lessons(db, plan["user"], date(2026, 8, 3))
    assert all(l["fach_display"] == "Elektrotechnik LF3" for l in lessons)


def test_alte_ausnahme_bekommt_das_kuerzel(db, plan):
    """Ausnahmen tragen einen Anzeige-Snapshot. Wurde er vor der Umstellung
    geschrieben, steht der lange Name drin — die Stammdaten gewinnen."""
    fach = db.query(m.TtFach).first()
    fach.kuerzel = "LF3"
    db.add(m.TtException(
        user_id=plan["user"].id, kind="zusatz",
        lesson_date=plan["days"]["B1"], block_start="08:00",
        klassen_key="MT", subjects_key="BBU",
        snap_klassen_display="MT", snap_fach_display="Elektrotechnik LF3"))
    db.flush()

    lessons = _lessons(db, plan["user"], date(2026, 8, 3))
    zusatz = [l for l in lessons if l["status"] == "zusatz"]
    assert len(zusatz) == 1
    assert zusatz[0]["fach_display"] == "LF3"
