# -*- coding: utf-8 -*-
"""
Unified alert runner for cloud / local cron.

Modes:
  --mode all            black_swan + close_confirm + position_levels + multi_asset
  --mode intraday       black_swan only（大盤／匯率／反1；不推個股破防守）
  --mode close_confirm  ~13:10 近收盤確認破防守 + 提早 EOD + 觀測評等
  --mode eod            position_levels only
  --mode multi          gold / FX / BTC / US ETF + 觀測評等
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
    # 同一輪排程只推一封整合摘要，避免 Telegram 轟炸
    env["TWSTOCKALS_BATCH_NOTIFY"] = "1"
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    print(f"=== EXIT {name} code={proc.returncode} ===")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["all", "intraday", "close_confirm", "eod", "multi"],
        default="all",
    )
    parser.add_argument("--force", action="store_true", help="Pass --force to child scripts")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--no-popup", action="store_true", default=True)
    args = parser.parse_args()

    print(f"run_all_alerts mode={args.mode} at {taiwan_now().isoformat(timespec='seconds')} (Asia/Taipei)")
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
        codes.append(run_script("scan_position_levels.py", eargs))

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
        "eod": f"收盤執行 {tw.strftime('%m/%d')}（台北）",
        "multi": f"多資產晚報 {tw.strftime('%m/%d')}（台北）",
        "all": f"警報整合 {tw.strftime('%m/%d %H:%M')}（台北）",
    }
    flush_notify_batch(
        mode_titles.get(args.mode, f"警報摘要 {tw.strftime('%m/%d %H:%M')}（台北）"),
        force=args.force_notify,
    )

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
