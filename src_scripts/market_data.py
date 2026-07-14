# -*- coding: utf-8 -*-
"""
統一行情抓取：依資產切換來源，避免只靠 Yahoo。

優先順序:
  - 美股 ETF（VOO/VXUS/QQQ…）：FinMind us_stock_price → Stooq → Yahoo
  - 加密：Binance 公開 API → Yahoo
  - 黃金／匯率等：Stooq → Yahoo（FinMind 通常無此代號）
  - 台股：請繼續用 FinMind taiwan_stock_daily（本模組不包）

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
        d = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
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


def fetch_daily(sym_key: str, prefer: Optional[str] = None) -> list[dict]:
    if sym_key in BINANCE_MAP:
        auto = ["binance", "yahoo"]
    elif sym_key in FINMIND_US:
        auto = ["finmind", "stooq", "yahoo"]
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
            return rows
    return []


def fetch_quote(sym_key: str) -> Optional[dict]:
    rows = fetch_daily(sym_key)
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
