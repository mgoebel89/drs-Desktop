"""SCORM 1.2 Paket-Builder für Lernsituationen.

Schreibt ein selbst-enthaltenes ZIP, das in Moodle/Ilias/OpenOlat als
SCORM-Aktivität importiert werden kann. Schüler-Sicht (ohne
Lösungsskizzen, Lehrerhinweise, fachliche Präzisierung).

Aufgaben mit gesetztem `aufgabentyp` werden interaktiv (MC, MR,
shortanswer, freitext) und melden Score via cmi.interactions.

Wiederverwendet:
- `_md_to_html` aus app.routers.timetable (Markdown + LaTeX→MathML)
- `LsAttachment` aus dem SMB-Folder der LS

Aufruf: `build_scorm_package(db, user, ls) -> bytes`.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import PHASEN_LABELS, parse_phasen_csv
from app.models import (
    LearningSituation, LsArbeitsblatt, LsAttachment, LsAufgabe, User)
from app.services import smb_client
from app.templating import templates


# ── Eingebettete Assets (klein genug, um sie als String zu halten) ──────


SCORM_STYLE_CSS = r"""
:root { --blau:#00639c; --blau-hell:#e6f3fa; --pink:#d4005e; --green:#5ec27a;
  --orange:#e36e00; --text:#1a1a1a; --muted:#666; --border:#ddd; }
* { box-sizing: border-box; }
body { font-family: Calibri,Arial,sans-serif; color: var(--text);
  background: #fff; margin: 0; padding: 0 1rem 2rem; max-width: 920px;
  margin: 0 auto; }
.scorm-header { padding: 1rem 0 .4rem; border-bottom: 2px solid var(--blau); }
.scorm-header h1 { color: var(--blau); margin: 0; font-size: 22px; }
.scorm-header .lf { color: var(--muted); font-size: 13px; margin-top: 2px; }
.scorm-nav { background: var(--blau-hell); padding: .5rem .8rem;
  border-radius: 6px; margin: .8rem 0 1.2rem; font-size: 12px; }
.scorm-nav strong { color: var(--blau); margin-right: .4rem; }
.scorm-nav a { color: var(--blau); text-decoration: none; margin-right: .8rem;
  padding: 2px 6px; border-radius: 3px; }
.scorm-nav a:hover { background: #fff; }
.scorm-nav a.active { background: var(--blau); color: #fff; }
section { margin: 1.2rem 0; }
section h2 { color: var(--blau); border-bottom: 1px solid var(--border);
  padding-bottom: 4px; font-size: 17px; }
section h3 { color: var(--blau); font-size: 14px; }
.md { line-height: 1.55; }
.md p { margin: .4em 0; }
.md ul, .md ol { margin: .4em 0 .4em 1.4em; }
.md code { background: #f3f3f3; padding: 1px 5px; border-radius: 3px;
  font-family: Consolas,monospace; font-size: 12px; }
.md pre { background: #f3f3f3; padding: .6rem .9rem; border-radius: 5px;
  overflow: auto; }
math { font-family: 'Latin Modern Math','Cambria Math',serif; }
math[display="block"] { display: block; margin: .3em 0; text-align: center; }
.auftrag { background: #fff8e1; border-left: 4px solid #f5b942;
  padding: .8rem 1rem; border-radius: 4px; }
.auftrag h2 { border: 0; color: #b85b00; }
.auftrag-bild { max-width: 100%; max-height: 320px; border: 1px solid #ddd;
  border-radius: 4px; margin: .4rem 0; }
.phasen { display: flex; flex-wrap: wrap; gap: .3rem; margin: .3rem 0; }
.phase-pill { background: #d4edda; color: #1b5e20;
  border: 1px solid #5ec27a; padding: 2px 8px; border-radius: 10px;
  font-size: 11px; }
.phase-pill.small { font-size: 10px; padding: 1px 6px; }
.hinweis { background: #fff3e0; border-left: 4px solid #f5b942;
  padding: .6rem .9rem; border-radius: 4px; }
.hinweis h3 { margin-top: 0; color: #b85b00; border: 0; }
.aufgabe { background: #f9f9fb; border: 1px solid var(--border);
  border-radius: 6px; padding: .8rem 1rem; margin: .8rem 0; }
.aufgabe-head { display: flex; gap: .6rem; align-items: baseline; }
.aufgabe-head .nr { color: var(--blau); font-weight: 700; }
.aufgabe-head .aufgabe-titel { font-weight: 600; flex: 1; }
.aufgabe-head .punkte { color: var(--muted); font-size: 11px;
  background: #e9eef5; padding: 1px 7px; border-radius: 8px; }
.auf-interactive { margin-top: .6rem; padding: .6rem .8rem;
  background: #fff; border: 1px solid #d8d0f4; border-radius: 5px; }
.auf-interactive .opt { display: flex; gap: .5rem; align-items: center;
  margin: .3rem 0; }
.auf-interactive input[type=text],
.auf-interactive input[type=number] {
  padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px;
  font-size: 14px; flex: 1; max-width: 260px; }
.auf-interactive textarea {
  width: 100%; min-height: 70px; padding: 6px 10px; font-family: inherit;
  font-size: 13px; border: 1px solid var(--border); border-radius: 4px;
  resize: vertical; }
.auf-interactive button.check {
  margin-top: .4rem; padding: 5px 12px; background: var(--blau);
  color: #fff; border: 0; border-radius: 4px; cursor: pointer;
  font-size: 13px; }
.auf-interactive button.check:hover { background: #004e7c; }
.auf-interactive button.check:disabled { background: #aaa; cursor: default; }
.auf-feedback { margin-top: .5rem; padding: .4rem .7rem; border-radius: 4px;
  font-size: 12px; }
.auf-feedback.ok { background: #e8f5e9; color: #1b5e20;
  border: 1px solid var(--green); }
.auf-feedback.no { background: #fde2e2; color: #c62828;
  border: 1px solid var(--pink); }
.auf-feedback.info { background: #e6f3fa; color: var(--blau);
  border: 1px solid #b8d8ec; }
.anhang-list { list-style: none; padding-left: 0; }
.anhang-list li { padding: 4px 0; }
.ab-actions { margin-top: 1.2rem; padding-top: .8rem;
  border-top: 1px solid var(--border); display: flex; gap: .8rem;
  align-items: center; }
.ab-actions button { padding: 6px 14px; background: var(--green);
  color: #fff; border: 0; border-radius: 5px; cursor: pointer;
  font-size: 13px; }
.ab-actions .status { font-size: 12px; color: var(--muted); }
"""


SCORM_API_JS = r"""
// SCORM 1.2 API Wrapper — sucht window.API über parent + opener und
// bündelt Setter/Getter mit suspend_data-State (JSON in cmi.suspend_data).
(function(){
  var api = null;
  var inited = false;
  var state = { answered: {} };   // { aufId: { result: 'correct'|'wrong'|'neutral', score: number, max: number } }

  function findAPI(win){
    var depth = 0;
    while (win && !win.API && win.parent && win.parent !== win && depth < 10) {
      win = win.parent; depth++;
    }
    if (win && win.API) return win.API;
    if (window.opener && window.opener.API) return window.opener.API;
    return null;
  }
  function loadState(){
    if (!api) return;
    try {
      var s = api.LMSGetValue('cmi.suspend_data');
      if (s) state = JSON.parse(s);
      if (!state.answered) state.answered = {};
    } catch(e){ state = { answered: {} }; }
  }
  function saveState(){
    if (!api) return;
    try { api.LMSSetValue('cmi.suspend_data', JSON.stringify(state)); }
    catch(e){}
  }
  function totalScore(){
    var raw = 0, max = 0;
    Object.keys(state.answered).forEach(function(k){
      var a = state.answered[k]; raw += a.score || 0; max += a.max || 0;
    });
    return { raw: raw, max: max };
  }

  window.SCORM = {
    init: function(){
      if (inited) return;
      api = findAPI(window);
      if (!api) { console.warn('SCORM 1.2 API nicht gefunden'); return; }
      try { api.LMSInitialize(''); } catch(e){}
      loadState();
      inited = true;
      // Status auf 'incomplete' setzen, falls noch 'not attempted'
      try {
        var st = api.LMSGetValue('cmi.core.lesson_status');
        if (st === 'not attempted' || st === '') {
          api.LMSSetValue('cmi.core.lesson_status', 'incomplete');
        }
      } catch(e){}
    },
    setInteraction: function(aufId, typ, response, correctResp, result, score, max){
      if (!api) return;
      // Index = Anzahl bisher gesetzter Interaktionen
      try {
        var n = parseInt(api.LMSGetValue('cmi.interactions._count') || '0', 10);
        api.LMSSetValue('cmi.interactions.'+n+'.id', 'aufgabe-'+aufId);
        api.LMSSetValue('cmi.interactions.'+n+'.type', typ);
        api.LMSSetValue('cmi.interactions.'+n+'.student_response',
          String(response).slice(0, 200));
        if (correctResp != null) {
          api.LMSSetValue('cmi.interactions.'+n+'.correct_responses.0.pattern',
            String(correctResp).slice(0, 200));
        }
        if (result) api.LMSSetValue('cmi.interactions.'+n+'.result', result);
      } catch(e){}
      state.answered[aufId] = {
        result: result || 'neutral',
        score: score || 0, max: max || 0,
      };
      var t = totalScore();
      if (t.max > 0) {
        try {
          api.LMSSetValue('cmi.core.score.raw', String(t.raw));
          api.LMSSetValue('cmi.core.score.max', String(t.max));
          api.LMSSetValue('cmi.core.score.min', '0');
        } catch(e){}
      }
      saveState();
      try { api.LMSCommit(''); } catch(e){}
    },
    isAnswered: function(aufId){
      return !!(state.answered && state.answered[aufId]);
    },
    setCompleted: function(){
      if (!api) return;
      try {
        api.LMSSetValue('cmi.core.lesson_status', 'completed');
        api.LMSCommit('');
      } catch(e){}
    },
    finish: function(){
      if (!api || !inited) return;
      saveState();
      try { api.LMSCommit(''); api.LMSFinish(''); } catch(e){}
      inited = false;
    },
  };
})();
"""


SCORM_AUFGABEN_JS = r"""
// Render-Engine für die 4 Aufgabentypen + Auto-Bewertung via SCORM-API.
function renderAufgaben(){
  document.querySelectorAll('.aufgabe').forEach(function(box){
    var aid = box.dataset.aufid;
    var typ = box.dataset.typ || '';
    var punkte = parseInt(box.dataset.punkte || '0', 10);
    var inter = box.querySelector('.auf-interactive');
    if (!typ || !inter) return;
    var keyScript = inter.querySelector('script[data-schluessel]');
    var key = {};
    try { key = keyScript ? JSON.parse(keyScript.textContent) : {}; } catch(e){}

    var html = '';
    if (typ === 'mc' || typ === 'mr') {
      var inputType = typ === 'mc' ? 'radio' : 'checkbox';
      var opts = key.options || [];
      opts.forEach(function(o, i){
        html += '<div class="opt"><label>'
          + '<input type="'+inputType+'" name="auf-'+aid+'" value="'+i+'"> '
          + escapeHtml(o) + '</label></div>';
      });
    } else if (typ === 'shortanswer') {
      var inputT = (key.kind === 'numeric') ? 'number' : 'text';
      html = '<div class="opt"><input type="'+inputT+'" name="auf-'+aid+'" '
        + (inputT==='number' ? 'step="any"' : '') + '></div>';
    } else if (typ === 'freitext') {
      html = '<textarea name="auf-'+aid+'" placeholder="Deine Antwort …"></textarea>';
    }
    html += '<button type="button" class="check">Antwort prüfen</button>'
      + '<div class="auf-feedback" style="display:none"></div>';
    inter.innerHTML = (keyScript ? keyScript.outerHTML : '') + html;
    if (window.SCORM && window.SCORM.isAnswered(aid)) {
      inter.querySelector('button.check').disabled = true;
      var fb = inter.querySelector('.auf-feedback');
      fb.style.display = 'block';
      fb.className = 'auf-feedback info';
      fb.textContent = '✓ Bereits beantwortet (kann nur einmal eingereicht werden).';
    }
    inter.querySelector('button.check').addEventListener('click', function(){
      handleSubmit(box, typ, punkte, key, inter);
    });
  });
  var finishBtn = document.getElementById('ab-finish');
  if (finishBtn) finishBtn.addEventListener('click', function(){
    if (window.SCORM) window.SCORM.setCompleted();
    var st = document.getElementById('ab-status');
    if (st) st.textContent = '✓ Als bearbeitet markiert.';
  });
}

function escapeHtml(s){
  return String(s==null?'':s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

function handleSubmit(box, typ, punkte, key, inter){
  var aid = box.dataset.aufid;
  var result = 'neutral';
  var score = 0;
  var response = '';
  var correctStr = '';

  if (typ === 'mc') {
    var pick = inter.querySelector('input[type=radio]:checked');
    if (!pick) { showFb(inter, 'info', 'Bitte eine Antwort auswählen.'); return; }
    response = pick.value;
    correctStr = (typeof key.correct === 'number') ? String(key.correct) : '';
    if (correctStr && response === correctStr) {
      result = 'correct'; score = punkte;
    } else { result = 'wrong'; }
  } else if (typ === 'mr') {
    var picks = Array.from(inter.querySelectorAll('input[type=checkbox]:checked'))
      .map(function(cb){ return parseInt(cb.value,10); }).sort(function(a,b){return a-b;});
    response = picks.join(',');
    var correctArr = Array.isArray(key.correct) ? key.correct.slice().sort(function(a,b){return a-b;}) : [];
    correctStr = correctArr.join(',');
    if (correctStr && response === correctStr) {
      result = 'correct'; score = punkte;
    } else { result = 'wrong'; }
  } else if (typ === 'shortanswer') {
    var inp = inter.querySelector('input[name="auf-'+aid+'"]');
    response = inp.value;
    correctStr = String(key.expected != null ? key.expected : '');
    var ok = false;
    if (key.kind === 'numeric') {
      var got = parseFloat(response);
      var want = parseFloat(correctStr);
      var tol = (typeof key.tolerance === 'number') ? key.tolerance : 0;
      if (!isNaN(got) && !isNaN(want) && Math.abs(got - want) <= tol) ok = true;
    } else {
      var a = (response||'').trim();
      var b = (correctStr||'').trim();
      if (!key.case_sensitive) { a = a.toLowerCase(); b = b.toLowerCase(); }
      if (a && b && a === b) ok = true;
    }
    if (ok) { result = 'correct'; score = punkte; }
    else { result = 'wrong'; }
  } else if (typ === 'freitext') {
    var ta = inter.querySelector('textarea');
    response = ta.value;
    if (!response.trim()) { showFb(inter, 'info', 'Bitte eine Antwort eingeben.'); return; }
    result = 'neutral'; score = 0;  // Keine Auto-Bewertung
  } else {
    return;
  }

  if (window.SCORM) {
    window.SCORM.setInteraction(aid, typ, response, correctStr, result, score, punkte);
  }
  inter.querySelector('button.check').disabled = true;
  if (result === 'correct') {
    showFb(inter, 'ok', '✓ Richtig (' + score + '/' + punkte + ' Punkte)');
  } else if (result === 'wrong') {
    showFb(inter, 'no', '✗ Nicht ganz — Antwort wurde gespeichert.');
  } else {
    showFb(inter, 'info', '✓ Antwort gespeichert.');
  }
}

function showFb(inter, cls, msg){
  var fb = inter.querySelector('.auf-feedback');
  fb.style.display = 'block';
  fb.className = 'auf-feedback ' + cls;
  fb.textContent = msg;
}
"""


# ── Builder ───────────────────────────────────────────────────────────────


_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")


def _safe_asset_name(name: str) -> str:
    name = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = _SAFE.sub("_", name)
    return name[:120] or "file"


def _md(text: str) -> str:
    """Markdown → HTML inkl. LaTeX→MathML, ohne externe Render-Logik."""
    from app.routers.timetable import _md_to_html
    return _md_to_html(text or "")


def _read_smb(user: User, ls: LearningSituation, relpath: str) -> bytes | None:
    """Liest eine Datei aus dem LS-Material-Ordner. None bei Fehler."""
    if not relpath:
        return None
    try:
        cfg = smb_client.load_config(user)
        if not cfg:
            return None
        base = smb_client.material_subpath(cfg, ls.smb_folder_name)
        return smb_client.read_file(user, base + "/" + relpath.lstrip("/"))
    except Exception:
        return None


def _collect_arbeitsblaetter(db: Session, ls: LearningSituation) -> list[LsArbeitsblatt]:
    abs_ = db.scalars(
        select(LsArbeitsblatt).where(
            LsArbeitsblatt.learning_situation_id == ls.id)
        .order_by(LsArbeitsblatt.position)
    ).all()
    # Aufgaben anhängen
    for ab in abs_:
        ab._aufgaben = db.scalars(
            select(LsAufgabe).where(
                LsAufgabe.arbeitsblatt_id == ab.id,
                LsAufgabe.learning_situation_id == ls.id)
            .order_by(LsAufgabe.nummer)
        ).all()
    return abs_


def _phasen_labels(csv: str | None) -> list[str]:
    return [PHASEN_LABELS[p] for p in parse_phasen_csv(csv or "")]


def validate_for_scorm(db: Session, ls: LearningSituation) -> dict:
    """Prüft, ob die LS exportier-fähig ist. Liefert {ok, problems[]}.

    Pflichtkriterien (zusätzlich zu validate_pflicht_v4):
    - Jede Aufgabe mit aufgabentyp != "" und != "freitext" muss einen
      gültigen antwort_schluessel_json haben (mind. eine Option +
      Korrekt-Markierung bei mc/mr; expected bei shortanswer).
    """
    from app.routers.learning_situations import validate_pflicht_v4
    base = validate_pflicht_v4(db, ls)
    problems = list(base.get("problems") or [])

    for ab in _collect_arbeitsblaetter(db, ls):
        for a in ab._aufgaben:
            t = a.aufgabentyp or ""
            if not t or t == "freitext":
                continue
            try:
                key = json.loads(a.antwort_schluessel_json or "{}")
            except Exception:
                key = None
            problem = None
            if not isinstance(key, dict):
                problem = "kein gültiger Schlüssel"
            elif t in ("mc", "mr"):
                opts = key.get("options") or []
                if len(opts) < 2:
                    problem = "weniger als 2 Antwortoptionen"
                elif t == "mc" and not isinstance(key.get("correct"), int):
                    problem = "keine richtige Antwort markiert"
                elif t == "mr" and not (
                        isinstance(key.get("correct"), list) and key["correct"]):
                    problem = "keine richtigen Antworten markiert"
            elif t == "shortanswer":
                exp = key.get("expected")
                if exp is None or (isinstance(exp, str) and not exp.strip()):
                    problem = "erwartete Antwort fehlt"
            if problem:
                problems.append({
                    "code": f"aufgabe_{a.id}",
                    "label": f"AB {ab.position} · Aufgabe {a.nummer}: {problem}",
                })
    return {"ok": not problems, "problems": problems}


def build_scorm_package(db: Session, user: User,
                        ls: LearningSituation) -> bytes:
    """Erzeugt ein SCORM-1.2-Paket als ZIP-Bytes für die übergebene LS.

    Wirft ValueError, wenn die LS nicht gültig ist (siehe
    validate_for_scorm)."""
    v = validate_for_scorm(db, ls)
    if not v["ok"]:
        labels = "; ".join(p["label"] for p in v["problems"])
        raise ValueError("Lernsituation unvollständig: " + labels)

    arbeitsblaetter = _collect_arbeitsblaetter(db, ls)

    # ── Assets sammeln ────────────────────────────────────────────────
    asset_files: list[tuple[str, bytes]] = []  # (zip-path, data)
    asset_zip_paths: list[str] = []  # für Manifest <file href=>
    asset_names_seen: set[str] = set()

    def _add_asset(name: str, data: bytes) -> str:
        """Fügt eine Datei in assets/ ein, gibt den ZIP-Pfad zurück.
        Bei Namens-Kollision wird Suffix angehängt."""
        safe = _safe_asset_name(name)
        base, dot, ext = safe.rpartition(".")
        i = 1
        candidate = safe
        while candidate in asset_names_seen:
            i += 1
            candidate = (f"{base}_{i}.{ext}" if dot else f"{safe}_{i}")
        asset_names_seen.add(candidate)
        zip_path = "assets/" + candidate
        asset_files.append((zip_path, data))
        asset_zip_paths.append(zip_path)
        return zip_path

    # Auftragsbild
    auftragsbild_path = ""
    if ls.auftrag_bild_path:
        data = _read_smb(user, ls, ls.auftrag_bild_path)
        if data:
            auftragsbild_path = _add_asset(ls.auftrag_bild_path, data)

    # Anhänge (LsAttachment)
    attachments_out: list[dict] = []
    from app.constants import ATTACHMENT_KATEGORIE_LABELS
    att_rows = db.scalars(
        select(LsAttachment).where(
            LsAttachment.learning_situation_id == ls.id)
        .order_by(LsAttachment.position, LsAttachment.id)
    ).all()
    for att in att_rows:
        if att.kategorie == "auftragsbild":
            # Bereits über auftragsbild_path eingebunden (oder hier
            # zusätzlich, falls Lehrer mehrere hat — wir nehmen es)
            pass
        data = _read_smb(user, ls, att.smb_relpath)
        if not data:
            continue
        zp = _add_asset(att.dateiname, data)
        attachments_out.append({
            "dateiname": att.dateiname,
            "kategorie_label": ATTACHMENT_KATEGORIE_LABELS.get(
                att.kategorie, att.kategorie),
            "zip_path": zp,
        })

    # ── HTML-Seiten rendern ───────────────────────────────────────────
    env = templates.env  # Jinja2-Env aus app.templating
    manifest_tpl = env.get_template("scorm/imsmanifest.xml.j2")
    index_tpl = env.get_template("scorm/index.html.j2")
    ab_tpl = env.get_template("scorm/ab.html.j2")

    index_html = index_tpl.render({
        "ls": ls,
        "arbeitsblaetter": arbeitsblaetter,
        "auftragsbild_path": auftragsbild_path,
        "auftrag_html": _md(ls.auftrag_md),
        "lernsituation_html": _md(ls.lernsituation_md),
        "kompetenzen_html": _md(ls.kompetenzen_md),
        "uebergreifende_html": _md(ls.uebergreifende_aspekte_md),
        "attachments": attachments_out,
    })

    ab_pages: list[tuple[str, str]] = []  # (filename, html)
    for ab in arbeitsblaetter:
        aufgaben_out: list[dict] = []
        for a in ab._aufgaben:
            schluessel = a.antwort_schluessel_json or "{}"
            try:
                json.loads(schluessel)
            except Exception:
                schluessel = "{}"
            aufgaben_out.append({
                "id": a.id,
                "nummer": a.nummer,
                "titel": a.titel or "",
                "text_html": _md(a.text_md or ""),
                "aufgabentyp": a.aufgabentyp or "",
                "phasen_labels": _phasen_labels(a.phasen),
                "punkte": a.punkte or 0,
                "schluessel_json": schluessel,
            })
        html = ab_tpl.render({
            "ls": ls,
            "ab": ab,
            "arbeitsblaetter": arbeitsblaetter,
            "ab_phasen_labels": _phasen_labels(ab.phasen),
            "hinweis_html": _md(ab.bearbeitungshinweis_md),
            "content_html": _md(ab.content_md),
            "aufgaben": aufgaben_out,
        })
        ab_pages.append((f"ab-{ab.position:02d}.html", html))

    manifest_xml = manifest_tpl.render({
        "ls": ls,
        "arbeitsblaetter": arbeitsblaetter,
        "asset_files": asset_zip_paths,
    })

    # ── ZIP zusammenstellen ───────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("imsmanifest.xml", manifest_xml)
        z.writestr("index.html", index_html)
        for fname, html in ab_pages:
            z.writestr(fname, html)
        z.writestr("shared/api.js", SCORM_API_JS)
        z.writestr("shared/aufgaben.js", SCORM_AUFGABEN_JS)
        z.writestr("shared/style.css", SCORM_STYLE_CSS)
        for zp, data in asset_files:
            z.writestr(zp, data)
    return buf.getvalue()


__all__ = ["build_scorm_package", "validate_for_scorm"]
