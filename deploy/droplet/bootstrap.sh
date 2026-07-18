#!/usr/bin/env bash
# First-time setup on Droplet as user brian (or TWSTOCKALS_USER).
# Usage:
#   bash deploy/droplet/bootstrap.sh
#   # or after rsync/git already placed the repo at ~/twstockals
set -euo pipefail

USER_NAME="${TWSTOCKALS_USER:-brian}"
WS="${TWSTOCKALS_WORKSPACE:-$HOME/twstockals}"

echo "== timezone Asia/Taipei =="
sudo timedatectl set-timezone Asia/Taipei || true

echo "== apt packages =="
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv python3-pip git curl ca-certificates

echo "== workspace $WS =="
mkdir -p "$WS"
cd "$WS"

if [[ ! -f "$WS/requirements.txt" ]]; then
  echo "ERROR: $WS/requirements.txt missing."
  echo "先把專案放到 $WS（git clone 或本機 rsync），再重跑本腳本。"
  exit 1
fi

echo "== venv =="
if [[ ! -x "$WS/.venv/bin/python" ]]; then
  python3 -m venv "$WS/.venv"
fi
# shellcheck disable=SC1091
source "$WS/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$WS/requirements.txt"

mkdir -p "$WS/reports/latest" "$WS/reports/history" \
  "$WS/market_crawled_cache/warehouse" "$WS/config"

if [[ ! -f "$WS/config/api_keys.json" ]]; then
  if [[ -f "$WS/config/api_keys.example.json" ]]; then
    cp "$WS/config/api_keys.example.json" "$WS/config/api_keys.json"
    echo "Created config/api_keys.json from example — 請填入 FINMIND_TOKENS / TELEGRAM_*"
  else
    echo "WARN: no api_keys.json yet"
  fi
fi

echo "== smoke import =="
cd "$WS"
TWSTOCKALS_WORKSPACE="$WS" "$WS/.venv/bin/python" -c "import FinMind, pandas; print('ok', FinMind.__version__ if hasattr(FinMind,'__version__') else 'FinMind')"

echo
echo "Bootstrap done."
echo "Next:"
echo "  1) 編輯 $WS/config/api_keys.json（勿 commit）"
echo "  2) 確認 $WS/config/my_targets.json 存在"
echo "  3) sudo TWSTOCKALS_WORKSPACE=$WS TWSTOCKALS_USER=$USER_NAME bash $WS/deploy/droplet/install_timers.sh"
echo "  4) 手動測：cd $WS && .venv/bin/python src_scripts/run_ingest.py --job crypto --no-notify"
