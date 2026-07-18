# -*- coding: utf-8 -*-
"""
Unified ingest entry for droplet cron/systemd.

  python src_scripts/run_ingest.py --job all|tw_eod|us_eod|fx_gold|crypto
  python src_scripts/run_ingest.py --job all --no-notify
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Droplet market data ingest")
    ap.add_argument(
        "--job",
        default="all",
        choices=["all", "tw_eod", "us_eod", "fx_gold", "crypto"],
    )
    ap.add_argument(
        "--no-notify",
        action="store_true",
        help="Do not Telegram on failure",
    )
    args = ap.parse_args()
    notify = not args.no_notify

    jobs = {
        "tw_eod": "ingest_tw_eod",
        "us_eod": "ingest_us_eod",
        "fx_gold": "ingest_fx_gold",
        "crypto": "ingest_crypto",
    }
    selected = list(jobs.keys()) if args.job == "all" else [args.job]
    results = {}
    for name in selected:
        mod = __import__(jobs[name])
        ok = mod.run(notify_on_fail=notify)
        results[name] = ok
        print(f"== {name}: {'OK' if ok else 'FAIL'} ==")

    failed = [k for k, v in results.items() if not v]

    # Post health check (stale warehouse) — notify when problems
    try:
        import check_ingest_health as health

        problems = health.run_checks()
        if problems:
            print("[run_ingest] health:", problems)
            if notify:
                from ingest_common import notify_ingest_health

                notify_ingest_health(
                    "資料倉健康檢查異常",
                    "\n".join(f"• {p}" for p in problems),
                    rule_id="health_stale",
                )
    except Exception as e:
        print(f"[run_ingest] health error: {e}")

    if failed:
        print(f"[run_ingest] failed: {failed}")
        return 1
    print("[run_ingest] all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
