#!/usr/bin/env bash
# Google Drive → Droplet：程式與設定（Windows 為唯一作者；鏡像同步含刪除）。
# reports/ 由 Droplet 作者，走反向的 gdrive_push_reports.sh，兩邊路徑不相交。
set -euo pipefail

RCLONE="${RCLONE:-/home/brian/.local/bin/rclone}"
WS="${TWSTOCKALS_WORKSPACE:-/home/brian/twstockals}"

exec "$RCLONE" sync gdrive: "$WS" \
  --exclude "reports/**" \
  --exclude ".git/**" \
  --exclude ".venv/**" \
  --exclude ".claude/**" \
  --exclude "__pycache__/**" \
  --exclude "**/__pycache__/**" \
  --exclude "market_crawled_cache/**" \
  --exclude "desktop.ini" \
  --exclude "**/desktop.ini" \
  --exclude "config/twstockals-sync-*.json" \
  --exclude "*.pyc" \
  --timeout 120s --retries 3 --log-level NOTICE
