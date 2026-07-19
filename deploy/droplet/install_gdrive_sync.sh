#!/usr/bin/env bash
# 安裝 Google Drive 雙向同步 timers（需 sudo）。
#   cd /home/brian/twstockals && sudo bash deploy/droplet/install_gdrive_sync.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"

for u in twstockals-gdrive-pull twstockals-gdrive-push; do
  cp "$SRC/$u.service" "$SRC/$u.timer" /etc/systemd/system/
done
chmod +x "$SRC/gdrive_pull_code.sh" "$SRC/gdrive_push_reports.sh"

systemctl daemon-reload
systemctl enable --now twstockals-gdrive-pull.timer twstockals-gdrive-push.timer

echo "--- installed ---"
systemctl list-timers 'twstockals-gdrive-*' --no-pager
echo
echo "煙測（可立即手動觸發一次）："
echo "  sudo systemctl start twstockals-gdrive-push.service && journalctl -u twstockals-gdrive-push -n 20 --no-pager"
