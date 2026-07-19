#!/usr/bin/env bash
# 安裝季度再驗證 timer（需 sudo）：
#   cd /home/brian/twstockals && sudo bash deploy/droplet/install_research_timer.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
cp "$SRC/twstockals-research-quarterly.service" "$SRC/twstockals-research-quarterly.timer" /etc/systemd/system/
chmod +x "$SRC/quarterly_research.sh"
systemctl daemon-reload
systemctl enable --now twstockals-research-quarterly.timer
systemctl list-timers 'twstockals-research-*' --no-pager
echo "手動試跑：sudo systemctl start twstockals-research-quarterly.service"
