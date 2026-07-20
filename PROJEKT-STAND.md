# Projektstand: DRS Unterrichtsmaterial-System

**Datum**: 2026-07-20 · **Schule**: David-Roentgen-Schule Neuwied, BBS Gewerbe + Technik (Mechatronik)

> Wenn du dieses Dokument in einer neuen Claude-Session lädst, sag direkt:
> *„Lies `PROJEKT-STAND.md` für den Stand. Ich möchte als Nächstes mit **\<Modul\>** weitermachen."*

---

## 0. Kurzüberblick (was sich zuletzt geändert hat)

Die App wurde ab Juni 2026 **verschlankt** und auf zwei Kernbereiche
fokussiert: **Stundenplan/Kalender + Bewertung**, im **Design der
Gemeindeverwaltung** (Kacheln, Karten, Vollbild-Assistenten, Detail-Modals).

- **Rückbau (Phase 1+2):** Lernsituationen, Arbeitsblätter, Wizard, Preview,
  Obsidian und Lernfelder sind in `app/main.py` **auskommentiert** (Code + DB
  bleiben liegen, nur nicht mehr eingehängt). Der Reskin läuft im GV-Stil mit
  Live-Dashboard.
- **Stundenplan ist jetzt manuell** (kein WebUntis mehr): eigene `tt_*`-Tabellen
  (Zeitraster, Schuljahr, Ferien, Versionen, Zeilen, Ausnahmen). Der Grid-Dienst
  `timetable_grid.py` baut formatgleich das Dict, das früher WebUntis lieferte —
  Template und PDF-Pfad blieben dadurch unverändert. Migration **0025**.
- **Stammdaten-Hierarchie** Jahrgang → Klasse → Schüler + Lerngruppen
  (`tt_jahrgaenge`, `tt_schulklassen`, Lerngruppen). Schüler leben jetzt in den
  Stammdaten; Stundenplan- und Prüfungs-Picker arbeiten mit **Lerngruppen**.
  Migration **0026**. **Wichtig:** Klasse ≠ Lerngruppe — der `klassen_key`
  bleibt die Stundenplan-/Prüfungs-Wahrheit (key4-Kompatibilität).
- **Vikunja-Aufgabenmodul** mit EINEM festen Projekt. Migration **0024**.
- **Schüler-Austritt** (zuletzt, 2026-07-15): Schüler werden beim Verlassen der
  Klasse **inaktiv** geschaltet statt gelöscht — Grund (`abschluss`/`abgang`) +
  letzter Schultag. Sie bleiben in ihrer Klasse, damit alte Prüfungen ihre
  Zuordnung behalten. Migration **0027**.
- **Monatsvorschau im Stundenplan** (2026-07-15): Button „📅 Monat" öffnet einen
  clientseitigen Kalender-Popover zum schnellen Springen zu einem Datum.
- **PDF-500-Fix** (2026-07-15): `drs-update` gleicht nach jedem pip-Upgrade den
  Playwright-Chromium ab (`playwright install chromium`), sonst crashen alle
  PDF-Exporte nach einem Playwright-Update mit Internal Server Error.
