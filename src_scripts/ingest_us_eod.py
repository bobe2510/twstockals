# -*- coding: utf-8 -*-
"""US ETF EOD ingest: Stooq primary, FinMind/Yahoo via market_data fallback."""
from __future__ import annotations

import os
import sys

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from ingest_common import (  # noqa: E402
    notify_ingest_failure,
    quality_check_ohlc,
    record_job,
    symbol_csv_path,
    us_etf_codes,
    write_ohlc_csv,
)
import market_data as md  # noqa: E402


def run(*, notify_on_fail: bool = True) -> bool:
    codes = us_etf_codes()
    row_counts: dict[str, int] = {}
    errors: list[str] = []
    # Prefer Stooq for warehouse source tag
    for code in codes:
        rows = md.fetch_stooq_daily(code)
        src = "stooq"
        if len(rows) < 5:
            rows = md.fetch_finmind_us_daily(code)
            src = "finmind"
        if len(rows) < 5:
            rows = md.fetch_yahoo_daily(code, "10y")
            src = "yahoo"
        if len(rows) < 5:
            errors.append(f"fail:{code}")
            continue
        warns = quality_check_ohlc(rows)
        if warns:
            print(f"[us_eod] quality {code}: {warns}")
        path = symbol_csv_path("stooq", code)
        n = write_ohlc_csv(path, rows, src)
        row_counts[code] = n
        print(f"[us_eod] {code} rows={n} source={src}")

    ok = len(errors) == 0 and len(row_counts) > 0
    if row_counts and len(errors) < len(codes):
        ok = len(row_counts) >= 1
    record_job(
        "us_eod",
        ok=ok and not errors,
        source="stooq",
        symbols=codes,
        row_counts=row_counts,
        error="; ".join(errors) if errors else None,
    )
    success = bool(row_counts) and len(errors) == 0
    if not success and notify_on_fail:
        notify_ingest_failure("us_eod", "; ".join(errors) or "no rows")
    print(f"[us_eod] done ok={success} errors={errors}")
    return success


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
