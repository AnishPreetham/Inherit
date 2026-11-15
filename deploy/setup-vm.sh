#!/usr/bin/env bash
# Set up Inherit in full mode on a fresh Ubuntu 22.04/24.04 VM.
#
# Run from the project directory on the VM (after copying or cloning it there):
#   sudo bash deploy/setup-vm.sh                  # serve on http://<vm-ip>/
#   sudo bash deploy/setup-vm.sh your.domain.com  # serve on https://your.domain.com (automatic TLS)
#
# Safe to re-run: it updates the images and restarts the app.
set -euo pipefail

DOMAIN="${1:-}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/setup-vm.sh [domain]" >&2
  exit 1
fi
if [[ ! -f docker-compose.yml || ! -d inherit ]]; then
  echo "Run this from the Inherit project directory." >&2
  exit 1
fi

echo "==> Installing Docker Engine and the Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "==> Preparing directories and configuration"
mkdir -p /srv/inherit/tmp /srv/inherit/runs
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "    Created .env from .env.example. Add your Nebius values to it, then re-run this script."
  echo "    Until then the app uses the offline mock model."
fi

echo "==> Building images (sandbox + app)"
docker compose build

echo "==> Starting the app"
if [[ -n "$DOMAIN" ]]; then
  # app only on localhost; Caddy terminates TLS on 80/443
  LOCAL_PORT=8000
  INHERIT_PORT="127.0.0.1:${LOCAL_PORT}" docker compose up -d app
else
  LOCAL_PORT=80
  INHERIT_PORT="${LOCAL_PORT}" docker compose up -d app
fi

if [[ -n "$DOMAIN" ]]; then
  echo "==> Installing Caddy for HTTPS on ${DOMAIN}"
  if ! command -v caddy >/dev/null 2>&1; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
      | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
      > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
  fi
  cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN} {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
EOF
  systemctl reload caddy || systemctl restart caddy
fi

echo "==> Waiting for the app to answer"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${LOCAL_PORT}/api/config" >/dev/null 2>&1; then
    echo
    echo "Inherit is running."
    if [[ -n "$DOMAIN" ]]; then
      echo "  URL: https://${DOMAIN}/  (DNS for ${DOMAIN} must point at this VM)"
    else
      echo "  URL: http://$(curl -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')/"
    fi
    echo "  Logs:    docker compose logs -f app"
    echo "  Restart: sudo bash deploy/setup-vm.sh ${DOMAIN}"
    exit 0
  fi
  sleep 2
done
echo "The app did not respond in time. Check: docker compose logs app" >&2
exit 1