- **Unterrichtsplanung** (2026-07-20, NEU): Vier Bausteine im Stundenplan —
  **Thema verteilen** (⋯-Menü: Klasse+Fach+Zeitraum → Blöcke ankreuzen, Zähler
  „N Blöcke · 2N Schulstunden"; Thema erscheint als Pille unter dem Fach),
  **Klassenarbeit** (⋯-Menü: Blockauswahl + Tabelle „Themen seit der letzten
  Klassenarbeit", setzt `is_exam`, legt eine Vikunja-Aufgabe 5 Tage vorher an),
  **Reflexion** (Rechtsklick/Long-Press-Menü + Panel: 4 Kategorien × 3 Items,
  4-stufig + „Keine Angabe" + Notiz, eigenes 🔎-Icon im Grid) und die
  **Themen-Kaskade**. Migrationen **0028** + **0029**.

**Migrations-Stand: 0029.** Achtung: Die Abschnitte 1–2 unten beschreiben in
Teilen noch den **alten** Wizard-/WebUntis-Fokus — sie gelten architektonisch
(Sicherheit, SMB, OnlyOffice) weiter, aber die dort als „live" markierten
Wizard-/LS-/Arbeitsblatt-Module sind aktuell **ausgeblendet**.

---

## 1. Was die Software heute ist

Ein Lehrer-Werkzeug, das in einem **Proxmox-LXC (CT 500)** unter
`http://192.168.2.139/` läuft. Multi-User mit Login. Aktiver Fokus:
**manueller Stundenplan** mit Notizen/Aufgaben/Prüfungen pro Block, externe
iCal-Kalender, **Bewertungs-Modul**, **Stammdaten** (Jahrgang/Klasse/Schüler/
Lerngruppen) und **Vikunja-Aufgaben**. Arbeitsplan- und Bewertungs-PDFs via
Playwright/Chromium. Quellcode auf GitHub: **`mgoebel89/drs-Desktop`** (public).

Die ältere Material-Schiene (Konfigurationstool, Lernsituationen + Wizard,
Obsidian-Vault, OnlyOffice, SMB-Share) ist im Code vorhanden, aber im Zuge der
Verschlankung **ausgeblendet** (siehe Abschnitt 0).

### Vorhandene Module (alle live)

| Modul | Status | Details |
|---|---|---|
| Multi-User-Auth | ✓ | Argon2id, Sessions (Cookie 30 d), Lockout 5×/15 Min, Admin + Teacher Rollen |
| First-Run-Setup | ✓ | Beim ersten Browser-Aufruf: `/setup` legt Admin per Formular an |
| Konfigurationstool | ✓ | Editor mit Aufgaben + Bild-Upload (Base64), Revisionen pro Save |
| HTML- + PDF-Export | ✓ | Standalone-HTML für Moodle, PDF via Playwright/Chromium (A4) |
| Vorschau-Buttons im Editor | ✓ | „Vorschau HTML/PDF" in neuem Tab (inline statt Download) |
| Fach/Lernfeld-Toggle | ✓ | Ein Eingabefeld + Dropdown was als Label gezeigt wird |
| PDF: Schreib-Leerraum | ✓ | Statt textarea ~38 mm Freiraum für Handschrift |
| Hilfe-Reiter | ✓ | LaTeX/SI-Makro-Referenz mit Live-Rendering |
| Schul-Branding | ✓ | Logo + Schulname global in Admin-Settings, im Nav + Arbeitsblatt-Header |
| WebUntis-Integration | ✓ | Pro Nutzer Credentials verschlüsselt, Diagnose-Endpoint |
| Stundenplan-Grid | ✓ | Mo–Fr, 90-Min-Doppelblöcke, Subspalten Lessons/Events, All-Day-Zeile oben |
| iCal-Kalender | ✓ | Mehrere pro Nutzer mit Label+Farbe, RRULE-Expansion, Europe/Berlin |
| Lehrer-Notizen pro Block | ✓ | Theme, Notizen, Material, Bemerkungen, Fach-Override, Prüfung, Auto-Save |
| Notiz-Indikator + Prüfungs-Rahmen | ✓ | 📝-Icon + roter Rahmen live ohne Reload |
| „Letzte Stunde"-Block im Panel | ✓ | Vorige Notiz mit Markdown/LaTeX-Rendering |
| LXC-Installer + drs-update | ✓ | Proxmox-Helper-Script-Style, idempotent, alembic-Migrationen |
| **Lernsituationen + Wizard v2** | ✓ | 4-stufig auf Basis Inhalts-MD im Obsidian-Vault. 9 Material-Typen, Dual-Prompt (Fobizz + Claude-Pro) |
| **LS-Hard-Delete** | ✓ | Bestätigungsseite mit Auswirkungs-Übersicht, löscht DB + SMB-Ordner + Vault-MD |
| **MD-Schema v2** | ✓ | Lernsituationsbeschreibung + Phasen der vollständigen Handlung mit Aufgaben + Anmerkungen. v1 bleibt lesbar |
| **Aufgaben-Sync (DB ⇄ MD)** | ✓ | `ls_aufgaben`-Tabelle als Index, MD ist Quelle. Stale-Aufgaben werden automatisch aus DB entfernt |
| **Stundenplan-Aufgaben-Picker** | ✓ | Pro Block: LS auswählen, Aufgaben ankreuzen. Lösungsskizzen direkt im Panel sichtbar. Grid-Pille „Aufg. N, M" |
| **Bewertungs-Modul** | ✓ | Schülerverwaltung (Klassen, Moodle-CSV-Import), Prüfungen mit Notenskalen (MSS Schulnoten / MSS Punkte), Bewertungs-Matrix mit Auto-Save, Stufen-Schnellauswahl (3/4/5 Stufen) |
| **PDF-Export Bewertung** | ✓ | Pro Schüler ein S/W-PDF (Playwright), ZIP aller PDFs einer Klasse |
| **Prüfungs-MD Export+Import** | ✓ | Brücke zur Offline-App / Obsidian. Bewertungen als Markdown-Tabelle, Stufen als Labels oder Zahlen |
| **Notenmanager-JSON-Export** | ✓ | Endnoten als `drs-notenmanager.grades.v1`-JSON für die Gesamtnotenliste. Lehrer wählt Blatt+Spalte (+Beschriftung/Faktor); Tendenz-Labels passen 1:1 ins `note`-Feld. Endpoint `/exams/{id}/export.notenmanager.json` |
| **Stundenplan ↔ Prüfungen** | ✓ | Block-Panel zeigt Klassen-Prüfungen; Schnellaktion „Neue Prüfung" |
| **Bewertung v2** | ✓ | Klassenübergreifende Teilnehmer-Auswahl (Checkbox), Gruppenarbeit (Gruppen- + Einzel-Blöcke, Scope je Feedbackpunkt), verwaltete Notenschlüssel (Burger-Menü), Feedback-Vorlagen, PDF im Aufgabenblatt-Layout, ZIP + Lehrer-Zusammenfassung. Migration 0013 |
| **Bewertung v3** | ✓ | Wizard-Eingabe (Overlay, ein Schüler/Schritt, Auto-Save) für Einzel + Gruppen getrennt. Pro Feedbackpunkt `eval_type` (Punkte/Schulnote/Stufen) + Gewicht %. Endnote = gewichteter Prozent-Schnitt → Note via Schlüssel. Migration 0014 |
| **SMB-Material-Share** | ✓ | OMV-Share pro Nutzer, smbprotocol-Client, Upload + Vorschau |
| **OnlyOffice Office-Vorschau** | ✓ | Separater LXC CT 501, JWT-gesichert, Iframe-Editor (View-Mode) |
| **Obsidian-Vault-Schreiber** | ✓ | Pro LS eine .md im Vault, YAML-Frontmatter, App-Read-Only-Anzeige (KaTeX + Mermaid) |

### Datenmodell (SQLite, Stand Migration 0014)

- `users` — jetzt zusätzlich `smb_creds_enc` (AES-GCM)
- `user_sessions`, `audit_log`
- `worksheets` — jetzt `learning_situation_id` FK (nullable)
- `worksheet_revisions` — jetzt `markdown_source` für Wizard-Outputs
- `settings` (school_name, school_logo)
- `ical_calendars` (verschlüsselte URL, Label, Farbe)
- `lesson_notes` — Key: `user_id, lesson_date, klassen_key, subjects_key, block_start`; jetzt `learning_situation_id` FK
- `lesson_series_overrides` — Reihen-Fachname pro `user_id, klassen_key, subjects_key`
- **`learning_situations`** — `id, user_id, slug, display_name, klassen_key, lernfeld, smb_folder_name, obsidian_note_path, lernziele, vorwissen, last_fobizz_prompt, last_fobizz_output, last_material_type, last_extras, content_md_present, created_at, updated_at`. Slug unique pro User, `smb_folder_name` stabil (`LS-{id:04d}_{slug}`). `lernziele/vorwissen` deprecated (Wizard v1) — Inhalt lebt jetzt in der Inhalts-MD im Vault.
- **`ls_aufgaben`** — `id, learning_situation_id, nummer, titel, anchor, phasen, updated_at`. Unique `(ls_id, nummer)`. **Index** der Aufgaben aus der Inhalts-MD (Quelle bleibt die MD), für Stundenplan-Verknüpfung. Sync via `app/services/aufgabe_sync.py`.
- **`lesson_note_aufgaben`** — M2M zwischen `lesson_notes` und `ls_aufgaben`. ON DELETE CASCADE auf beiden Seiten — gelöschte/umbenannte Aufgaben fliegen automatisch aus den Block-Zuordnungen.
- **`students`** — pro User + Klasse. Felder: `nachname, vorname, email, moodle_id, active`. Quelle für Prüfungs-Bewertungen.
- **`exams`** — pro Prüfung. Felder: `title, datum, klassen_key, learning_situation_id (FK SET NULL), lesson_note_id (FK SET NULL), grading_scale_key ('mss_noten'|'mss_punkte'), input_mode ('numeric'|'stages')`.
- **`exam_feedback_points`** — pro Prüfung mehrere. `name, max_points, position, stages_json` (JSON-Liste `[{label, points}]` für Stufen-Modus).
- **`exam_results`** — pro `(exam_id, student_id)` eine Zeile. `erreicht_json` als JSON-Blob `{feedback_point_id: erreicht_pkt}`, `comment` freitext.
- **`exam_students`** (v2) — Teilnehmer-Membership pro Prüfung (klassenübergreifend) + `group_label` für Gruppenarbeit. PK `(exam_id, student_id)`.
- **`exam_group_results`** (v2) — Gruppen-Bewertung für `scope='group'`-Feedbackpunkte, unique `(exam_id, group_label)`.
- **`exam_feedback_points`** — `scope` ('individual'|'group'), `eval_type` ('punkte'|'note'|'stufen'), `weight_pct` (Gewicht in % für die gewichtete Endnote). `erreicht_json`-Werte: Zahl (punkte/stufen) oder Noten-Label-String (note).
- **`grading_scales`** (v2) — benutzerdefinierte Notenskalen (`scale_type` mss_noten/mss_punkte, `payload_json`-Stufen). `exams.grading_scale_key` referenziert `builtin:<key>` oder `custom:<id>`.
- **`feedback_templates`** (v2) — wiederverwendbare Feedbackpunkt-Sets (`payload_json`).
- **`plan_shift_journal`** (0028) — Journal der Themen-Kaskade. Pro Ausnahme eine
  Kette aus Einzelschritten: `exception_id` (CASCADE), `seq`, `klassen_key`,
  `subjects_key`, `from_date`/`from_block_start` → `to_date`/`to_block_start`,
  plus Snapshot `moved_theme`/`moved_notes`/`moved_material`.
- **`lesson_reflections`** (0029) — Selbstreflexion pro Stunde, am key4 verankert
  (Unique über `user_id, lesson_date, klassen_key, subjects_key, block_start`).
  `ratings_json` = Item-ID → `voll|eher|eher_nicht|gar_nicht` (fehlend = k. A.),
  dazu `free_text`. Wandert bei der Kaskade bewusst NICHT mit.
- Hinweis: `exams.klassen_key` ist seit v2 eine **Anzeige-Liste** (komma-getrennt); Teilnehmer-Wahrheit ist `exam_students`. MSS-Noten-Built-in korrigiert: 1+ entfällt, Top-Note 1.

---

## 2. Wichtige Architektur-Entscheidungen

- **Sicherheit**: Anthropic-API-Key + WebUntis-Creds + iCal-URLs + **SMB-Creds**
  werden AES-GCM verschlüsselt in der DB gespeichert. Master-Key in
  `/etc/drs/secret.key` (chmod 0640 root:drs).
- **Kein KI-Feedback im Schüler-Export**: Aufgabenblätter enthalten keinen
  API-Key. KI-Funktionen laufen ausschließlich im Lehrer-Container.
- **Keine Anthropic-API-Kosten im Wizard**: Die Material-Generierung läuft
  über **Fobizz** ODER über den **Claude-Pro-Chat** des Lehrers. Wizard ist
  Prompt-Generator + Material-Manager, kein API-Client. Pro Material-Typ
  bietet Schritt 3 zwei Tabs:
  - **Fobizz-Tab**: kurzer Kontext-Prompt für den vorab konfigurierten
    Agenten (Systemprompt aus `docs/fobizz-agent-systemprompt.md`).
  - **Claude-Tab**: self-contained Prompt inkl. didaktischer Rolle, direkt
    in Claude.ai einkippbar (Pro-Abo nutzen, keine API-Kosten).
- **Inhalts-MD als Quelle (Wizard v2)**: Pro Lernsituation eine
  strukturierte `.md` im Obsidian-Vault (siehe
  `docs/lerninhalt-md-schema.md`). Pflichtsektionen: Lernziele,
  Sachanalyse, Inhalt. Der Lehrer pflegt sie in Obsidian Desktop; der
  Wizard liest sie und bettet sie in den Material-Prompt ein. Erzeugte
  Materialien hängt der Wizard als `WIZARD-BLOCK` an die Output-Sektion
  derselben Datei — Historie bleibt erhalten.
- **SMB-Anbindung Python-nativ**: `smbprotocol` statt systemweitem
  `mount.cifs`. Kein Root nötig, keine Mount-Lifecycle-Komplexität,
  OnlyOffice bekommt Dateien über App-interne Token-URLs gestreamt.
- **Lernsituation-Identität stabil**: `display_name` umbenennbar, aber
  `slug` und `smb_folder_name` immutable nach Anlegen. Pattern
  `LS-{id:04d}_{slug}`. So bleibt der Windows-Explorer-Pfad konsistent
  und Obsidian-Wikilinks brechen nicht.
- **OnlyOffice in eigenem LXC (CT 501)**: privileged Container (Docker
  braucht `keyctl=1`), JWT-pflichtig, Caddy im DRS-LXC reverse-proxyt
  `/onlyoffice/*`. Standard-RAM 4 GB. Document-Server läuft als
  `onlyoffice/documentserver:latest` mit Restart-Policy.
- **Obsidian-Vault im gleichen SMB-Share**: Unterpfad `/vault` (konfigurierbar
  im Profil). App rendert die `.md` schreibgeschützt mit KaTeX + Mermaid.
  Bearbeitet wird in Obsidian Desktop auf dem Lehrer-PC.
- **Notizen pro Block**: Schlüssel inkl. `block_start` (`"HH:MM"`).
  3./4. und 5./6. desselben Tages haben separate Notizen.
- **Events im Grid**: Tagesspalte intern zweigeteilt — Lessons-Subspalte links
  (~12 %), Events-Subspalte rechts (~6 %). Lange Events bekommen `rowspan`
  in der Event-Subspalte; Untis-Stunden bleiben in ihren echten Slots.
- **iCal-Termine**: nur innerhalb des Schul-Stundenrasters angezeigt
  (außerhalb verworfen). Mehrtägige All-Day-Events als `colspan`-Balken in der
  „Ganztägig"-Zeile.

---

## 3. Aktuell offene Punkte

### ⚠️ Skripte im content-Block laufen VOR drs.js (2026-07-20, behoben)

**Landmine für jedes neue Overlay.** `base.html` bindet `/static/drs.js` erst in
Zeile 127 ein — **nach** `{% block content %}` (Zeile 100). Wer ein Skript, das
`DRS.modal()` braucht, in den content-Block schreibt, greift auf ein noch nicht
existierendes `window.DRS` zu. Die drei neuen Overlays hatten genau deshalb
**keinen einzigen verdrahteten Knopf**: Ihr Schutz `if (!window.DRS) return;`
griff bei jedem Laden, die Menüpunkte waren sichtbar, der Klick blieb wirkungslos.
**Regel:** Alles, was DRS braucht, gehört in `{% block scripts %}` — der rendert
nach dem Script-Tag. Gefunden wurde das erst im Browser; Server-Tests, Jinja-Parse
und Python-Import sind dagegen blind.

### ⚠️ Parallele Abrufe in dieselbe Liste (2026-07-20, behoben)

Die Blocklisten der neuen Overlays laden bei jeder Änderung von Klasse/Fach/Datum
neu. Ändert man drei Felder schnell hintereinander, laufen drei Abrufe parallel;
jede Antwort rendert in denselben Container — im Test **57 statt 7 Zeilen**, Einträge
doppelt. **Regel für jede nachladende Liste:** ein Sequenzzähler (`const my = ++seq`),
und nach dem `await` verwerfen, wenn `my !== seq`. Erst danach den Container leeren
und neu füllen.

### Unterrichtsplanung: Kaskade + Overlays (2026-07-20)

**Themen-Kaskade** (`app/services/plan_cascade.py`): Fällt ein Block aus (oder wird
eine Vertretung im Dialog auf „verschieben" gestellt), wandert das Paket
**Thema + Notizen + Material** auf die nächste **gehaltene** Stunde derselben Reihe
(**Klasse + Fach**); alle folgenden Pakete rücken mit, bis ein leerer Block die Kette
aufnimmt. **Klassenarbeits-Blöcke (`is_exam`) sind terminfest** — sie sind weder Ziel
noch wandern sie, die Kette überspringt sie. `is_exam` und die Reflexion bleiben immer
am Ursprungsblock.

Architektur bewusst **physisch** (Umschreiben in `lesson_notes`) statt eines
Positionsmodells: Das key4 bleibt die Wahrheit, Panel-, PDF- und Grid-Pfad bleiben
unverändert. Reversibel über das **Journal** `plan_shift_journal` (eine Zeile je
Einzelschritt, `exception_id` + `seq`). **Anwenden von hinten** (großes `seq` zuerst),
**Zurücknehmen von vorne** — so ist der Zielblock beim Schreiben stets leer. Beim
Aufheben der Ausnahme (`exception_delete`) läuft `cascade_revert` **vor** dem Löschen.

**Bewusst unangetastet:** „Stunde verschieben" (`kind='verschiebung'`) behält seine
alte Einzelnotiz-Wanderung über `_undo_note_move` — sie hat eine andere Semantik
(gezieltes Ziel statt „nächste gehaltene Stunde") und war nicht Teil der Anforderung.

**Long-Press:** Auf dem Handy öffnet der Long-Press weiterhin das **Kontextmenü** —
das ist der einzige Touch-Weg zu Ausfall/Vertretung/Verschieben. Die Reflexion wurde
deshalb NICHT auf den Long-Press gelegt, sondern als Menüeintrag „🔎 Stunde
reflektieren" ergänzt (plus Button im Block-Panel).

**Verifiziert im Browser** (lokaler Auth-Override gegen eine separate Test-DB):
Themen-Pille, Verteilen inkl. Zähler/Sperren, Klassenarbeit inkl. Themen-Tabelle und
rotem Rahmen, Reflexion inkl. Auto-Save und Icon, Kaskade end-to-end mit
KA-Überspringen und exakter Rücknahme. Mobil (375 px): kein horizontales Scrollen,
alle Touch-Flächen 44 px. **Offen:** die Vikunja-Aufgabe gegen eine echte Instanz
(nur der „nicht konfiguriert"-Pfad ist getestet) und echtes Touch-Verhalten am Gerät.

### ⚠️ Zeigergesten: pointercancel MUSS aufräumen (2026-07-16, behoben)

Im Board blieb nach einem Zug der Klon am Zeiger kleben, und nichts ging mehr bis
zum Neuladen. Ursache: Der Drag-Code räumte nur bei `pointerup` auf. Übernimmt der
Browser die Geste selbst (Textauswahl, natives Drag), schickt er aber **kein
pointerup, sondern `pointercancel`** — der Zustand blieb stehen, jeder weitere Zug
erzeugte einen weiteren Geist. **Regel für jede Zeigergeste:** ein einziger
`endDrag()`-Ausgang, an `pointerup` UND `pointercancel` gehängt; dazu auf
`pointerdown` ein `preventDefault()` + `setPointerCapture()` und `user-select:none`
auf der Karte, damit die Geste gar nicht erst abgebrochen wird. Die Schüler-
Wischzuordnung (`schueler.js`) macht das seit jeher richtig — beim Portieren ins
Board fehlte genau dieser Zweig.

### ⚠️ Cache-Busting galt nur für CSS (2026-07-16, behoben)

**Landmine für jede künftige Änderung:** `static_version()` in `app/templating.py`
lieferte die mtime der **`drs.css`** — an diesem einen Wert hängt aber auch jedes
`<script src="/static/….js?v={{ static_version() }}">` (12 Stellen, 4 JS-Dateien).
Wer JavaScript ohne CSS änderte, bekam denselben `?v=`-Wert und damit die **alte
Datei aus dem Browser-Cache**. Im Container beißt das besonders: `git pull` fasst
unveränderte Dateien nicht an, die `drs.css` behält ihre mtime. So war der neue
Aufgaben-Dialog nach dem Deploy tot — der Knopf existierte (Template neu), sein
Handler nicht (JS alt). `static_version()` nimmt jetzt den **jüngsten Zeitstempel
aller Dateien unter `/static`**; eine JS-Änderung bumpt die Version damit wieder.

### Vikunja: Bucket-Bug behoben + Anlege-Dialog (2026-07-16)

**Der Bug:** Im Board standen alle Spalten auf 0, obwohl die Aufgaben in Vikunja
zugeordnet waren. Ursache: `list_board()` las `…/views/{view}/buckets` und
erwartete die Aufgaben eingebettet. Dieser Endpoint liefert aber **nur die
Spalten-Metadaten**. Vikunja gibt die Aufgaben über den **Tasks**-Endpoint der
View aus — ist die View vom Typ Kanban, antwortet `…/views/{view}/tasks` mit den
Buckets *inklusive* ihrer Aufgaben statt mit einer flachen Liste. Genau darauf
liegt der Abruf jetzt (`_fetch_buckets`), mit dem Buckets-Endpoint als
Rückfallebene für ältere Instanzen. **Lehre:** Der frühere Mock war gegen die
eigene Annahme gebaut und hat den Fehler bestätigt statt gefunden — der neue
Mock bildet die echte API nach (Buckets-Endpoint liefert bewusst leere `tasks`)
und mockt nur `_call`, sodass der komplette Client-Code echt läuft.

**Anlege-Dialog:** Die Formular-Zeile über der Liste ist raus; „+ Neue Aufgabe"
oben rechts öffnet ein `DRS.modal()` mit Titel, Fällig, **Klasse**, Spalte,
Priorität, Beschreibung, Labels. Gespeichert wird ohne Reload (Karte + Listen-
Eintrag werden eingesetzt, Liste sortiert wie der Server). Die alte Formular-
Route `POST /aufgaben` ist gelöscht, es gibt nur noch `POST /api/vikunja/tasks`.

**Klasse an einer Aufgabe = Vikunja-Label** „Klasse: <Lerngruppe>" (Farbe
DRS-Blau), bei Bedarf automatisch angelegt (`ensure_label`), Auswahl kommt über
`GET /api/vikunja/lerngruppen` aus dem `lerngruppen()`-Service (stillgelegte
Jahrgänge fallen also mit raus). Bewusst **keine** eigene Tabelle: keine
Migration, in Vikunja sichtbar und filterbar. Preis: Es ist ein String — wird
eine Lerngruppe umbenannt, bleibt das alte Label stehen.

Außerdem: Die Kanban-View-ID wird prozessweit gecacht (`_view_cache`, bei 404
einmal frisch geholt) — vorher kostete jedes Verschieben einen zusätzlichen
`/views`-Request. Verifiziert im Browser gegen die simulierte API: Karten in den
richtigen Spalten, Dialog legt in die gewählte Spalte an, Labels inkl. Klassen-
Label, Drag & Drop, Einsortieren in die Liste. **Offen bleibt der Test gegen die
echte Instanz** (v. a. ob `view_kind` dort als String oder Index kommt).

### Vikunja-Board (2026-07-15, später)

Das Aufgaben-Modul um ein **Kanban-Board** erweitert (bisher nur flache Liste):

- **Umschalter Liste ↔ Board** oben (merkt sich die Wahl in `localStorage`, `#board`
  im Hash erzwingt das Board). Die schnelle Fälligkeits-Liste bleibt fürs Alltags-
  Abhaken, das Board fürs Sortieren.
- **Views-API ab Vikunja 0.22:** Buckets hängen an einer Kanban-**View**. Neue
  Client-Funktionen in `services/vikunja_client.py`: `get_kanban_view_id`
  (findet die View über `view_kind`), `list_board` (Buckets + eingebettete Tasks),
  `move_task` (dedizierter Endpoint `…/views/:view/buckets/:bucket/tasks` — ab 0.24
  ignoriert das Task-Update `bucket_id`!), `update_task`, `list_labels`/`add_label`/
  `remove_label`. `_normalize` um `description` + Label-`id` erweitert.
- **Drag & Drop überall** per Pointer-Events (Muster wie die Schüler-Wischzuordnung),
  ein Klick ohne Ziehen öffnet die **Edit-Karte** (Titel/Fällig/Priorität/Beschreibung
  + Labels setzen/entfernen). Drop ins „Erledigt"-Bucket hakt serverseitig automatisch
  ab. Frontend in neuer `static/vikunja.js`; Board-CSS + Umschalter + Beschreibungs-
  feld in `templates/vikunja/list.html`.
- Neue Endpoints in `routers/vikunja.py`: `GET /api/vikunja/board`,
  `POST …/tasks/{id}/move`, `POST …/tasks/{id}/update`, `GET /api/vikunja/labels`,
  `POST …/tasks/{id}/labels` + `…/labels/{id}/delete`.

Verifiziert wurde das komplette Frontend gegen **gemockte** Vikunja-Aufrufe
(Board rendern, Drag&Drop mit Move-Call, Edit-Karte laden/speichern, Label
add/remove) — die echte Vikunja-Instanz ist aus der Dev-Umgebung nicht erreichbar.
**Offen: End-to-End-Test gegen die reale Instanz** (v. a. `view_kind`-Form,
Move-Body, Label-Endpoints). Bucket-Verwaltung (Spalten anlegen/umbenennen) ist
bewusst noch nicht drin. **Nachtrag 2026-07-16:** Der Board-Abruf war falsch —
siehe den Abschnitt „Bucket-Bug behoben" oben.

### UI-Feinschliff aus dem Testlauf (2026-07-15, später)

Sieben beim Testen gefundene Punkte, alle umgesetzt und gegen die echte App
verifiziert (lesender Auth-Override, keine Passwörter berührt):

1. **Schülerliste:** Ganze Zeile klickbar (`stu-row`), „bearbeiten ›" ist jetzt
   echter Affordance-Text — das Bearbeiten-Modal (aktiv/inaktiv + Austrittsgrund
   + Datum) existierte schon, nur der Klick-Ziel-Bereich fehlte auf dem Desktop.
   Dateien: `students/klasse.html`, `static/schueler.js`.
2. **Unterschrift im Änderungsformular:** Höhe auf ≤20 pt gedeckelt und ab der
   Linie (y≈126.9) aufgebaut, Oberkante bleibt ≤145.9 → sitzt auf der Linie
   statt in die A1–A4-Zeilen zu ragen (Tabelle beginnt bei y≈148.7). Zahlen aus
   der echten Vorlage-Geometrie. **Sitz am fertigen PDF im Container final prüfen.**
   Datei: `services/stundenplanaenderung_pdf.py`.
3. **Block-Notiz-Panel:** Default nur „Geplantes Thema" + Prüfungsschalter; die
   Felder Notizen/Material/Bemerkungen/nächste Stunde per „+"-Chip zuschaltbar
   (gefüllte klappen automatisch auf), Fach-Anzeige + Bewertungen unter „Weitere
   Optionen". Panel 520 px breit, auf dem Handy Vollbild (Transform statt festem
   `right`). Datei: `timetable.html`.
4. **Stundenplan-Toolbar:** ‹ › als Icon-Buttons, „heute"/„📅 Monat" bleiben
   sichtbar, Arbeitsplan/Änderung/Einstellungen im ⋯-Overflow-Menü rechts.
   Datei: `timetable.html`.
5. **Stundenplan mobil:** Tag-Umschalter (‹ Mo–Fr ›), unter 760 px zeigt das Grid
   nur den aktiven Tag (CSS-Spaltenfilter über `data-col-day`, Zellen samt
   Klick-Handlern bleiben erhalten); Default-Tag = heute, sonst Montag. Desktop
   unverändert. Datei: `timetable.html`.
6. **Textfelder-Styling:** Der globale CSS-Selektor traf nur `input[type=text]`;
   die per `el('input', {value:…})` erzeugten Modal-Felder haben kein
   `type`-Attribut und fielen auf Browser-Default zurück. Selektor um
   `input:not([type])` erweitert → greifen jetzt überall. Datei: `static/drs.css`.
7. **Inaktive Klassen in Auswahllisten:** „Jahrgang bearbeiten → aktiv aus"
   **kaskadiert** jetzt auf die Schulklassen UND Lerngruppen des Jahrgangs
   (`jahrgang_save`), sodass sie zusammen aus allen Pickern verschwinden. Die
   Picker filtern bereits `active` (Prüfung/Zusatzstunde sogar über den
   `lerngruppen()`-Service inkl. Jahrgang-aktiv); die Versetzen-Ziele zusätzlich
   per Jahrgang-Join als Sicherheitsnetz für Altbestände. **Wirkt erst, wenn die
   alten Jahrgänge tatsächlich abgeschlossen werden** — Bestand ist noch aktiv.
   Dateien: `routers/stammdaten_api.py`, `routers/students.py`.

### Zuletzt fertiggestellt (2026-07-15)

- **Stundenplanänderungs-/Beurlaubungsformular**: Button „📝 Stundenplanänderung"
  im Stundenplan (bezieht sich auf die angezeigte Woche). Die Schul-PDF-Vorlage
  `app/forms/stundenplanaenderung.pdf` ist ein echtes AcroForm (201 Felder) und
  wird **direkt befüllt** (pypdf) → sieht 1:1 aus, der untere Schulleitungs-Block
  bleibt leer und im Reader interaktiv. Quelle = eigene `tt_exceptions` der Woche:
  **Ausfall** → „entfällt, Klasse informiert", **Vertretung** → Name; Verlegung/
  Zusatz ignoriert. Block → Formularzeilen: 1→1./2., 2→3./4., 3→5./6., 4→7./8.,
  5→A1/A2, 6→A3/A4 (beide Zeilen identisch; 9./10. bleiben leer). Feld-Zuordnung
  rein über **Geometrie** (die Feldnamen sind chaotisch), schmale Spalten auf
  Auto-Schriftgröße. Kopf = Profilname + erster/letzter geänderter Tag + heutiges
  Datum, Radio automatisch „erforderlich". Wizard wählt **eine** von 6 Begründungen
  und füllt deren Felder. **Profil-Unterschrift** (`user.signature_data`) wird per
  reportlab-Overlay auf die Linie gelegt. Keine Änderung in der Woche → kein PDF,
  nur Hinweis. Dateien: `app/services/stundenplanaenderung_pdf.py`,
  `app/forms/stundenplanaenderung.pdf`, `app/routers/timetable.py`
  (`GET /api/timetable/aenderung/preview`, `POST /timetable/aenderung.pdf`),
  `app/templates/timetable.html`, neue Deps `pypdf`+`reportlab`.
  **Noch offen:** End-to-End-Test im Container (Login-Passwort fehlte lokal) —
  v. a. Sitz/Größe der Unterschrift auf der Linie prüfen.
- **Schüler-Austritt**: Bearbeiten-Modal eines Schülers hat einen Austritts-
  Kasten (erscheint, wenn „in der Klasse aktiv" aus ist): Grund
  (Abschluss/Abgang) + letzter Schultag. Backend `POST /api/schueler/{id}/save`
  erzwingt bei `active=False` einen Grund (sonst 400) und leert die Felder beim
  Reaktivieren. In der Klassenliste zeigt eine Pille „Abschluss · TT.MM.JJJJ".
  Migration **0027**. Dateien: `app/routers/students.py`,
  `app/static/schueler.js`, `app/templates/students/klasse.html`.
- **Monatsvorschau Stundenplan**: Button „📅 Monat" in der Wochennavigation,
  reiner Client-Kalender (Popover mit KW-Spalte, Monatsblättern), Klick auf
  einen Tag → `/timetable?week=<Montag jener Woche>`. Datei:
  `app/templates/timetable.html`.
- **PDF-500 behoben**: `bin/drs-update` ruft nach `pip install --upgrade` jetzt
  `playwright install chromium` (idempotent). Ursache war ein hochgezogenes
  `playwright`, dessen passender Chromium-Build fehlte → alle PDF-Exporte 500.

> **Im Container ausrollen:** `sudo drs-update` (zieht bis Migration 0029 und
> gleicht den Chromium-Build ab). Falls das alte Update-Skript den neuen
> Playwright-Schritt noch nicht hat, einmalig von Hand:
> `PLAYWRIGHT_BROWSERS_PATH=/opt/drs/playwright /opt/drs/venv/bin/playwright install chromium`

### Bewertungs-Modul (Stand v3, weiterhin aktiv)

Über drei Iterationen (v1 → v2 → v3) umgebaut. Wizard-Eingabe (Overlay),
`eval_type` je Feedbackpunkt (`punkte`/`note`/`stufen`), `scope`
(individual/group), gewichteter Prozent-Schnitt → Note via Schlüssel. Logik in
`_item_weight` / `_item_percent` / `_student_total` (`app/routers/exams.py`).
Schüler kommen jetzt aus den Stammdaten/Lerngruppen.

### Direkt zu testen (im Container)

- **Arbeitsplan-PDF** nach `drs-update` wieder öffnen (`/timetable` → „📄
  Arbeitsplan (PDF)") — der 500 sollte weg sein.
- **Schüler austragen** durchspielen: Modal → aktiv aus → Grund + Datum →
  speichern; Liste zeigt die Pille; Reaktivieren leert die Felder.
- **Monatssprung**: „📅 Monat" öffnen, Monat blättern, Tag klicken → richtige
  Woche.

### Geplant, noch nicht umgesetzt

1. **Exam-Anlage bei der Klassenarbeit**: `_maybe_create_exam()` in
   `app/routers/timetable.py` ist ein bewusster No-Op-Platzhalter. Nach der
   Überarbeitung des Prüfungs-Moduls dort ein `Exam` anlegen und über die
   `LessonNote` verknüpfen — der Rest des Flows steht schon.
2. **Moodle-Notenexport** (Phase B): Endpoint `/exams/{id}/export.csv?format=moodle`
   ist als Platzhalter vorgesehen, noch nicht gebaut. `moodle_id` wird beim
   Schüler-Import bereits gespeichert. Doku in `docs/moodle-integration.md`.
3. **Unterschriftsbild pro Lehrer** für Bewertungs-PDFs (`signature_data_url`
   ist im Template vorbereitet, aber noch leer — User-Setting fehlt).
4. **HTTPS im Caddy** standardmäßig (aktuell HTTP auf Port 80).
5. **Ideen-Backlog** siehe Auto-Memory `ideen-drs-lxc` (Vikunja-Ausbau,
   Klassen/Lernfelder mit Stundenansatz, Stundenplanänderungs-Formular,
   Untis-Abgleich, Schüler-Notizen, NocoDB-Backup, lokale Diktierfunktion).

### Ausgeblendet (Verschlankung Phase 1)

Lernsituationen, Arbeitsblätter/Worksheets, Wizard, Preview, Obsidian und
Lernfelder sind in `app/main.py` auskommentiert. Code + DB-Tabellen bleiben
liegen; ob sie später endgültig entfernt oder reaktiviert werden, ist offen.

### Bekannte Limits

- WebUntis-Account hat keine `getTeachers`-Berechtigung → Lehrer-Namen können
  nicht resolved werden, wird in `_period_to_dict` umgangen.
- iCal-Events nur in Untis-Slots sichtbar. Termine außerhalb gehen verloren.
- DRS-Untis liefert keinen `lstext` (Lernstoff) — Feld bleibt leer, Panel-Logik
  dafür aber bereit.

---

## 4. Repo-Struktur (wichtigste Pfade)

```
drs-lxc/
├── install.sh                         # Proxmox-Host-Installer (legt CT + opt. CT 501 für OO an)
├── lxc-setup.sh                       # Inneres Setup im LXC
├── lxc-onlyoffice-setup.sh            # OnlyOffice-Setup im CT 501 (Docker + JWT)
├── bin/{drs-update, drs-admin}        # Helper-Skripte im Container
├── systemd/drs-api.service            # liest /etc/drs/{config,onlyoffice}.env
├── caddy/Caddyfile                    # inkl. /onlyoffice/* Reverse-Proxy
├── alembic.ini
├── requirements.txt                   # + smbprotocol, markdown-it-py, python-slugify, PyYAML
├── docs/
│   ├── fobizz-agent-systemprompt.md   # zum 1× Einfügen in den Fobizz-Agent
│   └── lerninhalt-md-schema.md        # Schema der Inhalts-MD für den Lehrer
├── tests/                             # pytest: Kaskade + Endpoint-Integration
└── app/
    ├── main.py
    ├── config.py, db.py, models.py, crypto.py, auth.py, branding.py, cli.py
    ├── templating.py                  # geteilte Jinja-Instanz mit school_name() Global
    ├── alembic/versions/0001–0029_*.py
    ├── routers/
    │   ├── auth.py, setup.py, users.py, profile.py     # profile.py: + SMB-Block
    │   ├── worksheets.py, settings.py, help.py, timetable.py
    │   ├── learning_situations.py     # LS-CRUD, Upload, Datei-Löschen
    │   ├── wizard.py                  # 5-Schritt-Flow + done
    │   ├── preview.py                 # PDF/Bild inline, OnlyOffice-Iframe
    │   └── obsidian.py                # MD-Rendering der Vault-Notiz
    ├── services/
    │   ├── plan_cascade.py            # Themen-Kaskade: held_blocks, cascade_shift/-revert
    │   ├── timetable_grid.py          # Wochengrid des manuellen Plans (Ersatz für WebUntis)
    │   ├── lerngruppen.py             # aktive Lerngruppen für alle Picker
    │   ├── vikunja_client.py          # create_task, ensure_label, Board/Buckets
    │   ├── stundenplanaenderung_pdf.py# AcroForm-Befüllung des Schulformulars
    │   ├── playwright_pdf.py
    │   ├── webuntis_client.py
    │   ├── ical_client.py
    │   ├── smb_client.py              # smbprotocol-basiert, pro Nutzer
    │   ├── onlyoffice_client.py       # JWT-Signer + In-Memory-Filetoken
    │   ├── obsidian_writer.py         # Schema v1+v2, Template-Builder, Aufgaben-Parser, Output-Append
    │   ├── aufgabe_sync.py            # MD-Aufgaben ⇄ DB-Tabelle ls_aufgaben (idempotent)
    │   ├── material_prompts.py        # 9-Typen-Katalog + Dual-Prompt-Builder (Fobizz + Claude)
    │   └── wizard_helpers.py          # Slug, Folder-Name (übrig nach Refactor)
    ├── static/{drs.css, default_school_logo.jpg}
    └── templates/
        ├── base.html                  # Nav-Einträge: Lernsituationen, Wizard
        ├── login.html, change_password.html, home.html, setup.html
        ├── profile.html, help.html, timetable.html, timetable_diagnose.html
        ├── preview.html, obsidian_note.html
        ├── learning_situations/{list.html, detail.html, confirm_delete.html}
        ├── wizard/{_layout.html, start.html, step1_md.html, step2_typ.html, step3_prompt.html, step4_output.html, done.html}
        ├── admin/{users.html, settings.html}
        └── worksheets/{list.html, editor.html, revisions.html, export.html}
```

---

## 5. Wartung im Container

```bash
pct enter 500                                       # in den Container
# oder gezielt
pct exec 500 -- /usr/local/sbin/drs-update          # Code-Update + Migrationen + Restart
pct exec 500 -- /usr/local/sbin/drs-admin list-users
pct exec 500 -- journalctl -u drs-api -n 50 --no-pager
```

Login: **`mgoebel`** (Admin)

---

## 6. Letzte Commits

Alle Stände sind auf GitHub `mgoebel89/drs-Desktop` @ `main` gepusht.
Migrations-Stand: **0029**.

| Commit | Was |
|---|---|
| _(dieser)_ | **Unterrichtsplanung**: Thema verteilen, Klassenarbeit, Reflexion, Themen-Kaskade. Migrationen 0028 + 0029, erste Testsuite (`tests/`, 14 Tests) |
| `48e81e2` | Fix aus dem Browser-Test: Overlays liefen nie (drs.js lädt nach dem content-Block), Race in den Blocklisten, Touch-Flächen 44 px |
| `056c323` | Unterrichtsplanung — Feature-Commit |
| `8c09a8d` | Aufgaben-Board: pointercancel räumt auf |
| _(älter)_ | **Schüler-Austritt** (Grund + letzter Schultag, Migration 0027), **Monatsvorschau** im Stundenplan, **PDF-500-Fix** (drs-update gleicht Chromium ab) |
| `de2058e` | Schüler wandern in die Stammdaten; Stundenplan-/Prüfungs-Picker auf Lerngruppen |
| `7d1ee48` | Stammdaten: Lerngruppen und Fächer endgültig löschbar, Fächer-Seite auf Karten |
| `bdad5f1` | Stammdaten mit Kacheln, Assistenten und Detail-Modals |
| `28cd537` | **Stammdaten** Jahrgang → Klasse → Schüler + Lerngruppen. Migration 0026 |
| `d430954` | **Manueller Stundenplan** Etappe 1+2 — Stammdaten, Zeitraster, Schuljahr, Ferien. Migration 0025 |
| `7df82d7` | **Vikunja-Aufgabenmodul** mit EINEM festen Projekt. Migration 0024 |
| `9e60767` | Reskin Phase 2 — Gemeindeverwaltungs-Stil + Live-Dashboard |
| `d284bad` | Verschlankung Phase 1 — Lernsituationen/Arbeitsblätter/Wizard ausblenden |
| `403da88` | (alt) Bewertung v3: Gewicht nur bei Schulnote, Layout-Fix |
| `450751b` | (alt) Bewertung v3: Wizard-Eingabe + Item-Typen + Gewichtung. Migration 0014 |

**Offline-App** (`Feedbackdatei`, eigenes Repo, Branch `master`, kein Remote):
letzter Commit `616ae01` — Prüfungs-MD-Import/-Export für die USB-Stick-Brücke.

**Vor der nächsten Session:** Im Container `drs-update` ausführen (zieht bis
Migration **0029** und gleicht den Playwright-Chromium ab). Die Unterrichtsplanung
wurde lokal im Browser verifiziert (Desktop + 375-px-Viewport, siehe Abschnitt 3);
im Container bleiben zu prüfen: die **Vikunja-Aufgabe** bei einer Klassenarbeit gegen
die echte Instanz und das **Touch-Verhalten am Gerät**.

### Tests

Seit 2026-07-20 gibt es `tests/` (pytest, 14 Tests): Kaskade als Unit-Tests
(`test_plan_cascade.py`) plus Endpoint-Integration über FastAPI-TestClient mit
Auth-Override. Ausführen: `.venv/Scripts/python.exe -m pytest tests/ -q`
(pytest ist Dev-Werkzeug und steht bewusst nicht in `requirements.txt`).
Die Fixtures bauen eine In-Memory-DB mit minimalem Stundenplan — **`StaticPool` +
`check_same_thread=False` sind Pflicht**, sonst sieht der TestClient-Thread die DB nicht.

---

## 7. So lädst du diesen Stand in eine neue Session

1. **Neuen Chat eröffnen**, Claude Code im Projektordner starten:
   ```
   cd C:\Users\mgoebel\Documents\ClaudeCode\drs-lxc
   ```
2. **Erster Prompt**:
   *„Lies `PROJEKT-STAND.md` für den Stand. Ich möchte als Nächstes mit
   **\<Modul\>** weitermachen."*
3. Claude liest dann diese Datei und kennt den semantischen Überblick, die
   Architektur-Entscheidungen, die offene Liste und die Repo-Struktur.
4. Code-Dateien liest Claude bei Bedarf selbst aus dem Repo — kein Upload nötig.

### Wenn du dieses Dokument aktualisierst

Nach größeren Änderungen an der App diese Datei pflegen und committen:
```bash
git add PROJEKT-STAND.md
git commit -m "docs: Projektstand <Datum>"
git push
```
So bleibt der Stand zwischen Mensch und Repo synchron.
