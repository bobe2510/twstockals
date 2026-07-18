# -*- coding: utf-8 -*-
"""Crypto daily klines: Binance primary, Yahoo fallback."""
from __future__ import annotations

import os
import sys

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from ingest_common import (  # noqa: E402
    crypto_codes,
    notify_ingest_failure,
    quality_check_ohlc,
    record_job,
    symbol_csv_path,
    write_ohlc_csv,
)
import market_data as md  # noqa: E402


def run(*, notify_on_fail: bool = True) -> bool:
    codes = crypto_codes()
    # Only symbols with a Binance mapping (or Yahoo)
    codes = [c for c in codes if c in md.BINANCE_MAP or c in md.YAHOO_MAP]
    row_counts: dict[str, int] = {}
    errors: list[str] = []
    for code in codes:
        rows = md.fetch_binance_klines(code)
        src = "binance"
        if len(rows) < 5:
            rows = md.fetch_yahoo_daily(code, "2y")
            src = "yahoo"
        if len(rows) < 5:
            errors.append(f"fail:{code}")
            continue
        warns = quality_check_ohlc(rows, max_gap_pct=0.5)
        if warns:
            print(f"[crypto] quality {code}: {warns}")
        path = symbol_csv_path("binance", code)
        n = write_ohlc_csv(path, rows, src)
        row_counts[code] = n
        print(f"[crypto] {code} rows={n} source={src}")

    success = len(errors) == 0 and bool(row_counts)
    record_job(
        "crypto",
        ok=success,
        source="binance",
        symbols=codes,
        row_counts=row_counts,
        error="; ".join(errors) if errors else None,
    )
    if not success and notify_on_fail:
        notify_ingest_failure("crypto", "; ".join(errors) or "no rows")
    print(f"[crypto] done ok={success} errors={errors}")
    return success


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
