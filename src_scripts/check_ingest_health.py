# -*- coding: utf-8 -*-
"""
Warehouse / manifest health check → Telegram when stale or last job failed.

  python src_scripts/check_ingest_health.py
  python src_scripts/check_ingest_health.py --notify --force-notify

Used by run_all_alerts (preflight) and droplet cron.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from ingest_common import (  # noqa: E402
    WAREHOUSE_ROOT,
    csv_mtime_age_hours,
    load_manifest,
    notify_ingest_health,
    symbol_csv_path,
)
from tw_time import taiwan_now  # noqa: E402

# (job, max_age_hours, sample warehouse paths relative to source/symbol)
CHECKS = [
    ("crypto", 2.0, [("binance", "BTC-USD"), ("binance", "ETH-USD")]),
    ("fx_gold", 6.0, [("stooq", "GC=F"), ("stooq", "USDTWD=X")]),
    ("us_eod", 48.0, [("stooq", "VOO"), ("stooq", "QQQ")]),
    ("tw_eod", 48.0, [("twse", "0050"), ("twse", "00631L")]),
]


def _job_stale(job: str, max_age_h: float) -> Optional[str]:
    m = load_manifest()
    entry = (m.get("jobs") or {}).get(job)
    if not entry:
        return f"{job}: no manifest entry (尚未跑過 ingest)"
    if not entry.get("ok"):
        err = entry.get("error") or "ok=false"
        return f"{job}: last run FAIL — {err}"
    finished = entry.get("finished_at") or ""
    # Parse ISO; if age from finished_at unavailable, fall back to file mtime
    try:
        # finished_at like 2026-07-18T06:14:09+08:00
        from datetime import datetime

        ts = finished.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        now = taiwan_now()
        if dt.tzinfo and now.tzinfo is None:
            now = now.replace(tzinfo=dt.tzinfo)
        elif dt.tzinfo is None and now.tzinfo:
            dt = dt.replace(tzinfo=now.tzinfo)
        age_h = (now - dt).total_seconds() / 3600.0
        if age_h > max_age_h:
            return f"{job}: manifest stale {age_h:.1f}h > {max_age_h}h (at {finished})"
    except Exception:
        pass
    return None


def _files_stale(pairs: list[tuple[str, str]], max_age_h: float) -> Optional[str]:
    ages = []
    missing = []
    for src, sym in pairs:
        path = symbol_csv_path(src, sym)
        age = csv_mtime_age_hours(path)
        if age is None:
            missing.append(f"{src}/{sym}")
        else:
            ages.append((sym, age))
    if missing and not ages:
        return f"missing warehouse: {', '.join(missing)}"
    for sym, age in ages:
        if age > max_age_h:
            return f"{sym} file age {age:.1f}h > {max_age_h}h"
    return None


def run_checks(jobs: Optional[list[str]] = None) -> list[str]:
    """If jobs is set, only check those job names."""
    problems: list[str] = []
    if not os.path.isdir(WAREHOUSE_ROOT):
        problems.append(f"warehouse missing: {WAREHOUSE_ROOT}")
        return problems
    want = set(jobs) if jobs else None
    for job, max_age, pairs in CHECKS:
        if want is not None and job not in want:
            continue
        msg = _job_stale(job, max_age)
        if msg:
            problems.append(msg)
            continue
        msg2 = _files_stale(pairs, max_age)
        if msg2:
            problems.append(f"{job}: {msg2}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="Push Telegram/Email on problems")
    ap.add_argument("--force-notify", action="store_true")
    ap.add_argument(
        "--jobs",
        default="",
        help="Comma-separated job filter (default: all)",
    )
    ap.add_argument(
        "--quiet-ok",
        action="store_true",
        help="No stdout noise when healthy",
    )
    args = ap.parse_args()

    job_filter = [j.strip() for j in args.jobs.split(",") if j.strip()] or None
    problems = run_checks(job_filter)
    if not problems:
        if not args.quiet_ok:
            print("[ingest_health] OK")
        return 0

    body = "\n".join(f"• {p}" for p in problems)
    print(f"[ingest_health] PROBLEMS\n{body}")
    if args.notify:
        notify_ingest_health(
            "資料倉健康檢查異常",
            body,
            rule_id="health_stale",
            force=args.force_notify,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
