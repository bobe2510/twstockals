# -*- coding: utf-8 -*-
"""Gold + USD/TWD ingest via Stooq (Yahoo fallback)."""
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
    write_ohlc_csv,
)
import market_data as md  # noqa: E402

SYMBOLS = ["GC=F", "USDTWD=X"]


def run(*, notify_on_fail: bool = True) -> bool:
    row_counts: dict[str, int] = {}
    errors: list[str] = []
    for code in SYMBOLS:
        rows = md.fetch_stooq_daily(code)
        src = "stooq"
        if len(rows) < 5:
            rows = md.fetch_yahoo_daily(code, "10y")
            src = "yahoo"
        if len(rows) < 5:
            errors.append(f"fail:{code}")
            continue
        warns = quality_check_ohlc(rows, max_gap_pct=0.2)
        if warns:
            print(f"[fx_gold] quality {code}: {warns}")
        # Store under stooq folder for cache lookup consistency
        path = symbol_csv_path("stooq", code)
        n = write_ohlc_csv(path, rows, src)
        row_counts[code] = n
        print(f"[fx_gold] {code} rows={n} source={src}")

    success = len(errors) == 0 and len(row_counts) == len(SYMBOLS)
    record_job(
        "fx_gold",
        ok=success,
        source="stooq",
        symbols=SYMBOLS,
        row_counts=row_counts,
        error="; ".join(errors) if errors else None,
    )
    if not success and notify_on_fail:
        notify_ingest_failure("fx_gold", "; ".join(errors) or "no rows")
    print(f"[fx_gold] done ok={success} errors={errors}")
    return success


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
