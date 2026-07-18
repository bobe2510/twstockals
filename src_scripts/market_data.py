# -*- coding: utf-8 -*-
"""
統一行情抓取：依資產切換來源，避免只靠 Yahoo。

優先順序:
  - 本地倉（market_crawled_cache/warehouse，TTL 內）
  - 美股 ETF（VOO/VXUS/QQQ…）：Stooq → FinMind us_stock_price → Yahoo
    （ingest 主源為 Stooq；本模組即時鏈仍保留 FinMind）
  - 加密：Binance 公開 API → Yahoo
  - 黃金／匯率等：Stooq → Yahoo（FinMind 通常無此代號）
  - 台股：warehouse/twse 或 FinMind taiwan_stock_daily（見 ingest_tw_eod）

Yahoo 非官方 API 常限流／稀疏取樣，只當最後備援。
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

UA = {"User-Agent": "Mozilla/5.0 (compatible; twstockals/1.0)"}

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

# Cache-first defaults (hours); override via env
_CACHE_TTL_HOURS = float(os.environ.get("TWSTOCKALS_CACHE_TTL_HOURS", "36"))
_CACHE_TTL_CRYPTO_HOURS = float(os.environ.get("TWSTOCKALS_CACHE_TTL_CRYPTO_HOURS", "1"))
_SKIP_CACHE = os.environ.get("TWSTOCKALS_SKIP_CACHE", "").strip() in ("1", "true", "yes")

STOOQ_MAP = {
    "VOO": "voo.us",
    "VXUS": "vxus.us",
    "QQQ": "qqq.us",
    "QQQM": "qqqm.us",
    "GC=F": "gc.f",
    "USDTWD=X": "usdtwd",
}

YAHOO_MAP = {
    "VOO": "VOO",
    "VXUS": "VXUS",
    "QQQ": "QQQ",
    "QQQM": "QQQM",
    "GC=F": "GC=F",
    "USDTWD=X": "USDTWD=X",
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "USDT-USD": "USDT-USD",
    "USDC-USD": "USDC-USD",
    "PEPE-USD": "PEPE-USD",
    "BNB-USD": "BNB-USD",
    "POL-USD": "POL-USD",
    "TSM": "TSM",
    "EWT": "EWT",
    "NQ=F": "NQ=F",
}

BINANCE_MAP = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "BNB-USD": "BNBUSDT",
    "POL-USD": "POLUSDT",
}

FINMIND_US = {"VOO", "VXUS", "QQQ", "QQQM", "TSM", "EWT"}


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_finmind_us_daily(sym_key: str, years: int = 12) -> list[dict]:
    if sym_key not in FINMIND_US:
        return []
    try:
        if WORKSPACE not in sys.path:
            sys.path.insert(0, WORKSPACE)
        from src_scripts.fetch_stock_data import rotator, fetch_with_rotation
    except Exception:
        try:
            from fetch_stock_data import rotator, fetch_with_rotation
        except Exception:
            return []
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    try:
        df = fetch_with_rotation(
            rotator,
            "us_stock_price",
            stock_id=sym_key,
            start_date=start,
            end_date=end,
        )
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            c = r["Close"] if "Close" in df.columns else r["close"]
            if c is None or (isinstance(c, float) and c != c):
                continue
            d = str(r["date"])[:10]
            o = r["Open"] if "Open" in df.columns else None
            rows.append(
                {
                    "date": d,
                    "open": float(o) if o is not None and o == o else None,
                    "close": float(c),
                    "source": "finmind",
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_stooq_daily(sym_key: str) -> list[dict]:
    stooq = STOOQ_MAP.get(sym_key)
    if not stooq:
        return []
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(stooq)}&i=d"
    try:
        raw = _http_get(url, timeout=25).decode("utf-8", errors="ignore")
    except Exception:
        return []
    if not raw or "Date" not in raw.splitlines()[0]:
        return []
    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for r in reader:
        try:
            c = r.get("Close") or r.get("close")
            if c in (None, "", "null"):
                continue
            rows.append(
                {
                    "date": r["Date"],
                    "open": float(r["Open"]) if r.get("Open") not in (None, "") else None,
                    "close": float(c),
                    "source": "stooq",
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_yahoo_daily(sym_key: str, range_: str = "10y") -> list[dict]:
    ysym = YAHOO_MAP.get(sym_key, sym_key)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym)}"
        f"?interval=1d&range={range_}"
    )
    try:
        raw = json.loads(_http_get(url, timeout=25).decode("utf-8"))
    except Exception:
        return []
    result = (raw.get("chart") or {}).get("result") or []
    if not result:
        return []
    r0 = result[0]
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []
    rows = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        # 用 UTC 轉日期：避免 TZ=Asia/Taipei 時美股日線日期位移一天（與 Stooq 對齊）
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        o = opens[i] if i < len(opens) else None
        rows.append(
            {
                "date": d,
                "open": float(o) if o is not None else None,
                "close": float(c),
                "source": "yahoo",
            }
        )
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_binance_klines(sym_key: str, limit: int = 1000) -> list[dict]:
    pair = BINANCE_MAP.get(sym_key)
    if not pair:
        return []
    url = (
        f"https://api.binance.com/api/v3/klines?symbol={pair}"
        f"&interval=1d&limit={min(limit, 1000)}"
    )
    try:
        data = json.loads(_http_get(url, timeout=25).decode("utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows = []
    for k in data:
        try:
            d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append(
                {
                    "date": d,
                    "open": float(k[1]),
                    "close": float(k[4]),
                    "source": "binance",
                }
            )
        except (TypeError, ValueError, IndexError):
            continue
    return rows


def _warehouse_candidates(sym_key: str) -> list[tuple[str, str]]:
    """Return (source_folder, path) candidates for warehouse CSV."""
    try:
        from ingest_common import symbol_csv_path
    except Exception:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from ingest_common import symbol_csv_path
        except Exception:
            return []
    cands: list[tuple[str, str]] = []
    if sym_key in BINANCE_MAP:
        cands.append(("binance", symbol_csv_path("binance", sym_key)))
    if sym_key in STOOQ_MAP or sym_key in FINMIND_US:
        cands.append(("stooq", symbol_csv_path("stooq", sym_key)))
    # TW numeric / TAIEX
    if sym_key == "TAIEX" or (sym_key[:1].isdigit() and len(sym_key) <= 6):
        cands.append(("twse", symbol_csv_path("twse", sym_key)))
    return cands


def _ttl_hours_for(sym_key: str) -> float:
    if sym_key in BINANCE_MAP:
        return _CACHE_TTL_CRYPTO_HOURS
    return _CACHE_TTL_HOURS


def read_warehouse_daily(sym_key: str, *, max_age_hours: Optional[float] = None) -> list[dict]:
    """Read warehouse CSV if fresh enough; else []."""
    if _SKIP_CACHE:
        return []
    ttl = _ttl_hours_for(sym_key) if max_age_hours is None else max_age_hours
    try:
        from ingest_common import csv_mtime_age_hours, read_ohlc_csv
    except Exception:
        return []
    for _src, path in _warehouse_candidates(sym_key):
        age = csv_mtime_age_hours(path)
        if age is None or age > ttl:
            continue
        rows = read_ohlc_csv(path)
        if len(rows) >= 5:
            # tag source for callers
            for r in rows:
                r.setdefault("source", "warehouse")
            return rows
    return []


def _write_warehouse_after_fetch(sym_key: str, rows: list[dict], source: str) -> None:
    if not rows or len(rows) < 5:
        return
    try:
        from ingest_common import symbol_csv_path, write_ohlc_csv
    except Exception:
        return
    folder = "binance" if source == "binance" else "stooq"
    if sym_key == "TAIEX" or (sym_key[:1].isdigit() and source in ("twse", "finmind")):
        folder = "twse"
    try:
        write_ohlc_csv(symbol_csv_path(folder, sym_key), rows, source)
    except Exception:
        pass


def fetch_daily(
    sym_key: str,
    prefer: Optional[str] = None,
    *,
    use_cache: bool = True,
) -> list[dict]:
    if use_cache and not _SKIP_CACHE:
        cached = read_warehouse_daily(sym_key)
        if cached:
            return cached

    if sym_key in BINANCE_MAP:
        auto = ["binance", "yahoo"]
    elif sym_key in FINMIND_US:
        # Stooq first (droplet primary); FinMind then Yahoo
        auto = ["stooq", "finmind", "yahoo"]
    elif sym_key in STOOQ_MAP:
        auto = ["stooq", "yahoo"]
    else:
        auto = ["yahoo"]

    order = [prefer] + [p for p in auto if p != prefer] if prefer else auto
    for p in order:
        if not p:
            continue
        if p == "finmind":
            rows = fetch_finmind_us_daily(sym_key)
        elif p == "stooq":
            rows = fetch_stooq_daily(sym_key)
        elif p == "binance":
            rows = fetch_binance_klines(sym_key)
        elif p == "yahoo":
            rows = fetch_yahoo_daily(sym_key, "10y")
            if len(rows) < 50:
                rows = fetch_yahoo_daily(sym_key, "2y")
        else:
            rows = []
        if len(rows) >= 5:
            if use_cache and not _SKIP_CACHE:
                _write_warehouse_after_fetch(sym_key, rows, p)
            return rows
    return []


def fetch_quote(sym_key: str, *, use_cache: bool = True) -> Optional[dict]:
    """use_cache=False：跳過 warehouse 快取直抓來源（shock 類即時檢查用）。"""
    rows = fetch_daily(sym_key, use_cache=use_cache)
    if len(rows) < 2:
        if len(rows) == 1:
            return {
                "price": rows[0]["close"],
                "prev_close": rows[0]["close"],
                "change_pct": 0.0,
                "source": rows[0].get("source"),
                "date": rows[0]["date"],
            }
        return None
    a, b = rows[-2], rows[-1]
    prev, price = a["close"], b["close"]
    chg = (price / prev - 1.0) * 100.0 if prev else 0.0
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": chg,
        "source": b.get("source"),
        "date": b["date"],
    }


if __name__ == "__main__":
    for s in ["VOO", "VXUS", "QQQ", "GC=F", "USDTWD=X", "BTC-USD"]:
        q = fetch_quote(s)
        print(s, q)
