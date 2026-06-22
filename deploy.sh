#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${1:-main}"

cd "$APP_DIR"

echo "[deploy] app dir: $APP_DIR"
echo "[deploy] pulling origin/$BRANCH"
git pull origin "$BRANCH"

echo "[deploy] restarting PM2 apps"
pm2 restart stock-bot --update-env
pm2 restart stock-web --update-env

echo "[deploy] PM2 status"
pm2 status

