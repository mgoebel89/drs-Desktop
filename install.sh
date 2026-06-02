#!/usr/bin/env bash
# DRS Unterrichtsmaterial-System — Proxmox-Host Installer
# Erstellt einen unprivileged Debian-12-LXC und richtet die Anwendung ein.
#
# Aufruf auf Proxmox-Host:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/<USER>/drs-lxc/main/install.sh)"

set -euo pipefail

# ─── Konfiguration: Git-Repo + Branch ─────────────────────────────────────
GIT_REPO="${DRS_REPO:-https://github.com/mgoebel89/drs-Desktop.git}"
GIT_BRANCH="${DRS_BRANCH:-main}"

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
msg()   { printf "${BLU}==>${NC} %s\n" "$*"; }
ok()    { printf "${GRN}✓${NC}  %s\n" "$*"; }
warn()  { printf "${YLW}!${NC}  %s\n" "$*"; }
die()   { printf "${RED}✗${NC}  %s\n" "$*" >&2; exit 1; }
ask()   {
  local prompt="$1" default="${2:-}"
  local input
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " input
    echo "${input:-$default}"
  else
    read -r -p "$prompt: " input
    echo "$input"
  fi
}
ask_pw() {
  local prompt="$1" pw pw2
  while true; do
    read -r -s -p "$prompt: " pw; echo
    read -r -s -p "Wiederholen: " pw2; echo
    [[ "$pw" == "$pw2" ]] || { warn "Stimmen nicht überein."; continue; }
    [[ ${#pw} -ge 10 ]] || { warn "Mindestens 10 Zeichen."; continue; }
    echo "$pw"; return
  done
}

# ─── Vorprüfungen ─────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."
command -v pct >/dev/null 2>&1 || die "Dieses Skript läuft nur auf einem Proxmox-VE-Host (pct fehlt)."

cat <<EOF
${BLU}╔════════════════════════════════════════════════════════════╗
║  DRS Unterrichtsmaterial-System · Proxmox LXC Installer  ║
╚════════════════════════════════════════════════════════════╝${NC}

Dieses Skript erstellt einen unprivileged Debian-12-LXC und installiert
das DRS-System darin. Du wirst nach Container-Parametern und einem
Admin-Account gefragt.

EOF

# ─── Eingaben ─────────────────────────────────────────────────────────────
CTID="$(ask "Container-ID" "200")"
[[ "$CTID" =~ ^[0-9]+$ ]] || die "CTID muss numerisch sein."
pct status "$CTID" >/dev/null 2>&1 && die "Container $CTID existiert bereits."

HOSTNAME="$(ask "Hostname" "drs")"
DISK_SIZE="$(ask "Disk-Größe (GB)" "8")"
RAM_MB="$(ask "RAM (MB)" "2048")"
CORES="$(ask "CPU-Kerne" "2")"
BRIDGE="$(ask "Netzwerk-Bridge" "vmbr0")"
NET_CFG="$(ask "Netzwerk (dhcp oder z.B. 192.168.1.50/24,gw=192.168.1.1)" "dhcp")"
STORAGE="$(ask "Storage" "local-lvm")"
TEMPLATE_STORAGE="$(ask "Template-Storage (für CT-Template)" "local")"

msg "Suche Debian-12-Template …"
TEMPLATE=$(pveam available | awk '/debian-12.*standard/{print $2}' | sort -V | tail -1)
[[ -n "$TEMPLATE" ]] || die "Kein Debian-12-Standard-Template in pveam available gefunden."

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  msg "Lade Template $TEMPLATE in $TEMPLATE_STORAGE …"
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi
TEMPLATE_REF="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}"

# Admin-Account wird nach dem Boot über die Web-UI angelegt (First-Run-Setup).

# ─── Netzwerk-String zusammenbauen ────────────────────────────────────────
if [[ "$NET_CFG" == "dhcp" ]]; then
  NET="name=eth0,bridge=${BRIDGE},ip=dhcp,ip6=auto"
else
  NET="name=eth0,bridge=${BRIDGE},ip=${NET_CFG}"
fi

# ─── Container erstellen ──────────────────────────────────────────────────
msg "Erstelle Container CT $CTID …"
pct create "$CTID" "$TEMPLATE_REF" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" \
  --memory "$RAM_MB" \
  --swap 512 \
  --rootfs "${STORAGE}:${DISK_SIZE}" \
  --net0 "$NET" \
  --unprivileged 1 \
  --features "nesting=1" \
  --onboot 1 \
  --start 0
ok "Container erstellt."

msg "Starte Container …"
pct start "$CTID"
sleep 5

# ─── Setup-Skript ins Container kopieren ──────────────────────────────────
msg "Lade Setup-Skript in Container …"
TMPFILE=$(mktemp)
trap "rm -f $TMPFILE" EXIT

curl -fsSL "${GIT_REPO%.git}/raw/${GIT_BRANCH}/lxc-setup.sh" -o "$TMPFILE" 2>/dev/null \
  || curl -fsSL "$(echo "$GIT_REPO" | sed 's|github.com|raw.githubusercontent.com|; s|\.git$||')/${GIT_BRANCH}/lxc-setup.sh" -o "$TMPFILE" \
  || die "lxc-setup.sh konnte nicht geladen werden. Prüfe GIT_REPO/GIT_BRANCH."

pct push "$CTID" "$TMPFILE" /root/lxc-setup.sh
pct exec "$CTID" -- chmod +x /root/lxc-setup.sh

# ─── Setup-Skript im Container ausführen ──────────────────────────────────
msg "Führe Setup im Container aus (dauert einige Minuten) …"
pct exec "$CTID" -- env \
  DRS_REPO="$GIT_REPO" \
  DRS_BRANCH="$GIT_BRANCH" \
  bash /root/lxc-setup.sh

# ─── Container-IP ermitteln ───────────────────────────────────────────────
CT_IP=$(pct exec "$CTID" -- bash -c "hostname -I | awk '{print \$1}'" 2>/dev/null || echo "?")

cat <<EOF

${GRN}╔════════════════════════════════════════════════════════════╗
║  Fertig.                                                   ║
╚════════════════════════════════════════════════════════════╝${NC}

  CT-ID:       $CTID
  Hostname:    $HOSTNAME
  IP:          $CT_IP

  → Öffne im Browser:  http://$CT_IP/
     Die Seite führt dich durch die Anlage des ersten Admin-Accounts.

  Update:      pct exec $CTID -- /usr/local/sbin/drs-update
  Logs:        pct exec $CTID -- journalctl -u drs-api -f
  Shell:       pct enter $CTID

EOF
