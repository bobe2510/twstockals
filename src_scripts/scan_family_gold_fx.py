# -*- coding: utf-8 -*-
"""
家人帳（只黃金＋美金）掃描入口。

預設：寫報告、不推 Telegram（避免跟主帳洗版）。加 --notify 才推播。

  python src_scripts/scan_family_gold_fx.py
  python src_scripts/scan_family_gold_fx.py --force --day
  python src_scripts/scan_family_gold_fx.py --notify
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "src_scripts")
OUT_DIR = os.path.join(ROOT, "reports", "latest", "family_gold_fx")
TARGETS = os.path.join(ROOT, "config", "family_gold_fx_targets.json")
POLICY = os.path.join(ROOT, "config", "family_gold_fx_policy.json")
LADDER = os.path.join(OUT_DIR, "deploy_ladder_state.json")
REPORT = os.path.join(OUT_DIR, "multi_asset_levels.md")
STATE_MD = os.path.join(OUT_DIR, "CURRENT_STATE.md")
HOLDINGS = os.path.join(OUT_DIR, "holdings.json")


def write_state() -> None:
    with open(TARGETS, "r", encoding="utf-8") as f:
        t = json.load(f)
    multi = t.get("multi_asset") or {}
    gold = multi.get("gold_passbook") or {}
    fx = multi.get("forex_usd") or {}
    cash = int(multi.get("deployable_cash_twd") or 0)
    lines = [
        "# 家人帳現行狀態（黃金／美金 only）\n\n",
        f"來源：`config/family_gold_fx_targets.json`  \n\n",
        "## 持倉\n\n",
        f"* 黃金：**{gold.get('qty')}** 公克  \n",
        f"* 美金：**{fx.get('qty')}**（約 {fx.get('approx_twd')} 元｜as_of {fx.get('as_of')}）  \n",
        f"* 可再投入現金：**{cash:,}** 元  \n\n",
        "## 規則摘要\n\n",
        "* 黃金 ≥B → 允許買進（袖口約 12 萬／預算 30 萬）  \n",
        "* 美金 ≥A → 允許囤匯（袖口約 5 萬）；乖離年線 ≥+1.5% → 建議減約 10 萬一袖  \n",
        "* 不做台股／美股／加密  \n",
        "* 成交後跟主帳一樣：跟我匯報 → 改 targets／ladder → push  \n\n",
        f"報告：[`multi_asset_levels.md`](multi_asset_levels.md)  \n",
    ]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE_MD, "w", encoding="utf-8") as f:
        f.writelines(lines)
    doc = {
        "profile": "family_gold_fx",
        "gold_g": gold.get("qty"),
        "usd": fx.get("qty"),
        "deployable_cash_twd": cash,
        "as_of_fx": fx.get("as_of"),
    }
    with open(HOLDINGS, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"寫入 {STATE_MD}")


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--notify", "--with-crypto")]
    do_notify = "--notify" in sys.argv
    with_crypto = "--with-crypto" in sys.argv
    if "--force" not in args:
        args.append("--force")
    if "--day" not in args:
        args.append("--day")
    # 家人帳預設不掃加密；需要時才 --with-crypto
    if not with_crypto and "--skip-btc" not in args:
        args.append("--skip-btc")

    env = os.environ.copy()
    env["TWSTOCKALS_WORKSPACE"] = ROOT
    env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
    env["TWSTOCKALS_TARGETS"] = TARGETS
    env["TWSTOCKALS_POLICY"] = POLICY
    env["TWSTOCKALS_LADDER_STATE"] = LADDER
    env["TWSTOCKALS_MULTI_REPORT"] = REPORT
    # 預設不推播；要推才開
    if not do_notify:
        env["NOTIFY_DRY_RUN"] = "true"
        env.pop("TWSTOCKALS_BATCH_NOTIFY", None)

    os.makedirs(OUT_DIR, exist_ok=True)
    write_state()
    cmd = [sys.executable, os.path.join(SCRIPTS, "scan_multi_asset.py"), *args]
    print(f"=== family_gold_fx RUN {' '.join(args)} notify={do_notify} ===")
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    print(f"=== EXIT code={proc.returncode} report={REPORT} ===")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
