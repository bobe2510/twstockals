# -*- coding: utf-8 -*-
"""
觀測標的統一買點評等（比照黃金 D/C/B/A/S）：
  D/C = 觀望（0）
  B   = 允許小買（非必須）
  A/S = 較推薦分批

涵蓋 approved_universe / watchlist：0050、00631L、VOO、VXUS、QQQ、QQQM 等。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "watch_grades.md")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from notify import notify, load_alert_rules  # noqa: E402
from market_data import fetch_daily  # noqa: E402


def load_targets():
    if not os.path.exists(TARGETS_PATH):
        return {}
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _series_from_rows(rows: list[dict]) -> Optional[dict]:
    if len(rows) < 30:
        return None
    closes = [float(r["close"]) for r in rows]
    px = closes[-1]
    prev = closes[-2]
    return {
        "price": px,
        "prev": prev,
        "change_pct": (px / prev - 1.0) * 100.0 if prev else 0.0,
        "closes": closes,
        "ma5": sum(closes[-5:]) / 5 if len(closes) >= 5 else None,
        "ma10": sum(closes[-10:]) / 10 if len(closes) >= 10 else None,
        "ma20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
        "ma50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
        "ma200": sum(closes[-200:]) / 200 if len(closes) >= 200 else None,
        "source": rows[-1].get("source"),
        "date": rows[-1].get("date"),
    }


def fetch_tw_daily(code: str, years: int = 3) -> list[dict]:
    """FinMind 台股日線。"""
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
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    col = "close" if "close" in df.columns else "Close"
    date_col = "date" if "date" in df.columns else "Date"
    rows = []
    for _, r in df.iterrows():
        try:
            c = float(r[col])
            d = str(r[date_col])[:10]
            rows.append({"date": d, "close": c, "source": "finmind"})
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_symbol(code: str, market: str = "TW") -> Optional[dict]:
    code_u = str(code).upper()
    if code_u == "TAIEX":
        rows = fetch_tw_daily("TAIEX")
        return _series_from_rows(rows)
    if market == "US" or code_u in ("VOO", "VXUS", "QQQ", "QQQM"):
        return _series_from_rows(fetch_daily(code_u if code_u in ("VOO", "VXUS", "QQQ", "QQQM") else code))
    rows = fetch_tw_daily(code)
    # 00631L 1拆22（與回測同一基準日）
    if code == "00631L" and rows:
        split_date = "2026-03-24"
        for r in rows:
            if r["date"] <= split_date:
                r["close"] = r["close"] / 22.0
    return _series_from_rows(rows)


def macro_level(taiex: dict) -> int:
    if not taiex or not taiex.get("ma20"):
        return 2
    px, ma20 = taiex["price"], taiex["ma20"]
    if px < ma20:
        return 3
    bias = (px - ma20) / ma20 * 100
    if bias <= 1.5:
        return 2
    return 1


def _stabilized(s: dict) -> bool:
    closes = s["closes"]
    px = s["price"]
    last5 = closes[-5:] if len(closes) >= 5 else closes
    fresh_low = bool(last5) and px <= min(last5) * 1.001
    up_day = px >= s["prev"]
    rising = False
    if len(closes) >= 3:
        rising = closes[-1] >= closes[-2] or (px > closes[-2])
    return (not fresh_low) and (up_day or rising)


def grade_pullback_core(s: dict, *, level: int, name: str, cash_cap: int) -> dict:
    """0050／VOO／VXUS 類底倉：拉回均線分級。"""
    px = s["price"]
    ma5, ma10, ma20 = s.get("ma5"), s.get("ma10"), s.get("ma20")
    ma200 = s.get("ma200")
    stab = _stabilized(s)
    bias5 = (px - ma5) / ma5 * 100 if ma5 else 99
    bias10 = (px - ma10) / ma10 * 100 if ma10 else 99
    bias20 = (px - ma20) / ma20 * 100 if ma20 else 99
    bias200 = (px - ma200) / ma200 * 100 if ma200 else 0

    if level >= 3:
        return _g("D", f"{name}：大盤 Level 3，暫停新買。", 0, level, stab, bias5, bias10, bias20, bias200)

    # 追高
    if bias5 > 3 and bias10 > 5:
        return _g("D", f"{name}：偏離短均偏高，不追價。", 0, level, stab, bias5, bias10, bias20, bias200)

    near5 = ma5 and abs(bias5) <= 1.5
    near10 = ma10 and abs(bias10) <= 2.0
    near20 = ma20 and -4 <= bias20 <= 1.0
    deep20 = ma20 and bias20 <= -4

    if level == 2 and not (near20 or deep20):
        return _g("C", f"{name}：Level 2 警戒，僅深拉回才考慮。", 0, level, stab, bias5, bias10, bias20, bias200)

    if (near5 or near10) and stab and level == 1:
        return _g(
            "B",
            f"{name}：回測 5/10MA 且略止穩 → 允許小買（非必須）。",
            min(80_000, cash_cap),
            level,
            stab,
            bias5,
            bias10,
            bias20,
            bias200,
        )
    if (near5 or near10) and not stab:
        return _g("C", f"{name}：靠近短均但未止穩，觀望。", 0, level, stab, bias5, bias10, bias20, bias200)

    if near20 and stab and level == 1:
        amt = min(100_000, cash_cap)
        return _g(
            "A",
            f"{name}：回測月線區且止穩 → 較推薦分批。",
            amt,
            level,
            stab,
            bias5,
            bias10,
            bias20,
            bias200,
        )
    if deep20 and stab and level == 1:
        return _g(
            "S",
            f"{name}：月線下深拉回＋止穩 → 較佳分批（仍分批）。",
            min(120_000, cash_cap),
            level,
            stab,
            bias5,
            bias10,
            bias20,
            bias200,
        )
    if near20 or deep20:
        return _g("B", f"{name}：月線附近，允許小額試探（非必須）。", min(60_000, cash_cap), level, stab, bias5, bias10, bias20, bias200)

    return _g("D", f"{name}：無明確拉回買點。", 0, level, stab, bias5, bias10, bias20, bias200)


def grade_lev_00631L(s: dict, taiex: dict, level: int, cash_cap: int) -> dict:
    """正2：年線總開關 + Level。"""
    above200 = bool(taiex and taiex.get("ma200") and taiex["price"] > taiex["ma200"])
    px = s["price"]
    ma10, ma20 = s.get("ma10"), s.get("ma20")
    stab = _stabilized(s)
    bias10 = (px - ma10) / ma10 * 100 if ma10 else 99
    bias20 = (px - ma20) / ma20 * 100 if ma20 else 99

    if level >= 3:
        return _g("D", "正2：Level 3 禁止加碼（既有倉可續抱視年線）。", 0, level, stab, bias10, bias10, bias20, 0)
    if not above200:
        return _g("D", "正2：大盤收盤在年線下 → 不加碼／偏空倉。", 0, level, stab, bias10, bias10, bias20, 0)
    if level == 2:
        return _g("C", "正2：Level 2 不加碼，僅觀望。", 0, level, stab, bias10, bias10, bias20, 0)

    # Level 1 + above 200MA
    if bias10 > 4 and bias20 > 6:
        return _g("D", "正2：短線乖離偏高，不追價加碼。", 0, level, stab, bias10, bias10, bias20, 0)
    if abs(bias10) <= 2.5 and stab:
        return _g(
            "B",
            "正2：年線上＋回測短均 → 允許小加（非必須）。",
            min(80_000, cash_cap),
            level,
            stab,
            bias10,
            bias10,
            bias20,
            0,
        )
    if -5 <= bias20 <= 1 and stab:
        return _g(
            "A",
            "正2：年線上＋回測月線區止穩 → 較推薦分批加碼。",
            min(100_000, cash_cap),
            level,
            stab,
            bias10,
            bias10,
            bias20,
            0,
        )
    if bias20 < -5 and stab:
        return _g(
            "S",
            "正2：年線上深拉回止穩 → 較佳加碼窗（仍分批）。",
            min(120_000, cash_cap),
            level,
            stab,
            bias10,
            bias10,
            bias20,
            0,
        )
    return _g("C", "正2：年線上但無清楚拉回，觀望。", 0, level, stab, bias10, bias10, bias20, 0)


def grade_growth_us(s: dict, name: str, cash_cap: int, pause_ib: bool) -> dict:
    """QQQ 等：用年線乖離；若 pause_ib 則只觀測不建議匯款。"""
    px = s["price"]
    ma50, ma200 = s.get("ma50"), s.get("ma200")
    stab = _stabilized(s)
    bias50 = (px - ma50) / ma50 * 100 if ma50 else 99
    bias200 = (px - ma200) / ma200 * 100 if ma200 else 0
    suffix = "（暫停IB：只觀測、不匯款）" if pause_ib else ""

    if bias50 > 4:
        return _g("D", f"{name}：偏離季線偏高，不追。{suffix}", 0, None, stab, bias50, bias50, bias200, bias200)
    if -2 <= bias50 <= 2 and stab:
        g = _g("B", f"{name}：回測季線 → 允許小買（非必須）。{suffix}", 0 if pause_ib else min(60_000, cash_cap), None, stab, bias50, bias50, bias200, bias200)
        return g
    if bias200 <= -8 and stab:
        return _g(
            "A" if not pause_ib else "B",
            f"{name}：年線下深回撤止穩。{suffix}",
            0 if pause_ib else min(80_000, cash_cap),
            None,
            stab,
            bias50,
            bias50,
            bias200,
            bias200,
        )
    if bias200 <= -3:
        return _g("C", f"{name}：靠近／低於年線但未到位。{suffix}", 0, None, stab, bias50, bias50, bias200, bias200)
    return _g("D", f"{name}：無清楚買點。{suffix}", 0, None, stab, bias50, bias50, bias200, bias200)


def _g(grade, reason, suggest, level, stab, b5, b10, b20, b200):
    return {
        "grade": grade,
        "reason": reason,
        "suggest_twd": int(suggest),
        "level": level,
        "stabilized": stab,
        "bias5": b5,
        "bias10": b10,
        "bias20": b20,
        "bias200": b200,
    }


def watch_universe(targets: dict) -> list[dict]:
    """要評等的標的清單。"""
    items = []
    seen = set()
    for w in targets.get("watchlist") or []:
        code = w.get("code")
        if not code or code in seen:
            continue
        if code in ("USDT_EARN",):
            continue
        seen.add(code)
        items.append(
            {
                "code": code,
                "name": w.get("name") or code,
                "market": w.get("market") or ("US" if code.isalpha() else "TW"),
                "role": w.get("role") or "",
            }
        )
    for b in (targets.get("approved_universe") or {}).get("buy_allowed") or []:
        code = b.get("id")
        if not code or code in seen or code in ("BOT_GOLD", "USDT_EARN"):
            continue
        seen.add(code)
        items.append(
            {
                "code": code,
                "name": code,
                "market": "US" if b.get("venue") == "IB" else "TW",
                "role": b.get("sleeve") or "",
            }
        )
    return items


def main():
    now = datetime.now()
    force = "--force" in sys.argv
    # 允許收盤確認窗與晚間多資產窗
    hhmm = now.strftime("%H%M")
    in_close = "1300" <= hhmm <= "1430"
    in_evening = now.hour >= 18 or now.hour < 8
    if not force and not (in_close or in_evening):
        print("非評等視窗（13:00~14:30 或晚間）且無 --force，退出。")
        sys.exit(0)

    targets = load_targets()
    multi = targets.get("multi_asset") or {}
    cash = int(multi.get("deployable_cash_twd") or 1_000_000)
    pause_ib = bool(multi.get("pause_us_ib"))

    print("載入大盤與觀測報價…")
    taiex = fetch_symbol("TAIEX", "TW")
    level = macro_level(taiex) if taiex else 2

    lines = []
    lines.append("# 觀測標的買點評等（統一 D/C/B/A/S）\n\n")
    lines.append(f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"可運用現金約 **{cash:,}** 元｜大盤 Level：**{level}**"
    )
    if taiex and taiex.get("ma200"):
        lines.append(
            f"｜TAIEX {taiex['price']:.0f}／年線 {taiex['ma200']:.0f}"
            f"（{'上' if taiex['price'] > taiex['ma200'] else '下'}）"
        )
    lines.append("  \n")
    lines.append(
        "> **B=允許小買（非必須）**；**A/S=較推薦分批**；D/C=觀望。  \n"
        "> 個股破防守仍只在收盤確認窗推播，不盤中殺低。  \n\n"
    )

    actions = []
    for item in watch_universe(targets):
        code = item["code"]
        name = item["name"]
        market = item["market"]
        s = fetch_symbol(code, market)
        if not s:
            lines.append(f"## {code} {name}\n\n* 報價失敗  \n\n")
            continue

        if code == "00631L":
            g = grade_lev_00631L(s, taiex, level, cash)
        elif code in ("QQQ", "QQQM") or item.get("role") in ("growth", "growth_alt", "satellite"):
            g = grade_growth_us(s, name, cash, pause_ib)
        else:
            # 0050 / VOO / VXUS core
            g = grade_pullback_core(
                s,
                level=level if market == "TW" else 1,
                name=name,
                cash_cap=cash,
            )
            if market == "US" and pause_ib and g["suggest_twd"] > 0:
                g["reason"] += "（暫停IB：只觀測、金額僅示意）"
                g["suggest_twd"] = 0
                if g["grade"] in ("A", "S"):
                    g["grade"] = "B"
                    g["reason"] = g["reason"].replace("較推薦", "允許觀測")

        lines.append(f"## {code} {name}\n\n")
        lines.append(
            f"* 價格：**{s['price']:.2f}** ({s['change_pct']:+.2f}%)｜來源 {s.get('source')}  \n"
        )
        if s.get("ma5"):
            lines.append(f"* 5/10/20MA：{s['ma5']:.2f}／{s.get('ma10') or '-'}／{s.get('ma20') or '-'}  \n")
        if s.get("ma200"):
            lines.append(f"* 200MA：{s['ma200']:.2f}（乖離 {g['bias200']:+.1f}%）  \n")
        lines.append(f"* 止穩：{'是' if g['stabilized'] else '否'}  \n")
        lines.append(f"\n### 評等 **{g['grade']}**｜")
        if g["grade"] in ("A", "S") and g["suggest_twd"] > 0:
            lines.append(f"**推薦**分批，上限 **{g['suggest_twd']:,}** 元\n\n")
            title = f"{code}評等{g['grade']}｜推薦分批買（上限{g['suggest_twd']//10000}萬）"
            stance = "推薦"
        elif g["grade"] == "B" and g["suggest_twd"] > 0:
            lines.append(f"**允許**小買（非必須），上限 **{g['suggest_twd']:,}** 元\n\n")
            title = f"{code}評等B｜允許小買上限{g['suggest_twd']//10000}萬（非必須）"
            stance = "允許"
        elif g["grade"] in ("B", "A", "S") and g["suggest_twd"] <= 0:
            lines.append(f"**觀測**（暫停新資金／示意 0 元）\n\n")
            title = f"{code}評等{g['grade']}｜觀測（暫不匯款）"
            stance = "觀測"
        else:
            lines.append("暫不買（**0** 元）\n\n")
            title = None
            stance = None
        lines.append(f"{g['reason']}  \n\n")

        if title and g["grade"] in ("B", "A", "S") and g["suggest_twd"] > 0:
            # 只推「真的可動用金額」；暫停IB的純觀測不洗版
            msg = (
                f"{g['reason']}\n"
                f"現價 {s['price']:.2f} ({s['change_pct']:+.2f}%)｜"
                f"上限 {g['suggest_twd']:,} 元｜大盤Level {level}"
            )
            rule = (
                "watch_grade_a"
                if g["grade"] in ("A", "S") and stance == "推薦"
                else "watch_grade_b"
            )
            actions.append((code, rule, title, msg))

    lines.append("## 推播摘要\n\n")
    if actions:
        for code, rule, title, _ in actions:
            tag = "推薦" if "推薦" in title else ("允許" if "允許" in title else "觀測")
            lines.append(f"* [{tag}] **{title}**\n")
    else:
        lines.append("* 無 B/A/S 可推項目（或皆為觀望）。\n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    for symbol, rule_id, title, msg in actions:
        notify(
            title=title,
            body=msg + "\n\n詳見 reports/latest/watch_grades.md",
            symbol=symbol,
            rule_id=rule_id,
            urgency="eod_action",
            force=("--force-notify" in sys.argv),
        )

    print(f"寫入 {REPORT_PATH}；推播候選 {len(actions)} 項")


if __name__ == "__main__":
    main()
