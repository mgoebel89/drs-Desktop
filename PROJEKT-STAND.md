# Projektstand: DRS Unterrichtsmaterial-System

**Datum**: Juni 2026 · **Schule**: David-Roentgen-Schule Neuwied, BBS Gewerbe + Technik (Mechatronik)

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

### Datenmodell (SQLite, Stand Migration 0007)

- `users`, `user_sessions`, `audit_log`
- `worksheets`, `worksheet_revisions`
- `settings` (school_name, school_logo)
- `ical_calendars` (verschlüsselte URL, Label, Farbe)
- `lesson_notes` — Key: `user_id, lesson_date, klassen_key, subjects_key, block_start`
- `lesson_series_overrides` — Reihen-Fachname pro `user_id, klassen_key, subjects_key`

---

## 2. Wichtige Architektur-Entscheidungen

- **Sicherheit**: Anthropic-API-Key + WebUntis-Creds + iCal-URLs werden
  AES-GCM verschlüsselt in der DB gespeichert. Master-Key in
  `/etc/drs/secret.key` (chmod 0640 root:drs).
- **Kein KI-Feedback im Schüler-Export**: Aufgabenblätter enthalten keinen
  API-Key. KI-Funktionen laufen ausschließlich im Lehrer-Container.
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

### Direkt aus letzter Session noch zu klären

- **Optik-Check** des durchgehenden Event-Balkens via rowspan
  (Commit `3075461`, `flex: 1 1 auto` auf `.tt-event`). User hat den
  Container noch nicht final getestet.
- **Sub-Spalten-Breiten** im Grid evtl. fein-tunen (aktuell 12 % Lessons :
  6 % Events pro Tag).

### Geplant, noch nicht umgesetzt

1. **Planungs-Skill-Wizard** mit Anthropic-Anbindung — größter offener Block.
   Wizard soll u. a. `LessonNote.theme` und `LessonSeriesOverride.display_name`
   programmatisch befüllen können (die Endpunkte stehen schon).
2. **Worksheet-Anknüpfung im Stundenplan-Panel**: „verknüpfte Aufgabenblätter
   zu Klasse+Fach" + „Neues Aufgabenblatt für diese Stunde" als Schnellaktion.
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
├── install.sh                         # Proxmox-Host-Installer
├── lxc-setup.sh                       # Inneres Setup im LXC
├── bin/{drs-update, drs-admin}        # Helper-Skripte im Container
├── systemd/drs-api.service
├── caddy/Caddyfile
├── alembic.ini
├── requirements.txt
└── app/
    ├── main.py
    ├── config.py, db.py, models.py, crypto.py, auth.py, branding.py, cli.py
    ├── templating.py                  # geteilte Jinja-Instanz mit school_name() Global
    ├── alembic/versions/0001–0007_*.py
    ├── routers/
    │   ├── auth.py, setup.py, users.py, profile.py
    │   ├── worksheets.py, settings.py, help.py, timetable.py
    ├── services/
    │   ├── playwright_pdf.py
    │   ├── webuntis_client.py         # inkl. _attach_events, lesson_key_parts
    │   └── ical_client.py             # Europe/Berlin, RRULE-Expansion, 15 min Cache
    ├── static/{drs.css, default_school_logo.jpg}
    └── templates/
        ├── base.html, login.html, change_password.html, home.html, setup.html
        ├── profile.html, help.html, timetable.html, timetable_diagnose.html
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

## 6. Letzte unbestätigte Commits

| Commit | Was |
|---|---|
| `3075461` | Event-Card flex:1 für durchgehenden Balken |
| `c1b2b89` | Tagesspalten zweigeteilt (Lessons + Events Subspalten) |
| `6fefb5e` | Lange Events nicht mehr als rowspan-Lessons-Merge |
| `3c4248e` | Notizen pro Block (block_start im Key) |
| `ca75b08` | Prüfung/Notiz live im Grid, kein roter Hintergrund |
| `0e08cf1` | Fach-Override (Reihe + Sitzung) + Prüfung |

**Bitte vor neuer Session noch im Container `drs-update` ausführen und das
Verhalten des durchgehenden Event-Balkens visuell bestätigen.**

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
