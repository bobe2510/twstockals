#!/usr/bin/env bash
# Droplet → Google Drive：reports/（Droplet 為唯一作者；鏡像同步含刪除）。
# Windows 端由 Google Drive 桌面版自動收下，取代舊的 pull_reports_latest.ps1。
set -euo pipefail

RCLONE="${RCLONE:-/home/brian/.local/bin/rclone}"
WS="${TWSTOCKALS_WORKSPACE:-/home/brian/twstockals}"

# backtest 子目錄兩邊都會寫（本機研究＋Droplet 季度再驗證）→ 合併不鏡像，
# 避免鏡像刪除把對方作者的報告砍掉（2026-07-19 事故）。其餘 reports/ 嚴格鏡像。
"$RCLONE" sync "$WS/reports" gdrive:reports \
  --exclude "desktop.ini" \
  --exclude "**/desktop.ini" \
  --exclude "latest/backtest/**" \
  --timeout 120s --retries 3 --log-level NOTICE

exec "$RCLONE" copy --update "$WS/reports/latest/backtest" gdrive:reports/latest/backtest \
  --exclude "desktop.ini" \
  --timeout 120s --retries 3 --log-level NOTICE
