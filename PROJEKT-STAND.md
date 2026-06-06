# Projektstand: DRS Unterrichtsmaterial-System

**Datum**: 2026-06-06 · **Schule**: David-Roentgen-Schule Neuwied, BBS Gewerbe + Technik (Mechatronik)

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
| **SMB-Material-Share** | ✓ | OMV-Share pro Nutzer, smbprotocol-Client, Upload + Vorschau |
| **OnlyOffice Office-Vorschau** | ✓ | Separater LXC CT 501, JWT-gesichert, Iframe-Editor (View-Mode) |
| **Obsidian-Vault-Schreiber** | ✓ | Pro LS eine .md im Vault, YAML-Frontmatter, App-Read-Only-Anzeige (KaTeX + Mermaid) |

### Datenmodell (SQLite, Stand Migration 0011)

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

### Direkt aus letzter Session noch zu klären / zu testen

- **Migration 0008 + 0009 + 0010** im Container ausrollen (`drs-update`)
  und Wizard v2 Ende-zu-Ende durchspielen: LS anlegen → Vorlage in Vault
  schreiben → in Obsidian befüllen → Wizard Schritt 2/3/4 mit Material-Typ
  „Arbeitsblatt" laufen lassen, Output einfügen, optional als Worksheet
  anlegen. Vault-MD nach dem Lauf prüfen (WIZARD-BLOCK angehängt?).
- **OnlyOffice-LXC (CT 501)** über den neuen Installer-Pfad anlegen lassen
  und DOCX/PPTX-Vorschau im Browser prüfen.
- **Optik-Check** des durchgehenden Event-Balkens via rowspan
  (Commit `3075461`, `flex: 1 1 auto` auf `.tt-event`) — vor der Wizard-Arbeit
  noch nicht final getestet.
- **Sub-Spalten-Breiten** im Grid evtl. fein-tunen (aktuell 12 % Lessons :
  6 % Events pro Tag).

### Geplant, noch nicht umgesetzt

1. **Worksheet-Anknüpfung im Stundenplan-Panel**: „verknüpfte Aufgabenblätter
   zu Klasse+Fach" + „Neues Aufgabenblatt für diese Stunde" als Schnellaktion.
   FK `worksheets.learning_situation_id` ist da, die UI fehlt noch.
2. **Wizard ↔ Stundenplan-Block**: Button „Wizard für diesen Block öffnen"
   im Block-Panel, der `lesson_notes.learning_situation_id` setzt und
   `LessonNote.theme` aus dem Wizard-Output befüllt. Endpunkte und FK stehen
   schon, nur die Panel-Aktion fehlt.
3. **HTTPS im Caddy** standardmäßig (aktuell HTTP auf Port 80; im Caddyfile
   als Kommentarblock vorbereitet).
4. **Visual-Editor für Worksheet-Vorlagen** (GrapesJS) — niedrige Priorität.

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
    ├── alembic/versions/0001–0011_*.py
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

| Commit | Was |
|---|---|
| _pending_ | **MD-Schema v2 + LS-Delete + Aufgaben-Stundenplan**: Pflichtsektionen, Aufgaben mit Phasen-Tags + Lösungsskizzen, DB-Sync, Block-Picker mit Lösungsanzeige, Grid-Pille. Migration 0011. |
| _pending_ | **Wizard v2**: Inhalts-MD im Vault, 4 Schritte, 9 Material-Typen, Dual-Prompt (Fobizz + Claude), Worksheet-Übernahme. Migration 0010. |
| _pending_ | Phase 6+7: Wizard-Flow + Fobizz-Agent-Systemprompt |
| _pending_ | Phase 5: Obsidian-Writer + Read-Only-Anzeige |
| _pending_ | Phase 4: Preview-Router (PDF/Bild/OnlyOffice-Iframe) |
| _pending_ | Phase 3: OnlyOffice CT 501 + Installer-Automation |
| _pending_ | Phase 2: SMB-Service + Profil-UI |
| _pending_ | Phase 1: Migration 0008 + LearningSituation-Model |
| `3075461` | Event-Card flex:1 für durchgehenden Balken |
| `c1b2b89` | Tagesspalten zweigeteilt (Lessons + Events Subspalten) |
| `6fefb5e` | Lange Events nicht mehr als rowspan-Lessons-Merge |
| `3c4248e` | Notizen pro Block (block_start im Key) |
| `ca75b08` | Prüfung/Notiz live im Grid, kein roter Hintergrund |
| `0e08cf1` | Fach-Override (Reihe + Sitzung) + Prüfung |

**Vor der nächsten Session:** Im Container `drs-update` ausführen (Migration
0008–0011), Profil → SMB-Zugang eintragen, ggf. OnlyOffice-LXC anlegen
(Installer-Pfad), Wizard testen. Bestehende v1-LS bleiben funktional —
beim Öffnen im Wizard bietet die App eine Schema-v2-Vorlage (überschreibt
v1 — vorher Inhalte sichern).

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
