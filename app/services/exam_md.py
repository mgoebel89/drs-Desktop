"""Prüfungs-Markdown — Build + Parse.

Pro Prüfung eine .md mit YAML-Frontmatter + Sektionen:
- ## Schüler (Tabelle)
- ## Feedbackpunkte (Tabelle)
- ## Bewertungsstufen (nur bei eingabemodus: stufen, je Punkt Untertabelle)
- ## Bewertungen (Tabelle, optional)

Dient zwei Zwecken:
- Template-Generator: vorbefüllte Vorlage zum Download (Brücke zur
  Offline-App / USB-Stick / Obsidian-Pflege).
- Export/Import einer kompletten Prüfung inkl. Bewertungen.

Parser ist tolerant: zusätzliche Spalten werden ignoriert, fehlende
Sektionen führen nicht zum Abbruch — `parse_exam_md` liefert
Dict-Felder, die einzeln auf Vorhandensein prüfbar sind.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from datetime import date as date_cls
from typing import Iterable

import yaml

from app.services import grading


# ── Build ─────────────────────────────────────────────────────────────────

def _yaml_block(meta: dict) -> str:
    out = "---\n"
    out += yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    out += "---\n\n"
    return out


def _table(headers: list[str], rows: list[list]) -> str:
    out = "| " + " | ".join(headers) + " |\n"
    out += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in rows:
        cells = [str(c if c is not None else "").replace("|", "\\|") for c in row]
        # auf Header-Länge auffüllen
        cells += [""] * (len(headers) - len(cells))
        out += "| " + " | ".join(cells[:len(headers)]) + " |\n"
    return out


def build_from_exam(exam, students, results_by_student_id: dict) -> str:
    """Vollständige Prüfungs-MD aus einem DB-Exam — inkl. Bewertungen.

    Args:
        exam: Exam-Instanz.
        students: Liste der Schüler dieser Klasse.
        results_by_student_id: {student_id: ExamResult} — Bewertungen.
    """
    fps_data = []
    for fp in exam.feedback_points:
        stages = []
        if fp.stages_json:
            try:
                stages = json.loads(fp.stages_json)
            except Exception:
                stages = []
        fps_data.append({
            "name": fp.name,
            "max_points": fp.max_points,
            "stages": stages,
        })

    students_data = [
        {"nachname": s.nachname, "vorname": s.vorname,
         "email": s.email, "moodle_id": s.moodle_id}
        for s in students
    ]

    md = build_template(
        title=exam.title,
        datum=exam.datum,
        klasse=exam.klassen_key,
        lernfeld="",
        lernsituation_slug="",
        lehrer="",
        notenskala=exam.grading_scale_key,
        eingabemodus=exam.input_mode,
        students=students_data,
        feedback_points=fps_data,
    )

    # Bewertungen-Sektion mit echten Werten überschreiben:
    # Wir entfernen die letzte ##-Bewertungen-Sektion und hängen sie neu an.
    idx = md.rfind("## Bewertungen")
    if idx >= 0:
        md = md[:idx].rstrip() + "\n\n"

    headers = ["Nachname", "Vorname"] + [fp.name for fp in exam.feedback_points] + ["Kommentar"]
    rows = []
    for s in students:
        r = results_by_student_id.get(s.id)
        erreicht = json.loads(r.erreicht_json) if r and r.erreicht_json else {}
        row = [s.nachname, s.vorname]
        for fp in exam.feedback_points:
            val = erreicht.get(str(fp.id), "")
            # Wenn Stufen-Modus: passendes Label finden, sonst Zahl
            if exam.input_mode == "stages" and fp.stages_json:
                try:
                    stages = json.loads(fp.stages_json)
                    match = next((st for st in stages
                                  if str(st.get("points", "")) == str(val)), None)
                    row.append(match["label"] if match else str(val))
                except Exception:
                    row.append(str(val))
            else:
                row.append(str(val) if val != "" else "")
        row.append((r.comment if r else "") or "")
        rows.append(row)

    md += "## Bewertungen\n\n" + _table(headers, rows)
    return md


def build_template(
    *,
    title: str = "",
    datum: str = "",
    klasse: str = "",
    lernfeld: str = "",
    lernsituation_slug: str = "",
    lehrer: str = "",
    notenskala: str = "mss_noten",
    eingabemodus: str = "numeric",
    students: Iterable[dict] | None = None,
    feedback_points: Iterable[dict] | None = None,
) -> str:
    """Vollständige Vorlage. Schüler + Feedbackpunkte optional."""
    if not grading.is_known_scale(notenskala):
        notenskala = grading.DEFAULT_SCALE
    if eingabemodus not in ("numeric", "stages"):
        eingabemodus = "numeric"

    meta = {
        "title": title or "Neue Prüfung",
        "datum": datum or date_cls.today().isoformat(),
        "klasse": klasse,
        "lernsituation": lernsituation_slug,
        "lernfeld": lernfeld,
        "lehrer": lehrer,
        "notenskala": notenskala,
        "eingabemodus": eingabemodus,
        "schema_version": 1,
    }
    buf = io.StringIO()
    buf.write(_yaml_block(meta))
    buf.write(f"# {meta['title']}\n\n")

    # Schüler
    buf.write("## Schüler\n\n")
    s_rows = []
    if students:
        for s in students:
            s_rows.append([
                s.get("nachname", ""), s.get("vorname", ""),
                s.get("email", ""), s.get("moodle_id", ""),
            ])
    if not s_rows:
        s_rows = [["Mustermann", "Max", "", ""]]
    buf.write(_table(["Nachname", "Vorname", "Email", "Moodle-ID"], s_rows))
    buf.write("\n")

    # Feedbackpunkte
    buf.write("## Feedbackpunkte\n\n")
    fp_rows = []
    if feedback_points:
        for fp in feedback_points:
            fp_rows.append([fp.get("name", ""), fp.get("max_points", 10)])
    if not fp_rows:
        fp_rows = [["Aufgabe 1", 10], ["Aufgabe 2", 10]]
    buf.write(_table(["Punkt", "Max"], fp_rows))
    buf.write("\n")

    # Stufen-Tabellen (nur falls Stufen-Modus und Stages vorhanden)
    if eingabemodus == "stages" and feedback_points:
        any_stages = any(fp.get("stages") for fp in feedback_points)
        if any_stages:
            buf.write("## Bewertungsstufen\n\n")
            for fp in feedback_points:
                stages = fp.get("stages") or []
                if not stages:
                    continue
                buf.write(f"### {fp.get('name', '')}\n\n")
                rows = [[st.get("label", ""), st.get("points", 0)] for st in stages]
                buf.write(_table(["Stufe", "Punkte"], rows))
                buf.write("\n")

    # Bewertungen (immer als leere Vorlage am Ende — Lehrer kann sie auf
    # USB-Stick / in Obsidian ausfüllen und re-importieren)
    buf.write("## Bewertungen\n\n")
    bw_headers = ["Nachname", "Vorname"] + [
        fp.get("name", f"Punkt {i+1}")
        for i, fp in enumerate(feedback_points or [])
    ] + ["Kommentar"]
    if not (feedback_points or []):
        bw_headers = ["Nachname", "Vorname", "Aufgabe 1", "Aufgabe 2", "Kommentar"]
    bw_rows = []
    if students:
        for s in students:
            bw_rows.append([s.get("nachname", ""), s.get("vorname", "")]
                           + [""] * (len(bw_headers) - 3) + [""])
    if not bw_rows:
        bw_rows = [["Mustermann", "Max"] + [""] * (len(bw_headers) - 3) + [""]]
    buf.write(_table(bw_headers, bw_rows))

    return buf.getvalue()


# ── Parse (für Phase 9 vorbereitet) ───────────────────────────────────────

@dataclass
class ParsedExam:
    meta: dict
    students: list[dict]
    feedback_points: list[dict]   # [{name, max_points, stages: [...]}]
    bewertungen: list[dict]       # [{nachname, vorname, by_col: {colname: val}, comment}]


def _split_frontmatter(md: str) -> tuple[dict, str]:
    if not md.startswith("---\n"):
        return {}, md
    end = md.find("\n---\n", 4)
    if end < 0:
        return {}, md
    try:
        meta = yaml.safe_load(md[4:end]) or {}
    except Exception:
        meta = {}
    return meta, md[end + 5:]


def _parse_md_table(lines: list[str], start_idx: int) -> tuple[list[str], list[list[str]], int]:
    """Liest eine MD-Tabelle ab start_idx (Header-Zeile mit Pipes).
    Liefert (header, rows, end_idx). end_idx zeigt auf die Zeile nach der Tabelle."""
    if start_idx >= len(lines):
        return [], [], start_idx
    header_line = lines[start_idx].strip()
    if not header_line.startswith("|"):
        return [], [], start_idx
    header = [c.strip() for c in header_line.strip("|").split("|")]
    # Trenner-Zeile überspringen
    i = start_idx + 1
    if i < len(lines) and re.match(r"^\|[\s\-:\|]+\|$", lines[i].strip()):
        i += 1
    rows: list[list[str]] = []
    while i < len(lines):
        ln = lines[i].strip()
        if not ln.startswith("|"):
            break
        cells = [c.strip().replace("\\|", "|") for c in ln.strip("|").split("|")]
        rows.append(cells)
        i += 1
    return header, rows, i


def parse_exam_md(md: str) -> ParsedExam:
    meta, body = _split_frontmatter(md)
    lines = body.splitlines()

    students: list[dict] = []
    fps: list[dict] = []
    fp_stages: dict[str, list[dict]] = {}  # fp_name → stages
    bewertungen: list[dict] = []
    bewertung_cols: list[str] = []

    i = 0
    current_section = ""
    current_subsection = ""
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            current_section = ln[3:].strip().lower()
            current_subsection = ""
            i += 1
            continue
        if ln.startswith("### "):
            current_subsection = ln[4:].strip()
            i += 1
            continue
        if ln.strip().startswith("|"):
            header, rows, i_end = _parse_md_table(lines, i)
            sec_norm = current_section.replace(" ", "")
            if sec_norm.startswith("schüler") or sec_norm.startswith("schueler"):
                idx_nach = next((j for j, h in enumerate(header) if h.lower() == "nachname"), 0)
                idx_vor = next((j for j, h in enumerate(header) if h.lower() == "vorname"), 1)
                idx_mail = next((j for j, h in enumerate(header) if "mail" in h.lower()), -1)
                idx_id = next((j for j, h in enumerate(header) if "moodle" in h.lower() or "id" in h.lower()), -1)
                for r in rows:
                    if len(r) <= max(idx_nach, idx_vor): continue
                    nach = r[idx_nach].strip() if idx_nach < len(r) else ""
                    if not nach: continue
                    students.append({
                        "nachname": nach,
                        "vorname": r[idx_vor].strip() if idx_vor < len(r) else "",
                        "email": r[idx_mail].strip() if 0 <= idx_mail < len(r) else "",
                        "moodle_id": r[idx_id].strip() if 0 <= idx_id < len(r) else "",
                    })
            elif sec_norm.startswith("feedbackpunkte"):
                for r in rows:
                    if not r or not r[0].strip(): continue
                    try:
                        mx = float(r[1]) if len(r) > 1 and r[1].strip() else 0.0
                    except ValueError:
                        mx = 0.0
                    fps.append({"name": r[0].strip(), "max_points": mx, "stages": []})
            elif sec_norm.startswith("bewertungsstufen") and current_subsection:
                stages = []
                for r in rows:
                    if not r or not r[0].strip(): continue
                    try:
                        pts = float(r[1]) if len(r) > 1 and r[1].strip() else 0.0
                    except ValueError:
                        pts = 0.0
                    stages.append({"label": r[0].strip(), "points": pts})
                fp_stages[current_subsection] = stages
            elif sec_norm.startswith("bewertungen"):
                bewertung_cols = header
                for r in rows:
                    if not r or len(r) < 2: continue
                    nach = r[0].strip()
                    if not nach: continue
                    entry = {
                        "nachname": nach,
                        "vorname": r[1].strip() if len(r) > 1 else "",
                        "by_col": {},
                        "comment": "",
                    }
                    for j, col in enumerate(header[2:], start=2):
                        val = r[j].strip() if j < len(r) else ""
                        if col.lower() == "kommentar":
                            entry["comment"] = val
                        else:
                            entry["by_col"][col] = val
                    bewertungen.append(entry)
            i = i_end
            continue
        i += 1

    # Stufen den Feedbackpunkten zuweisen (per Name)
    for fp in fps:
        if fp["name"] in fp_stages:
            fp["stages"] = fp_stages[fp["name"]]

    return ParsedExam(
        meta=meta or {},
        students=students,
        feedback_points=fps,
        bewertungen=bewertungen,
    )
