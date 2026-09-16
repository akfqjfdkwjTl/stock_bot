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

echo "[deploy] restarting PM2 apps"
pm2 restart stock-bot --update-env
pm2 restart stock-web --update-env

echo "[deploy] PM2 status"
pm2 status
