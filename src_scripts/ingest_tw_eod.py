# -*- coding: utf-8 -*-
"""Taiwan EOD ingest: TWSE OpenAPI day snapshot + FinMind fallback for holdings."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from ingest_common import (  # noqa: E402
    notify_ingest_failure,
    quality_check_ohlc,
    record_job,
    symbol_csv_path,
    tw_universe_codes,
    warehouse_dir,
    write_ohlc_csv,
)

UA = {"User-Agent": "Mozilla/5.0 (compatible; twstockals-ingest/1.0)"}
TWSE_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_MI_INDEX = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"


def _http_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _f(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "--", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_twse_day_all() -> list[dict]:
    data = _http_json(TWSE_DAY_ALL)
    if not isinstance(data, list):
        return []
    return data


def fetch_taiex_row() -> Optional[dict]:
    """Best-effort TAIEX close from MI_INDEX (structure varies)."""
    try:
        data = _http_json(TWSE_MI_INDEX)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    for row in data:
        name = str(row.get("指數") or row.get("Index") or row.get("Name") or "")
        if "發行量加權" in name or name in ("TAIEX", "臺灣加權指數"):
            close = _f(row.get("收盤指數") or row.get("CloseIndex") or row.get("收盤"))
            date_raw = row.get("日期") or row.get("Date") or ""
            d = str(date_raw).replace("/", "-")[:10]
            if close and d:
                return {"date": d, "open": None, "close": close, "source": "twse"}
    return None


def snapshot_to_rows(snapshot: list[dict], codes: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in snapshot:
        code = str(row.get("Code") or row.get("證券代號") or "").strip()
        if not code or (codes and code not in codes):
            continue
        close = _f(row.get("ClosingPrice") or row.get("收盤價"))
        if close is None:
            continue
        # STOCK_DAY_ALL is latest trading day only; date often absent → use today TW
        from tw_time import taiwan_now

        d = taiwan_now().strftime("%Y-%m-%d")
        date_hint = row.get("Date") or row.get("日期")
        if date_hint:
            d = str(date_hint).replace("/", "-")[:10]
        out[code] = [
            {
                "date": d,
                "open": _f(row.get("OpeningPrice") or row.get("開盤價")),
                "high": _f(row.get("HighestPrice") or row.get("最高價")),
                "low": _f(row.get("LowestPrice") or row.get("最低價")),
                "close": close,
                "volume": _f(row.get("TradeVolume") or row.get("成交股數")),
                "source": "twse",
            }
        ]
    return out


def finmind_history(code: str, years: int = 2) -> list[dict]:
    try:
        from fetch_stock_data import rotator, fetch_with_rotation
    except Exception:
        return []
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    try:
        df = fetch_with_rotation(
            rotator,
            "taiwan_stock_daily",
            stock_id=code,
            start_date=start,
            end_date=end,
        )
    except Exception as e:
        print(f"[tw_eod] FinMind {code}: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            c = r.get("close") if hasattr(r, "get") else r["close"]
            if c is None or (isinstance(c, float) and c != c):
                continue
            d = str(r["date"])[:10]
            rows.append(
                {
                    "date": d,
                    "open": float(r["open"]) if "open" in r and r["open"] == r["open"] else None,
                    "high": float(r["max"]) if "max" in r and r["max"] == r["max"] else None,
                    "low": float(r["min"]) if "min" in r and r["min"] == r["min"] else None,
                    "close": float(c),
                    "volume": float(r["Trading_Volume"])
                    if "Trading_Volume" in r and r["Trading_Volume"] == r["Trading_Volume"]
                    else None,
                    "source": "finmind",
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    return rows


def run(*, notify_on_fail: bool = True) -> bool:
    codes = tw_universe_codes()
    code_set = set(codes)
    row_counts: dict[str, int] = {}
    errors: list[str] = []
    source_used = "twse"

    # Persist full market snapshot
    snap_path = ""
    try:
        snapshot = fetch_twse_day_all()
        if not snapshot:
            raise RuntimeError("empty STOCK_DAY_ALL")
        from tw_time import taiwan_now

        day = taiwan_now().strftime("%Y%m%d")
        snap_dir = warehouse_dir("twse")
        snap_path = os.path.join(snap_dir, f"STOCK_DAY_ALL_{day}.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        per = snapshot_to_rows(snapshot, code_set)
        for code, rows in per.items():
            warns = quality_check_ohlc(rows, max_gap_pct=0.5)
            path = symbol_csv_path("twse", code)
            n = write_ohlc_csv(path, rows, "twse")
            row_counts[code] = n
            if warns and n < 5:
                # single-day append OK; still try FinMind history below
                pass
        print(f"[tw_eod] TWSE snapshot {len(snapshot)} rows → {snap_path}")
    except Exception as e:
        errors.append(f"twse:{e}")
        source_used = "finmind"
        print(f"[tw_eod] TWSE failed: {e}; falling back to FinMind")

    # Ensure each holding has usable history (FinMind backfill)
    for code in codes:
        path = symbol_csv_path("twse", code)
        need_hist = True
        if os.path.exists(path):
            try:
                import csv

                with open(path, "r", encoding="utf-8") as f:
                    n = sum(1 for _ in csv.DictReader(f))
                need_hist = n < 30
            except Exception:
                need_hist = True
        if not need_hist and code in row_counts:
            continue
        hist = finmind_history(code)
        if hist:
            n = write_ohlc_csv(path, hist, "finmind")
            row_counts[code] = n
            warns = quality_check_ohlc(hist)
            if warns:
                print(f"[tw_eod] quality {code}: {warns}")
            source_used = "twse+finmind" if source_used == "twse" else "finmind"
        elif code not in row_counts:
            errors.append(f"missing:{code}")

    taiex = fetch_taiex_row()
    if taiex:
        n = write_ohlc_csv(symbol_csv_path("twse", "TAIEX"), [taiex], "twse")
        row_counts["TAIEX"] = n
    else:
        # FinMind index
        try:
            from fetch_stock_data import rotator, fetch_with_rotation

            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
            df = fetch_with_rotation(
                rotator,
                "taiwan_stock_daily",
                stock_id="TAIEX",
                start_date=start,
                end_date=end,
            )
            if df is not None and not df.empty:
                rows = []
                for _, r in df.iterrows():
                    try:
                        rows.append(
                            {
                                "date": str(r["date"])[:10],
                                "close": float(r["close"]),
                                "open": float(r["open"]) if "open" in r else None,
                                "source": "finmind",
                            }
                        )
                    except Exception:
                        continue
                if rows:
                    row_counts["TAIEX"] = write_ohlc_csv(
                        symbol_csv_path("twse", "TAIEX"), rows, "finmind"
                    )
        except Exception as e:
            errors.append(f"taiex:{e}")

    ok = len(errors) == 0 and len(row_counts) > 0
    if not ok and len(row_counts) >= max(1, len(codes) // 2):
        ok = True  # partial success acceptable
    record_job(
        "tw_eod",
        ok=ok,
        source=source_used,
        symbols=codes,
        row_counts=row_counts,
        error="; ".join(errors) if errors else None,
        extra={"snapshot": snap_path or None},
    )
    if not ok and notify_on_fail:
        notify_ingest_failure("tw_eod", "; ".join(errors) or "unknown")
    print(f"[tw_eod] done ok={ok} symbols={len(row_counts)} errors={errors}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
