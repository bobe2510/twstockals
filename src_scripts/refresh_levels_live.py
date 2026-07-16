# -*- coding: utf-8 -*-
"""
輕量刷新 reports/latest/levels.json 的現價／均線／5日低（雲端 EOD／收盤確認用）。
不重跑全市場 screener；只更新 portfolio + watchlist + TAIEX。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from holding_rules import is_core_etf  # noqa: E402
from market_data import fetch_daily  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def _series(code: str, market: str = "TW") -> Optional[dict]:
    prefer = "us" if market == "US" or (code.isalpha() and not code[0].isdigit()) else "tw"
    if code == "TAIEX":
        prefer = "tw"
    try:
        rows = fetch_daily(code, prefer=prefer)
    except Exception as e:
        print(f"fetch fail {code}: {e}")
        return None
    if len(rows) < 20:
        return None
    closes = [float(r["close"]) for r in rows]
    px = closes[-1]
    low_5d = min(closes[-5:]) if len(closes) >= 5 else None
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    return {
        "close": px,
        "ma5": sum(closes[-5:]) / 5 if len(closes) >= 5 else None,
        "ma10": sum(closes[-10:]) / 10 if len(closes) >= 10 else None,
        "ma20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
        "ma200": ma200,
        "low_5d": low_5d,
        "above_200ma": (px > ma200) if ma200 is not None else None,
    }


def main() -> None:
    now = taiwan_now()
    os.makedirs(os.path.dirname(LEVELS_PATH), exist_ok=True)
    doc: dict = {}
    if os.path.exists(LEVELS_PATH):
        with open(LEVELS_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)

    targets: dict = {}
    if os.path.exists(TARGETS_PATH):
        with open(TARGETS_PATH, "r", encoding="utf-8") as f:
            targets = json.load(f)

    by_code = {
        str(r.get("code")): dict(r)
        for r in (doc.get("levels") or [])
        if r.get("code")
    }
    portfolio_codes = {
        str(h.get("code")) for h in (targets.get("portfolio") or []) if h.get("code")
    }
    force_exit = {
        str(c) for c in (targets.get("force_exit_codes") or []) if c
    } | {
        str(h.get("code"))
        for h in (targets.get("portfolio") or [])
        if h.get("force_exit") and h.get("code")
    }

    codes: list[tuple[str, str, str]] = []
    for h in targets.get("portfolio") or []:
        if h.get("code"):
            codes.append((str(h["code"]), str(h.get("name") or ""), "TW"))
    for w in targets.get("watchlist") or []:
        c = w.get("code")
        if not c:
            continue
        m = w.get("market") or ("US" if str(c).isalpha() else "TW")
        codes.append((str(c), str(w.get("name") or ""), m))
    codes.append(("TAIEX", "加權指數", "TW"))

    updated = 0
    for code, name, market in codes:
        s = _series(code, market)
        if not s:
            continue
        row = by_code.get(code) or {
            "code": code,
            "name": name,
            "status": (
                "macro"
                if code == "TAIEX"
                else ("portfolio" if code in portfolio_codes else "watchlist")
            ),
            "force_exit": code in force_exit,
        }
        row["close"] = s["close"]
        row["ma5"] = s.get("ma5")
        row["ma10"] = s.get("ma10")
        row["ma20"] = s.get("ma20")
        if s.get("ma200") is not None:
            row["ma200"] = s["ma200"]
            row["above_200ma"] = s.get("above_200ma")
        if s.get("low_5d") is not None:
            row["low_5d"] = s["low_5d"]

        status = row.get("status")
        if status == "portfolio":
            core = is_core_etf(code, name) and code not in force_exit
            if not core and s.get("low_5d") is not None:
                row["stop"] = s["low_5d"]
            cost = row.get("cost")
            if cost is None:
                for h in targets.get("portfolio") or []:
                    if str(h.get("code")) == code and h.get("cost") is not None:
                        cost = float(h["cost"])
                        row["cost"] = cost
                        break
            if cost and float(cost) > 0:
                row["roi_pct"] = (float(s["close"]) / float(cost) - 1.0) * 100.0
        elif status == "watchlist":
            row["entry"] = s.get("ma5")
            row["stop"] = s.get("low_5d")
            row["profit"] = s.get("ma10")

        by_code[code] = row
        updated += 1

    doc["levels"] = list(by_code.values())
    doc["as_of"] = now.strftime("%Y-%m-%d")
    doc["generated_at"] = now.isoformat(timespec="seconds")
    with open(LEVELS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"levels.json 已輕量刷新：{updated} 檔｜as_of={doc['as_of']}")


if __name__ == "__main__":
    main()
