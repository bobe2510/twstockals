# -*- coding: utf-8 -*-
"""
Unified alert runner for cloud / local cron.

Modes:
  --mode all            black_swan + close_confirm + position_levels + multi_asset
  --mode intraday       black_swan only（大盤／匯率／反1；不推個股破防守）
  --mode close_confirm  ~13:10 近收盤確認破防守 + 出清倉停損停利 + 提早 EOD + 觀測評等
  --mode eod            position_levels + 觀測評等（≥門檻請買進）；寫入隔日 08:30 提醒
  --mode preopen        ~08:30 若前一日 EOD 有 0050／正2 操作 → 開盤前提醒
  --mode crypto_noon    ~12:00 BTC／ETH 午間狀態（偏重不加碼）
  --mode multi_day      上班窗：黃金／外匯（台銀可執行）
  --mode multi          晚間：黃金複核 + BTC + 美股觀測 + 觀測評等
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "src_scripts")
sys.path.insert(0, SCRIPTS)
from notify import clear_notify_batch, flush_notify_batch  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def run_script(name: str, extra_args: list[str]) -> int:
    path = os.path.join(SCRIPTS, name)
    cmd = [sys.executable, path, *extra_args]
    print(f"\n=== RUN {name} {' '.join(extra_args)} ===")
    env = os.environ.copy()
    env["TWSTOCKALS_WORKSPACE"] = ROOT
    env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
    env["TWSTOCKALS_BATCH_NOTIFY"] = "1"
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    print(f"=== EXIT {name} code={proc.returncode} ===")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[
            "all",
            "intraday",
            "close_confirm",
            "eod",
            "preopen",
            "crypto_noon",
            "multi",
            "multi_day",
        ],
        default="all",
    )
    parser.add_argument("--force", action="store_true", help="Pass --force to child scripts")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--no-popup", action="store_true", default=True)
    args = parser.parse_args()

    print(
        f"run_all_alerts mode={args.mode} at "
        f"{taiwan_now().isoformat(timespec='seconds')} (Asia/Taipei)"
    )
    print(f"workspace={ROOT}")

    clear_notify_batch()

    common = []
    if args.force:
        common.append("--force")
    if args.force_notify:
        common.append("--force-notify")

    codes = []
    if args.mode in ("all", "intraday"):
        sw = list(common)
        if args.no_popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        codes.append(run_script("scan_black_swan.py", sw))

    if args.mode in ("all", "close_confirm"):
        sw = list(common)
        if args.no_popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        sw.append("--close-confirm")
        codes.append(run_script("scan_black_swan.py", sw))
        xargs = list(common)
        if "--force" not in xargs:
            xargs.append("--force")
        codes.append(run_script("scan_exit_watch.py", xargs))
        eargs = list(common)
        if "--force" not in eargs:
            eargs.append("--force")
        codes.append(run_script("scan_position_levels.py", eargs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        codes.append(run_script("scan_watch_grades.py", wargs))

    if args.mode in ("all", "eod"):
        eargs = list(common)
        if "--force" not in eargs:
            eargs.append("--force")
        eargs.append("--save-pending")
        codes.append(run_script("scan_position_levels.py", eargs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        wargs.append("--save-pending")
        codes.append(run_script("scan_watch_grades.py", wargs))

    if args.mode == "preopen":
        pargs = list(common)
        if "--force" not in pargs:
            pargs.append("--force")
        codes.append(run_script("scan_preopen_reminder.py", pargs))

    if args.mode == "crypto_noon":
        cargs = list(common)
        if "--force" not in cargs:
            cargs.append("--force")
        codes.append(run_script("scan_crypto_noon.py", cargs))

    if args.mode == "multi_day":
        margs = list(common)
        if "--force" not in margs:
            margs.append("--force")
        margs.append("--day")
        margs.append("--skip-btc")
        codes.append(run_script("scan_multi_asset.py", margs))

    if args.mode in ("all", "multi"):
        margs = list(common)
        if "--force" not in margs:
            margs.append("--force")
        codes.append(run_script("scan_multi_asset.py", margs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        codes.append(run_script("scan_watch_grades.py", wargs))

    bad = [c for c in codes if c not in (0, None)]

    tw = taiwan_now()
    mode_titles = {
        "intraday": f"盤中摘要 {tw.strftime('%m/%d %H:%M')}（台北）",
        "close_confirm": f"收盤確認 {tw.strftime('%m/%d %H:%M')}（台北）",
        "eod": f"收盤執行 {tw.strftime('%m/%d %H:%M')}（台北）",
        "preopen": f"開盤前提醒 {tw.strftime('%m/%d %H:%M')}（台北）",
        "crypto_noon": f"BTC／ETH 午間 {tw.strftime('%m/%d %H:%M')}（台北）",
        "multi_day": f"多資產上班窗 {tw.strftime('%m/%d %H:%M')}（台北）",
        "multi": f"多資產晚報 {tw.strftime('%m/%d %H:%M')}（台北）",
        "all": f"警報整合 {tw.strftime('%m/%d %H:%M')}（台北）",
    }
    flush_notify_batch(
        mode_titles.get(args.mode, f"警報摘要 {tw.strftime('%m/%d %H:%M')}（台北）"),
        force=args.force_notify,
    )

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
