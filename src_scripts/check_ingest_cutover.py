# -*- coding: utf-8 -*-
"""
Compare warehouse vs live fetch for cutover readiness.

  python src_scripts/check_ingest_cutover.py
  python src_scripts/check_ingest_cutover.py --symbols VOO,GC=F,BTC-USD

Exit 0 if all compared symbols within tolerance; else 1.
See docs/DATA_INGEST.md cutover checklist.
"""
from __future__ import annotations

import argparse
import os
import sys

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

import market_data as md  # noqa: E402
from ingest_common import load_manifest  # noqa: E402


def _last_close(rows):
    if not rows:
        return None
    return float(rows[-1]["close"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--symbols",
        default="VOO,VXUS,QQQ,GC=F,USDTWD=X,BTC-USD,ETH-USD",
    )
    ap.add_argument("--tol-pct", type=float, default=1.5, help="max |wh-live|/live %")
    args = ap.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]

    m = load_manifest()
    print("manifest jobs:", list((m.get("jobs") or {}).keys()))
    for j, entry in (m.get("jobs") or {}).items():
        print(f"  {j}: ok={entry.get('ok')} at={entry.get('finished_at')}")

    bad = []
    for sym in syms:
        wh = md.read_warehouse_daily(sym, max_age_hours=72)
        live = md.fetch_daily(sym, use_cache=False)
        cw, cl = _last_close(wh), _last_close(live)
        if cw is None or cl is None or cl == 0:
            print(f"{sym}: SKIP wh={cw} live={cl}")
            bad.append(sym)
            continue
        pct = abs(cw / cl - 1.0) * 100.0
        status = "OK" if pct <= args.tol_pct else "DIFF"
        print(f"{sym}: warehouse={cw:.4f} live={cl:.4f} Δ={pct:.2f}% [{status}]")
        if pct > args.tol_pct:
            bad.append(sym)

    if bad:
        print(f"cutover NOT ready: {bad}")
        print("Also complete checklist in docs/DATA_INGEST.md")
        return 1
    print("cutover price check OK — finish checklist in docs/DATA_INGEST.md before disabling Actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
