#!/usr/bin/env bash
# 季度 walk-forward 再驗證：重跑全部回測 → 規則健康檢查（劣化推播）。
# 由 twstockals-research-quarterly.timer 觸發；手動：
#   cd /home/brian/twstockals && bash deploy/droplet/quarterly_research.sh
set -uo pipefail

WS="${TWSTOCKALS_WORKSPACE:-/home/brian/twstockals}"
PY="$WS/.venv/bin/python"
[ -x "$PY" ] || PY=python3
cd "$WS"

echo "=== quarterly research $(date -Is) ==="
FAILED=""
for s in \
  research/run_voltarget_backtest.py \
  research/run_exit_rule_backtest.py \
  research/run_gold_sleeve_backtest.py \
  research/run_trend_exit_backtest.py \
  research/run_rebalance_band_backtest.py \
  "research/run_grade_threshold_backtest.py --costs real" \
; do
  echo "--- run $s ---"
  # shellcheck disable=SC2086
  if ! $PY src_scripts/$s; then
    FAILED="$FAILED $s"
    echo "!!! $s failed, continuing"
  fi
done

echo "--- rule health check ---"
$PY src_scripts/research/check_rule_health.py || FAILED="$FAILED check_rule_health"

if [ -n "$FAILED" ]; then
  echo "quarterly research finished with failures:$FAILED"
  exit 1
fi
echo "quarterly research done"
