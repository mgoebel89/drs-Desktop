#!/usr/bin/env bash
# DRS · OnlyOffice Document Server — Setup im LXC
# Wird vom Host-Installer in den OnlyOffice-LXC gepusht und ausgeführt.
#
# Erwartete Env-Variablen:
#   OO_JWT_SECRET   — JWT-Secret (wird vom Host-Installer generiert)
#
# Bringt:
#   - Docker CE
#   - onlyoffice/documentserver:latest auf Port 80 → mapped auf Host-Port 80
#   - JWT zwingend aktiv
#   - systemd-Unit `onlyoffice` für persistenten Container

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[0;34m'; NC='\033[0m'
msg()  { printf "${BLU}==>${NC} %s\n" "$*"; }
ok()   { printf "${GRN}✓${NC}  %s\n" "$*"; }
die()  { printf "${RED}✗${NC}  %s\n" "$*" >&2; exit 1; }

[[ -n "${OO_JWT_SECRET:-}" ]] || die "OO_JWT_SECRET nicht gesetzt."

export DEBIAN_FRONTEND=noninteractive

msg "System aktualisieren …"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg lsb-release

msg "Docker-CE installieren …"
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io
systemctl enable --now docker
ok "Docker bereit."

msg "OnlyOffice-Datenverzeichnisse anlegen …"
mkdir -p /var/lib/onlyoffice/{data,lib,logs,db}
mkdir -p /etc/drs
echo -n "$OO_JWT_SECRET" > /etc/drs/onlyoffice.jwt
chmod 0640 /etc/drs/onlyoffice.jwt

msg "OnlyOffice-Image ziehen (kann mehrere Minuten dauern) …"
docker pull onlyoffice/documentserver:latest

# Alten Container entfernen falls vorhanden (idempotent)
if docker ps -a --format '{{.Names}}' | grep -q '^onlyoffice$'; then
  msg "Vorhandenen Container entfernen …"
  docker rm -f onlyoffice >/dev/null
fi

msg "OnlyOffice-Container starten …"
docker run -d --restart=always --name onlyoffice \
  -p 80:80 \
  -e JWT_ENABLED=true \
  -e JWT_SECRET="$OO_JWT_SECRET" \
  -e JWT_HEADER=Authorization \
  -v /var/lib/onlyoffice/data:/var/www/onlyoffice/Data \
  -v /var/lib/onlyoffice/lib:/var/lib/onlyoffice \
  -v /var/lib/onlyoffice/logs:/var/log/onlyoffice \
  -v /var/lib/onlyoffice/db:/var/lib/postgresql \
  onlyoffice/documentserver:latest
ok "Container läuft."

msg "Warte auf Healthcheck …"
for i in {1..60}; do
  if curl -fsS http://127.0.0.1/healthcheck 2>/dev/null | grep -q true; then
    ok "OnlyOffice antwortet."
    exit 0
  fi
  sleep 5
done
die "Healthcheck nach 5 Minuten nicht erfolgreich. Logs: docker logs onlyoffice"
