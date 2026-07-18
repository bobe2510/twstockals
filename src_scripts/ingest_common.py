# -*- coding: utf-8 -*-
"""Shared warehouse helpers for droplet ingest workers."""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
WAREHOUSE_ROOT = os.path.join(WORKSPACE, "market_crawled_cache", "warehouse")
MANIFEST_PATH = os.path.join(WAREHOUSE_ROOT, "manifest.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
try:
    from tw_time import taiwan_now
except Exception:  # pragma: no cover

    def taiwan_now() -> datetime:
        return datetime.now()


def warehouse_dir(source: str) -> str:
    path = os.path.join(WAREHOUSE_ROOT, source)
    os.makedirs(path, exist_ok=True)
    return path


def symbol_csv_path(source: str, symbol: str) -> str:
    safe = symbol.replace("/", "_").replace("=", "_")
    return os.path.join(warehouse_dir(source), f"{safe}.csv")


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"updated_at": None, "jobs": {}}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "jobs": {}}


def save_manifest(manifest: dict) -> None:
    os.makedirs(WAREHOUSE_ROOT, exist_ok=True)
    manifest["updated_at"] = taiwan_now().isoformat(timespec="seconds")
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def record_job(
    job: str,
    *,
    ok: bool,
    source: str,
    symbols: list[str],
    row_counts: dict[str, int],
    error: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    m = load_manifest()
    entry: dict[str, Any] = {
        "ok": ok,
        "source": source,
        "symbols": symbols,
        "row_counts": row_counts,
        "finished_at": taiwan_now().isoformat(timespec="seconds"),
        "error": error,
    }
    if extra:
        entry["extra"] = extra
    m.setdefault("jobs", {})[job] = entry
    save_manifest(m)


def write_ohlc_csv(path: str, rows: list[dict], source: str) -> int:
    """Write date/open/high/low/close/volume/source CSV; returns row count."""
    if not rows:
        return 0
    # Merge with existing by date if present
    by_date: dict[str, dict] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    d = (r.get("date") or "")[:10]
                    if d:
                        by_date[d] = r
        except Exception:
            pass
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if not d:
            continue
        by_date[d] = {
            "date": d,
            "open": r.get("open", ""),
            "high": r.get("high", ""),
            "low": r.get("low", ""),
            "close": r.get("close", ""),
            "volume": r.get("volume", ""),
            "source": r.get("source") or source,
        }
    ordered = [by_date[k] for k in sorted(by_date.keys())]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "volume", "source"]
        )
        w.writeheader()
        w.writerows(ordered)
    return len(ordered)


def read_ohlc_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    c = r.get("close")
                    if c in (None, "", "null"):
                        continue
                    rows.append(
                        {
                            "date": (r.get("date") or "")[:10],
                            "open": float(r["open"]) if r.get("open") not in (None, "") else None,
                            "close": float(c),
                            "source": r.get("source") or "warehouse",
                        }
                    )
                except (TypeError, ValueError, KeyError):
                    continue
    except Exception:
        return []
    rows.sort(key=lambda x: x["date"])
    return rows


def csv_mtime_age_hours(path: str) -> Optional[float]:
    if not os.path.exists(path):
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 3600.0


def quality_check_ohlc(rows: list[dict], *, max_gap_pct: float = 0.35) -> list[str]:
    """Return list of warning strings; empty = pass."""
    warns: list[str] = []
    if len(rows) < 5:
        warns.append(f"too_few_rows:{len(rows)}")
        return warns
    closes = []
    for r in rows:
        try:
            closes.append(float(r["close"]))
        except (TypeError, ValueError, KeyError):
            continue
    if len(closes) < 5:
        warns.append("too_few_valid_closes")
        return warns
    if any(c <= 0 for c in closes[-30:]):
        warns.append("non_positive_close")
    # Large single-day jump on last bar
    if len(closes) >= 2 and closes[-2] > 0:
        gap = abs(closes[-1] / closes[-2] - 1.0)
        if gap > max_gap_pct:
            warns.append(f"large_gap:{gap:.1%}")
    return warns


def notify_ingest_failure(job: str, detail: str, *, force: bool = False) -> None:
    """Record fail streak; edge-push only via eval_market_events / event_bus."""
    try:
        from event_bus import bump_streak
        from eval_market_events import eval_ingest

        bump_streak(f"ingest_job_{job}", success=False)
        # Re-evaluate pipeline event (N≥2 onset)
        eval_ingest(quiet=False, force=force)
        print(f"[ingest] fail recorded job={job}: {detail[:200]}")
    except Exception as e:
        print(f"[ingest] event notify failed: {e}")
        try:
            from notify import notify

            notify(
                f"資料抓取失敗：{job}",
                detail[:3500],
                symbol="INGEST",
                rule_id=f"fail_{job}",
                urgency="emergency",
                force=force,
            )
        except Exception as e2:
            print(f"[ingest] telegram fallback failed: {e2}")


def notify_ingest_health(
    title: str,
    body: str,
    *,
    rule_id: str = "health",
    force: bool = False,
) -> None:
    try:
        from eval_market_events import eval_ingest

        eval_ingest(quiet=False, force=force)
        print(f"[ingest] health → event_bus: {title}")
    except Exception as e:
        print(f"[ingest] health notify failed: {e}")
        try:
            from notify import notify

            notify(
                title,
                body[:3500],
                symbol="INGEST",
                rule_id=rule_id,
                urgency="emergency",
                force=force,
            )
        except Exception:
            pass


def load_targets() -> dict:
    path = os.path.join(WORKSPACE, "config", "my_targets.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def tw_universe_codes() -> list[str]:
    """TW listed codes from portfolio + watchlist (skip US tickers)."""
    data = load_targets()
    codes: list[str] = []
    seen = set()
    for key in ("portfolio", "watchlist"):
        for item in data.get(key) or []:
            code = str(item.get("code") or "").strip()
            mkt = (item.get("market") or "TSE").upper()
            if not code or code in seen:
                continue
            if mkt in ("US", "NASDAQ", "NYSE") or code.isalpha():
                continue
            # Heuristic: pure digits / digit+letter TW codes
            if code[0].isdigit():
                seen.add(code)
                codes.append(code)
    if "0050" not in seen:
        codes.append("0050")
    return codes


def us_etf_codes() -> list[str]:
    data = load_targets()
    codes: list[str] = []
    seen = set()
    for item in data.get("watchlist") or []:
        code = str(item.get("code") or "").strip().upper()
        mkt = (item.get("market") or "").upper()
        if code in ("VOO", "VXUS", "QQQ", "QQQM", "TSM", "EWT") or mkt in (
            "US",
            "NASDAQ",
            "NYSE",
        ):
            if code and code not in seen and code.isalpha():
                seen.add(code)
                codes.append(code)
    for item in data.get("multi_asset", {}).get("us_etf") or []:
        code = str(item.get("code") or "").strip().upper()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        codes = ["VOO", "VXUS", "QQQ", "QQQM"]
    return codes


def crypto_codes() -> list[str]:
    data = load_targets()
    out: list[str] = []
    seen = set()
    for item in data.get("multi_asset", {}).get("crypto") or []:
        # my_targets 的 crypto 用 "symbol" 欄位（相容舊 "code"）
        code = str(item.get("symbol") or item.get("code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    # Prefer majors that have Binance map
    preferred = [c for c in out if c in ("BTC-USD", "ETH-USD", "BNB-USD", "POL-USD")]
    return preferred or ["BTC-USD", "ETH-USD"]
