#!/usr/bin/env bash
# Innerer Setup-Schritt: läuft im LXC und richtet App + Dienste ein.
# Wird vom install.sh aufgerufen. Erwartete Env-Variablen:
#   DRS_REPO, DRS_BRANCH, DRS_ADMIN_USER, DRS_ADMIN_NAME, DRS_ADMIN_PW
set -euo pipefail

: "${DRS_REPO:?DRS_REPO fehlt}"
: "${DRS_BRANCH:=main}"
: "${DRS_ADMIN_USER:?DRS_ADMIN_USER fehlt}"
: "${DRS_ADMIN_NAME:=}"
: "${DRS_ADMIN_PW:?DRS_ADMIN_PW fehlt}"

APP_DIR=/opt/drs/app
VENV_DIR=/opt/drs/venv
DATA_DIR=/opt/drs/data
BIN_DIR=/opt/drs/bin
CFG_DIR=/etc/drs

msg() { printf "==> %s\n" "$*"; }

# ─── 1) System-Pakete ─────────────────────────────────────────────────────
msg "apt update + Pakete"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-dev \
  build-essential pkg-config libffi-dev libssl-dev \
  git curl ca-certificates \
  debian-keyring debian-archive-keyring apt-transport-https gnupg \
  sqlite3

# Caddy (offizielles Repo)
if ! command -v caddy >/dev/null 2>&1; then
  msg "Installiere Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  # Die deb.txt von Cloudsmith enthält bereits signed-by — nicht erneut umschreiben.
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi

# ─── 2) Service-User + Verzeichnisse ──────────────────────────────────────
msg "Lege Service-User 'drs' und Verzeichnisstruktur an"
id -u drs >/dev/null 2>&1 || useradd --system --home /opt/drs --shell /usr/sbin/nologin drs
install -d -o drs -g drs -m 0755 /opt/drs "$APP_DIR" "$DATA_DIR" "$BIN_DIR"
install -d -o root -g root -m 0750 "$CFG_DIR"

# ─── 3) Master-Key generieren (falls noch nicht vorhanden) ────────────────
if [[ ! -f "$CFG_DIR/secret.key" ]]; then
  msg "Generiere /etc/drs/secret.key"
  python3 -c "import secrets,sys; sys.stdout.write(secrets.token_hex(32))" > "$CFG_DIR/secret.key"
  chmod 0640 "$CFG_DIR/secret.key"
  chown root:drs "$CFG_DIR/secret.key"
fi

# ─── 4) Code holen ────────────────────────────────────────────────────────
msg "Klone Repository ($DRS_REPO @ $DRS_BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
  runuser -u drs -- git -C "$APP_DIR" fetch --depth 1 origin "$DRS_BRANCH"
  runuser -u drs -- git -C "$APP_DIR" reset --hard "origin/$DRS_BRANCH"
else
  # rm -rf, da der Verzeichnisbesitzer drs ist (Verzeichnis zuvor angelegt)
  find "$APP_DIR" -mindepth 1 -delete 2>/dev/null || true
  runuser -u drs -- git clone --depth 1 -b "$DRS_BRANCH" "$DRS_REPO" "$APP_DIR"
fi

# ─── 5) Python venv + Dependencies ────────────────────────────────────────
msg "Erstelle venv und installiere Python-Dependencies"
runuser -u drs -- python3 -m venv "$VENV_DIR"
runuser -u drs -- "$VENV_DIR/bin/pip" install --upgrade pip -q
runuser -u drs -- "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# ─── 6) Playwright + Chromium ─────────────────────────────────────────────
msg "Installiere Chromium für Playwright (~250 MB)"
install -d -o drs -g drs -m 0755 /opt/drs/playwright
runuser -u drs -- env PLAYWRIGHT_BROWSERS_PATH=/opt/drs/playwright \
  "$VENV_DIR/bin/playwright" install chromium
# System-Deps für Chromium (als root)
PLAYWRIGHT_BROWSERS_PATH=/opt/drs/playwright \
  "$VENV_DIR/bin/playwright" install-deps chromium

# ─── 7) Konfig-Env schreiben ──────────────────────────────────────────────
msg "Schreibe /etc/drs/config.env"
SECRET_HEX="$(cat "$CFG_DIR/secret.key")"
cat > "$CFG_DIR/config.env" <<EOF
DRS_SECRET_KEY=$SECRET_HEX
DRS_DATA_DIR=/opt/drs/data
DRS_DB_URL=sqlite:////opt/drs/data/drs.sqlite
DRS_BIND_HOST=127.0.0.1
DRS_BIND_PORT=8000
PLAYWRIGHT_BROWSERS_PATH=/opt/drs/playwright
EOF
chmod 0640 "$CFG_DIR/config.env"
chown root:drs "$CFG_DIR/config.env"

# Symlink, damit alembic.ini relative Pfade funktionieren
ln -sfn "$DATA_DIR" "$APP_DIR/data"

# ─── 8) DB migrieren ──────────────────────────────────────────────────────
msg "Alembic migration"
runuser -u drs -- env $(grep -v '^#' "$CFG_DIR/config.env" | xargs) \
  "$VENV_DIR/bin/alembic" -c "$APP_DIR/alembic.ini" upgrade head

# ─── 9) Admin-Account ─────────────────────────────────────────────────────
msg "Lege Admin-Account '$DRS_ADMIN_USER' an"
runuser -u drs -- env $(grep -v '^#' "$CFG_DIR/config.env" | xargs) \
  bash -c "cd $APP_DIR && $VENV_DIR/bin/python -m app.cli create-admin -u '$DRS_ADMIN_USER' -n '$DRS_ADMIN_NAME' -p '$DRS_ADMIN_PW'" || \
  msg "Hinweis: Falls Admin schon existiert, wurde keine Aktion ausgeführt."

# ─── 10) systemd-Unit + Caddyfile installieren ────────────────────────────
msg "Installiere systemd-Unit + Caddy-Konfig"
install -m 0644 "$APP_DIR/systemd/drs-api.service" /etc/systemd/system/drs-api.service
install -m 0644 "$APP_DIR/caddy/Caddyfile" /etc/caddy/Caddyfile
mkdir -p /var/log/caddy

systemctl daemon-reload
systemctl enable --now drs-api
systemctl reload caddy || systemctl restart caddy

# ─── 11) Helper-Skripte ───────────────────────────────────────────────────
msg "Installiere drs-update und drs-admin"
install -m 0755 "$APP_DIR/bin/drs-update" /usr/local/sbin/drs-update
install -m 0755 "$APP_DIR/bin/drs-admin" /usr/local/sbin/drs-admin

msg "Setup abgeschlossen."
