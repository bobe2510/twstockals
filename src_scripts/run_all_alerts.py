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
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "src_scripts")


def run_script(name: str, extra_args: list[str]) -> int:
    path = os.path.join(SCRIPTS, name)
    cmd = [sys.executable, path, *extra_args]
    print(f"\n=== RUN {name} {' '.join(extra_args)} ===")
    env = os.environ.copy()
    env["TWSTOCKALS_WORKSPACE"] = ROOT
    env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
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

    print(f"run_all_alerts mode={args.mode} at {datetime.now().isoformat(timespec='seconds')}")
    print(f"workspace={ROOT}")

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
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
