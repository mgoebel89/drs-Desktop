# Projektstand: DRS Unterrichtsmaterial-System

**Datum**: 2026-06-09 · **Schule**: David-Roentgen-Schule Neuwied, BBS Gewerbe + Technik (Mechatronik)

> Wenn du dieses Dokument in einer neuen Claude-Session lädst, sag direkt:
> *„Lies `PROJEKT-STAND.md` für den Stand. Ich möchte als Nächstes mit **\<Modul\>** weitermachen."*

---

## 1. Was die Software heute ist

Ein vollständiges Lehrer-Werkzeug, das in einem **Proxmox-LXC (CT 500)** unter
`http://192.168.2.139/` läuft. Multi-User mit Login, Konfigurationstool für
Aufgabenblätter mit HTML-/PDF-Export für Moodle, WebUntis-Stundenplanansicht
mit Notizen pro Block, externe iCal-Kalender. Quellcode auf GitHub:
**`mgoebel89/drs-Desktop`** (public).

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

### Zuletzt fertiggestellt (Bewertung v3, Commit `403da88`)

Das **Bewertungs-Modul** ist über drei Iterationen (v1 → v2 → v3) komplett
umgebaut. Aktueller Stand:
- **Wizard-Eingabe** (Overlay): getrennte Wizards für Einzel- und
  Gruppenbewertung, ein Schüler/Gruppe pro Schritt, Weiter/Zurück +
  Pfeiltasten, Auto-Save je Schritt, Live-Note in der Übersicht.
- **Pro Feedbackpunkt `eval_type`**: `punkte` (Zahl), `note`
  (Schulnote direkt aus dem Notenschlüssel), `stufen` (selbst definierte
  Stufen mit Punktwert). Plus `scope` (individual/group).
- **Gewicht** nur beim Typ `note` (Feld erscheint nur dort). Punkte/Stufen
  poolen über ihre Max-Punkte (= Gesamtpunktzahl → Note). Endnote =
  gewichteter Prozent-Schnitt über alle Items → Note via Schlüssel.
  Gewichte werden automatisch normiert. Logik in `_item_weight` /
  `_item_percent` / `_student_total` (`app/routers/exams.py`).

### Direkt zu testen (im Container `drs-update`, dann durchspielen)

- **Migrationen 0008–0014** ausrollen. **Achtung**: in der Test-Session
  wurde bisher nur lokal verifiziert (Migration up/down, App-Import,
  Jinja-Parse, Scoring-Mathematik). End-to-End im Browser noch offen.
- **Bewertung v3 Ende-zu-Ende**: Prüfung anlegen → Feedbackpunkte mit
  gemischten Typen (Punkte/Schulnote/Stufen) + Gewichten → Einzel-Wizard
  durchklicken → Übersicht zeigt gewichtete Endnote → Export-Tab:
  Einzel-PDF + ZIP (inkl. `_Zusammenfassung.pdf`).
- **Gruppen-Wizard**: Teilnehmer Gruppen A/B zuordnen, Gruppen-Feedbackpunkt
  anlegen, Gruppenwert eintragen → fließt in Endnote der Mitglieder.
- **Notenschlüssel-Verwaltung** (`/grading-scales`) + **Feedback-Vorlagen**
  (`/feedback-templates`) prüfen.
- **OnlyOffice-LXC (CT 501)** über Installer-Pfad anlegen, DOCX-Vorschau prüfen.

### Geplant, noch nicht umgesetzt

1. **Moodle-Notenexport** (Phase B): Endpoint `/exams/{id}/export.csv?format=moodle`
   ist als Platzhalter vorgesehen, noch nicht gebaut. `moodle_id` wird beim
   Schüler-Import bereits gespeichert. Gradebook-CSV-Format mit Test-Instanz
   iterieren; Doku in `docs/moodle-integration.md`.
2. **Worksheet-Anknüpfung im Stundenplan-Panel**: „verknüpfte Aufgabenblätter
   zu Klasse+Fach" + „Neues Aufgabenblatt für diese Stunde". FK
   `worksheets.learning_situation_id` ist da, die UI fehlt noch.
3. **Wizard ↔ Stundenplan-Block**: Button „Wizard für diesen Block öffnen"
   im Block-Panel, der `lesson_notes.learning_situation_id` setzt.
4. **Unterschriftsbild pro Lehrer** für Bewertungs-PDFs (`signature_data_url`
   ist im Template vorbereitet, aber noch leer — User-Setting fehlt).
5. **HTTPS im Caddy** standardmäßig (aktuell HTTP auf Port 80).
6. **Visual-Editor für Worksheet-Vorlagen** (GrapesJS) — niedrige Priorität.

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
└── app/
    ├── main.py
    ├── config.py, db.py, models.py, crypto.py, auth.py, branding.py, cli.py
    ├── templating.py                  # geteilte Jinja-Instanz mit school_name() Global
    ├── alembic/versions/0001–0012_*.py
    ├── routers/
    │   ├── auth.py, setup.py, users.py, profile.py     # profile.py: + SMB-Block
    │   ├── worksheets.py, settings.py, help.py, timetable.py
    │   ├── learning_situations.py     # LS-CRUD, Upload, Datei-Löschen
    │   ├── wizard.py                  # 5-Schritt-Flow + done
    │   ├── preview.py                 # PDF/Bild inline, OnlyOffice-Iframe
    │   └── obsidian.py                # MD-Rendering der Vault-Notiz
    ├── services/
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
Aktuellster Commit: **`403da88`**. Migrations-Stand: **0014**.

| Commit | Was |
|---|---|
| `403da88` | fix Bewertung v3: Gewicht nur bei Schulnote, Layout-Überlappung behoben |
| `450751b` | **Bewertung v3**: Wizard-Eingabe + Item-Typen (Punkte/Note/Stufen) + Gewichtung. Migration 0014 |
| `15d5671` | Bewertung v2: Multi-Class, Teilnehmer-Auswahl, Gruppen, PDF im DRS-Layout |
| `22e3dff` | Bewertung v2: Löschen-Fix, Notenskalen-Verwaltung, Feedback-Vorlagen. Migration 0013 |
| `2cc69f1` | Bewertungs-Modul Phasen 1–5: Schüler, Prüfungen, Stufen-Modus. Migration 0012 |
| `f72c980` | Arbeitsblatt direkt aus LS-MD ohne Wizard |
| `da434de` | Burger-Menü mit Drawer + gruppierter Struktur |
| `fb99498` | Nav-Leiste-Fix (Context-Processor injiziert user) |
| `7c30b6a` | SyntaxError-Fix in obsidian_writer (502 behoben) |
| `7614bb0` | LS-Delete + MD-Schema v2 + Aufgaben-Stundenplan. Migration 0011 |
| `a98c5dd` | Wizard v2: Inhalts-MD im Vault, 9 Material-Typen, Dual-Prompt. Migration 0010 |
| `747c9f9` | LS + Wizard + SMB + OnlyOffice + Obsidian (Phasen 1–8). Migration 0008/0009 |

**Offline-App** (`Feedbackdatei`, eigenes Repo, Branch `master`, kein Remote):
letzter Commit `616ae01` — Prüfungs-MD-Import/-Export für die USB-Stick-Brücke.

**Vor der nächsten Session:** Im Container `drs-update` ausführen (zieht bis
Migration 0014). Bewertung v3 wurde bisher nur lokal verifiziert (Migration
up/down, App-Import 104 Routen, Jinja-Parse, Scoring-Mathematik) — der
**Browser-End-to-End-Test steht noch aus** (siehe Abschnitt 3).

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
