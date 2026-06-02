# DRS Unterrichtsmaterial-System

Lehrer-Plattform für die David-Roentgen-Schule Neuwied: Konfigurationstool für
Arbeitsblätter, HTML-/PDF-Export für Moodle und Druck, Multi-User mit Login,
KI-gestützter Planungs-Skill (folgt) und WebUntis-Anbindung (folgt). Läuft im
Proxmox-LXC, Installation und Updates aus Git.

---

## Installation auf Proxmox

Auf dem **Proxmox-VE-Host** (nicht in einem bestehenden Container) als root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/drs-Desktop/main/install.sh)"
```

Das Skript fragt nach:
- Container-ID, Hostname, Disk-Größe, RAM, Cores
- Netzwerk (Bridge, DHCP oder feste IP)
- Storage und Template-Storage
- Admin-Benutzername + Initial-Passwort für die Web-UI

Dann:
1. Lädt ggf. das Debian-12-Template
2. Erstellt einen **unprivileged LXC**
3. Installiert Python, Caddy, Playwright/Chromium, App-Code und Dienste
4. Legt den Admin-Account in der DB an
5. Startet `drs-api` (FastAPI) und `caddy` (Reverse Proxy auf Port 80)

Nach Abschluss zeigt das Skript die Container-IP und die Login-URL.

### Alternativer Repo / Branch

```bash
DRS_REPO="https://github.com/<fork>/drs-lxc.git" \
DRS_BRANCH="develop" \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/<fork>/drs-lxc/develop/install.sh)"
```

---

## Update

Im Container (per `pct exec` vom Host oder `pct enter` als Shell):

```bash
drs-update
```

Macht `git pull`, installiert neue Dependencies, fährt DB-Migrationen,
aktualisiert systemd-Unit und Caddyfile, startet die Dienste neu.

---

## Admin-Operationen im Container

```bash
drs-admin list-users
drs-admin create-admin -u jens -n "Jens Beispiel" -p "Initial1234"
drs-admin reset-password jens         # Notfall: PW interaktiv setzen
```

Logs:
```bash
journalctl -u drs-api -f
```

---

## Sicherheit

- Auth per Username + Passwort (Argon2id), Sessions als HTTP-only Cookie (30 Tage).
- Pro Nutzer ein eigener Anthropic-API-Key — verschlüsselt (AES-GCM) in der DB.
- WebUntis-Credentials pro Nutzer ebenfalls verschlüsselt.
- Master-Key liegt in `/etc/drs/secret.key` (chmod 0640, root:drs).
- Rate-Limiting auf Login: 5 Fehlversuche → 15 Min Sperre.
- Audit-Log in der DB (Logins, Account-Operationen, Worksheet-Aktionen, Exporte).

**Wichtig:** Standard-Konfig liefert HTTP auf Port 80 (Schul-LAN intern).
HTTPS mit self-signed Cert ist im [Caddyfile](caddy/Caddyfile) als Kommentarblock
vorbereitet — bei externer Erreichbarkeit aktivieren.

---

## Datenablage

| Pfad | Inhalt |
|---|---|
| `/opt/drs/app/` | Geklonter Git-Stand der App |
| `/opt/drs/data/drs.sqlite` | SQLite-DB (Nutzer, Worksheets, Audit-Log) |
| `/opt/drs/playwright/` | Chromium für PDF-Export |
| `/etc/drs/config.env` | App-Konfig (Env-Vars) |
| `/etc/drs/secret.key` | AES-Master-Key (chmod 0640) |
| `/var/log/caddy/drs.log` | HTTP-Zugriffsprotokoll |

Optional: `/opt/drs/data` per Bind-Mount auf ein NFS-Volume legen (Proxmox-LXC
Mount Point `mp0`), dann liegen Backups automatisch außerhalb des Containers.

---

## Lokale Entwicklung (Windows/Linux)

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1     # Windows
# . .venv/bin/activate           # Linux/macOS
pip install -r requirements.txt
playwright install chromium

# Master-Key für lokale DB
set DRS_SECRET_KEY=dev-only-change-me-dev-only-change   # Windows cmd
# $env:DRS_SECRET_KEY="..."                              # PowerShell
# export DRS_SECRET_KEY=...                              # bash

alembic upgrade head
python -m app.cli create-admin -u admin -n "Markus Goebel" -p "lokal12345"

uvicorn app.main:app --reload
```

Browser → `http://localhost:8000`, Login `admin / lokal12345`.

---

## Status

| Modul | Status |
|---|---|
| Multi-User-Auth + Admin | ✓ |
| Konfigurationstool (Editor + Revisionen) | ✓ |
| HTML-Export (Moodle-fertig, ohne KI) | ✓ |
| PDF-Export (Playwright) | ✓ |
| LXC-Installer + Update | ✓ |
| Planungs-Skill-Wizard (Anthropic) | offen |
| WebUntis-Anbindung | offen |
| Visual-Editor für Vorlagen | offen |
| HTTPS-Default | optional |
