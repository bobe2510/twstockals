#!/usr/bin/env bash
# Droplet → Google Drive：reports/（Droplet 為唯一作者；鏡像同步含刪除）。
# Windows 端由 Google Drive 桌面版自動收下，取代舊的 pull_reports_latest.ps1。
set -euo pipefail

RCLONE="${RCLONE:-/home/brian/.local/bin/rclone}"
WS="${TWSTOCKALS_WORKSPACE:-/home/brian/twstockals}"

exec "$RCLONE" sync "$WS/reports" gdrive:reports \
  --exclude "desktop.ini" \
  --exclude "**/desktop.ini" \
  --timeout 120s --retries 3 --log-level NOTICE
