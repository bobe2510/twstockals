#!/usr/bin/env bash
# Install systemd ingest + alert timers for user brian.
set -euo pipefail

WS="${TWSTOCKALS_WORKSPACE:-/home/brian/twstockals}"
RUN_USER="${TWSTOCKALS_USER:-brian}"
UNIT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYS=/etc/systemd/system

if [[ ! -d "$WS" ]]; then
  echo "TWSTOCKALS_WORKSPACE not found: $WS" >&2
  exit 1
fi

sudo cp "$UNIT_DIR/twstockals-ingest@.service" "$SYS/"
sudo cp "$UNIT_DIR/twstockals-alert@.service" "$SYS/"
sudo sed -i "s|/home/brian/twstockals|$WS|g" "$SYS/twstockals-ingest@.service"
sudo sed -i "s|/home/brian/twstockals|$WS|g" "$SYS/twstockals-alert@.service"
sudo sed -i "s/^User=.*/User=$RUN_USER/" "$SYS/twstockals-ingest@.service"
sudo sed -i "s/^Group=.*/Group=$RUN_USER/" "$SYS/twstockals-ingest@.service"
sudo sed -i "s/^User=.*/User=$RUN_USER/" "$SYS/twstockals-alert@.service"
sudo sed -i "s/^Group=.*/Group=$RUN_USER/" "$SYS/twstockals-alert@.service"

for t in tw-eod us-eod fx-gold crypto; do
  sudo cp "$UNIT_DIR/twstockals-ingest-${t}.timer" "$SYS/"
done
sudo cp "$UNIT_DIR/twstockals-ingest-health.service" "$SYS/"
sudo cp "$UNIT_DIR/twstockals-ingest-health.timer" "$SYS/"
sudo sed -i "s|/home/brian/twstockals|$WS|g" "$SYS/twstockals-ingest-health.service"
sudo sed -i "s/^User=.*/User=$RUN_USER/" "$SYS/twstockals-ingest-health.service"
sudo sed -i "s/^Group=.*/Group=$RUN_USER/" "$SYS/twstockals-ingest-health.service"

for t in digest-am digest-close digest-pm close-confirm close-confirm-backup scan-bg; do
  sudo cp "$UNIT_DIR/twstockals-alert-${t}.timer" "$SYS/"
done

sudo systemctl daemon-reload

for u in \
  twstockals-ingest-tw-eod.timer \
  twstockals-ingest-us-eod.timer \
  twstockals-ingest-fx-gold.timer \
  twstockals-ingest-crypto.timer \
  twstockals-ingest-health.timer \
  twstockals-alert-digest-am.timer \
  twstockals-alert-digest-close.timer \
  twstockals-alert-digest-pm.timer \
  twstockals-alert-close-confirm.timer \
  twstockals-alert-close-confirm-backup.timer \
  twstockals-alert-scan-bg.timer
do
  sudo systemctl enable --now "$u"
done

echo "Installed. Timers:"
systemctl list-timers 'twstockals-*' --no-pager || true
