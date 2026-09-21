#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${1:-main}"

cd "$APP_DIR"

echo "[deploy] app dir: $APP_DIR"
echo "[deploy] pulling origin/$BRANCH"
git pull origin "$BRANCH"

# 기존 100종목 설정만 새 300종목 자동추천 범위로 한 번 마이그레이션합니다.
if [[ -f .env ]] && grep -qx 'MAX_SYMBOLS=100' .env; then
  sed -i 's/^MAX_SYMBOLS=100$/MAX_SYMBOLS=300/' .env
  echo "[deploy] expanded MAX_SYMBOLS from 100 to 300"
fi

echo "[deploy] installing cloudflared when needed"
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH="$(dpkg --print-architecture)"
  case "$ARCH" in
    amd64|arm64) ;;
    *) echo "[deploy] unsupported architecture: $ARCH" >&2; exit 1 ;;
  esac
  CLOUDFLARED_DEB="/tmp/cloudflared-${ARCH}.deb"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb" -o "$CLOUDFLARED_DEB"
  sudo dpkg -i "$CLOUDFLARED_DEB"
fi

echo "[deploy] restarting web app"
pm2 restart stock-web --update-env

echo "[deploy] starting HTTPS tunnel"
mkdir -p data
rm -f data/tunnel-url.txt
if pm2 describe stock-tunnel >/dev/null 2>&1; then
  pm2 restart stock-tunnel --update-env
else
  pm2 start cloudflare_tunnel.py --name stock-tunnel --interpreter "$APP_DIR/venv/bin/python"
fi

for _ in $(seq 1 45); do
  [[ -s data/tunnel-url.txt ]] && break
  sleep 1
done
if [[ ! -s data/tunnel-url.txt ]]; then
  echo "[deploy] HTTPS tunnel URL was not created" >&2
  pm2 logs stock-tunnel --lines 80 --nostream
  exit 1
fi

TUNNEL_URL="$(cat data/tunnel-url.txt)"
echo "[deploy] HTTPS dashboard: $TUNNEL_URL"
# stock-tunnel updates .env and restarts stock-bot when its URL changes.
pm2 save

echo "[deploy] verifying HTTPS tunnel"
curl -fsS --connect-timeout 10 --max-time 90 -o /dev/null "$TUNNEL_URL/docs"

echo "[deploy] PM2 status"
pm2 status
