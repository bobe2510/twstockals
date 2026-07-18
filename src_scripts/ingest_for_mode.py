# -*- coding: utf-8 -*-
"""Map alert mode → ingest jobs; run them then optional health check."""
from __future__ import annotations

import os
import sys

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

# Which ingest jobs to refresh before each alert mode
MODE_JOBS: dict[str, list[str]] = {
    "intraday": ["fx_gold"],
    "close_confirm": ["fx_gold", "tw_eod"],
    "eod": ["tw_eod", "us_eod", "fx_gold"],
    "multi_day": ["fx_gold"],
    "multi": ["fx_gold", "crypto", "us_eod"],
    "all": ["tw_eod", "us_eod", "fx_gold", "crypto"],
}

_JOB_MODS = {
    "tw_eod": "ingest_tw_eod",
    "us_eod": "ingest_us_eod",
    "fx_gold": "ingest_fx_gold",
    "crypto": "ingest_crypto",
}


def run_ingest_for_mode(
    mode: str,
    *,
    notify_on_fail: bool = True,
    health_notify: bool = True,
) -> bool:
    """Return True if all selected jobs ok (empty job list = True)."""
    jobs = MODE_JOBS.get(mode, [])
    if not jobs:
        print(f"[ingest_for_mode] mode={mode}: no ingest jobs")
        return True

    results = {}
    for name in jobs:
        mod_name = _JOB_MODS[name]
        mod = __import__(mod_name)
        ok = mod.run(notify_on_fail=notify_on_fail)
        results[name] = ok
        print(f"[ingest_for_mode] {name}: {'OK' if ok else 'FAIL'}")

    all_ok = all(results.values()) if results else True

    # Health check only for jobs we just ran (avoid false alarm on unrelated sleeves)
    try:
        import check_ingest_health as health

        problems = health.run_checks(jobs)
        if problems:
            print("[ingest_for_mode] health:", problems)
            if health_notify:
                from ingest_common import notify_ingest_health

                notify_ingest_health(
                    "資料倉健康檢查異常",
                    "\n".join(f"• {p}" for p in problems),
                    rule_id="health_stale",
                )
    except Exception as e:
        print(f"[ingest_for_mode] health check error: {e}")

    return all_ok
