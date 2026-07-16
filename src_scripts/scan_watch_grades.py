# -*- coding: utf-8 -*-
"""
觀測標的統一買點評等（比照黃金 D/C/B/A/S）：
  低於 buy_min → 觀望
  =門檻 → 允許買進（回測可買級｜非必須）
  高於門檻 → 建議買進（回測較優級）
  S → 強烈建議買進（回測實證高）

涵蓋 approved_universe / watchlist：0050、00631L、VOO、VXUS、QQQ、QQQM 等。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
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
from notify import notify, load_alert_rules, already_sent  # noqa: E402
from market_data import fetch_daily  # noqa: E402
from trade_levels import entry_plan_for_symbol  # noqa: E402
from tw_time import taiwan_now  # noqa: E402
from grade_buy_policy import (  # noqa: E402
    apply_policy_amount,
    cash_pool_snapshot,
    format_cash_pool_footer,
    load_grade_buy_policy,
    load_ladder_state,
    meets_buy_min,
    product_policy,
    push_short_label,
    push_verb,
    reset_ladder_cycle,
)
from eod_pending_ops import append_watch_ops  # noqa: E402


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
    end = taiwan_now().strftime("%Y-%m-%d")
    start = (taiwan_now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
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


def us_ib_go_signal(s: dict, g: dict, *, code: str, policy: Optional[dict] = None) -> tuple[bool, str]:
    """
    美股「可開始布局／匯款 IB」窗（僅 pause_us_ib=false 時才推播）。
    必須達該商品 buy_min_grade（VOO/VXUS≥S、QQQ≥B），避免低於門檻仍催匯款。
    """
    grade = str(g.get("grade") or "")
    if not grade or not meets_buy_min(grade, code, policy):
        return False, ""
    min_g = product_policy(code, policy).get("buy_min_grade") or "?"
    stab = bool(g.get("stabilized")) or _stabilized(s)
    px = s.get("price")
    ma50, ma200 = s.get("ma50"), s.get("ma200")
    bias50 = (px - ma50) / ma50 * 100 if ma50 and px else None
    bias200 = (px - ma200) / ma200 * 100 if ma200 and px else None

    if grade in ("A", "S"):
        return True, f"{code} 評等 {grade}≥門檻{min_g}（深拉回／月線區）"
    if (
        ma200
        and px
        and px > ma200
        and bias50 is not None
        and -3.0 <= bias50 <= 1.5
        and stab
    ):
        return True, f"{code} 評等 {grade}≥{min_g}｜年線上＋回測季線止穩"
    if bias200 is not None and bias200 <= -8 and stab:
        return True, f"{code} 評等 {grade}≥{min_g}｜年線下深回撤 {bias200:+.1f}% 止穩"
    return False, ""


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
    now = taiwan_now()
    force = "--force" in sys.argv
    # 允許收盤確認窗與晚間多資產窗（一律台北時間）
    hhmm = now.strftime("%H%M")
    in_close = "1300" <= hhmm <= "1430"
    in_evening = now.hour >= 18 or now.hour < 8
    if not force and not (in_close or in_evening):
        print(
            f"非評等視窗（台北 13:00~14:30 或晚間）且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    targets = load_targets()
    multi = targets.get("multi_asset") or {}
    cash = int(multi.get("deployable_cash_twd") or 2_000_000)
    pause_ib = bool(multi.get("pause_us_ib"))
    policy = load_grade_buy_policy()

    print("載入大盤與觀測報價…")
    taiex = fetch_symbol("TAIEX", "TW")
    level = macro_level(taiex) if taiex else 2

    lines = []
    lines.append("# 觀測標的買點評等（統一 D/C/B/A/S）\n\n")
    lines.append(f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n")
    lines.append(
        f"可運用現金約 **{cash:,}** 元｜大盤 Level：**{level}**"
    )
    if taiex and taiex.get("ma200"):
        lines.append(
            f"｜TAIEX {taiex['price']:.0f}／年線 {taiex['ma200']:.0f}"
            f"（{'上' if taiex['price'] > taiex['ma200'] else '下'}）"
        )
    lines.append("  \n")
    ladder_state = load_ladder_state()
    pool_snap = cash_pool_snapshot(ladder_state, policy)
    lines.append(
        f"常態池剩 **{pool_snap['routine_remaining']:,}**｜"
        f"**剩餘機會金 {pool_snap['opportunity_remaining']:,}** 元  \n"
    )
    lines.append(
        "> 評等維持真實 D/C/B/A/S；推播語氣依回測級距：\n"
        "> **允許買進**（=門檻）／**建議買進**（較優）／**強烈建議買進**（S・實證高）；"
        "ladder 升級=**請加碼**；flat 升級只改語氣不加碼。  \n"
        "> 個股破防守仍只在收盤確認窗推播。  \n\n"
    )

    actions = []
    us_ib_go: list[str] = []
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
            g = grade_growth_us(s, name, cash, pause_ib=False)
            if (not pause_ib) and market == "US":
                go, go_why = us_ib_go_signal(s, g, code=code, policy=policy)
                if go:
                    us_ib_go.append(go_why)
        else:
            g = grade_pullback_core(
                s,
                level=level if market == "TW" else 1,
                name=name,
                cash_cap=cash,
            )
            if market == "US" and not pause_ib:
                go, go_why = us_ib_go_signal(s, g, code=code, policy=policy)
                if go:
                    us_ib_go.append(go_why)

        applied = apply_policy_amount(
            code,
            g["grade"],
            policy=policy,
            pause_ib=pause_ib and market == "US",
            state=ladder_state,
        )
        g = dict(g)
        g["suggest_twd"] = int(applied["suggest_twd"])
        stance = applied["stance"]
        action = applied.get("action") or "none"
        min_g = applied.get("min_grade") or product_policy(code, policy).get(
            "buy_min_grade", "?"
        )
        filled = applied.get("max_grade_filled")
        if applied.get("blocked") == "pause_us_ib":
            g["reason"] = str(g.get("reason") or "") + "（暫停IB：只觀測、不推買）"

        # 出場重置：台股破 10MA；美股破 50MA（有階梯進度才重置）
        exit_hit = False
        if filled:
            if market == "TW" and s.get("ma10") and s["price"] < s["ma10"]:
                exit_hit = True
            elif market == "US" and s.get("ma50") and s["price"] < s["ma50"]:
                exit_hit = True
            if exit_hit:
                ladder_state = reset_ladder_cycle(code, state=ladder_state)
                filled = None

        lines.append(f"## {code} {name}\n\n")
        lines.append(
            f"* 價格：**{s['price']:.2f}** ({s['change_pct']:+.2f}%)｜來源 {s.get('source')}  \n"
        )
        if s.get("ma5"):
            lines.append(
                f"* 5/10/20MA：{s['ma5']:.2f}／{s.get('ma10') or '-'}／{s.get('ma20') or '-'}  \n"
            )
        if s.get("ma200") and g.get("bias200") is not None:
            lines.append(f"* 200MA：{s['ma200']:.2f}（乖離 {g['bias200']:+.1f}%）  \n")
        lines.append(f"* 止穩：{'是' if g.get('stabilized') else '否'}  \n")
        lines.append(
            f"* 推播門檻：≥**{min_g}**｜sizing=`{applied.get('sizing') or 'flat'}`"
            f"｜已填階 **{filled or '—'}**  \n"
        )
        if exit_hit:
            lines.append("* **出場重置**：破防守均線，階梯進度已清零  \n")
        lines.append(f"\n### 評等 **{g['grade']}**｜")
        title = None
        verb = push_verb(stance, action=action if action in ("enter", "add") else "enter")
        short = push_short_label(stance, action=action if action in ("enter", "add") else "enter")
        if (not exit_hit) and action == "add" and g["suggest_twd"] > 0:
            lines.append(f"**{verb}** **{g['suggest_twd']:,}** 元\n\n")
            title = f"{code}評等{g['grade']}｜{short}（{g['suggest_twd']//10000}萬）"
        elif (not exit_hit) and action == "enter" and g["suggest_twd"] > 0:
            lines.append(f"**{verb}** **{g['suggest_twd']:,}** 元\n\n")
            title = f"{code}評等{g['grade']}｜{short}（進場{g['suggest_twd']//10000}萬）"
        elif stance in ("recommend", "strong", "prefer") and applied.get("blocked") == "flat_no_add":
            lines.append(f"**{short}**（flat：升級不加碼，本次 **0** 元）\n\n")
        elif g["grade"] in ("B", "A", "S") and applied.get("blocked"):
            lines.append("**觀測**（暫停新資金／示意 0 元）\n\n")
        else:
            lines.append(f"暫不買（低於門檻 {min_g} 或 0 元）\n\n")
        lines.append(f"{g['reason']}  \n\n")
        entry_txt = entry_plan_for_symbol(
            s, code=code, market=market, grade=str(g.get("grade") or "")
        )
        lines.append("**進場／防守／停利**  \n")
        for ln in entry_txt.split("\n"):
            lines.append(f"* {ln}  \n")
        lines.append("\n")

        if title and action in ("enter", "add") and g["suggest_twd"] > 0:
            msg = (
                f"{g['reason']}\n"
                f"現價 {s['price']:.2f} ({s['change_pct']:+.2f}%)｜"
                f"門檻≥{min_g}｜**{verb}** 本次 {g['suggest_twd']:,} 元｜大盤Level {level}\n"
                f"{format_cash_pool_footer(code, state=ladder_state, policy=policy, suggest_twd=g['suggest_twd'])}\n\n"
                f"{entry_txt}\n"
                f"執行：收盤後／隔日開盤（EOD）。"
            )
            rule = (
                "watch_grade_s"
                if stance == "strong"
                else (
                    "watch_grade_a"
                    if action == "add" or stance in ("recommend", "prefer")
                    else "watch_grade_b"
                )
            )
            force_notify = "--force-notify" in sys.argv
            if not force_notify and already_sent(code, rule):
                lines.append(f"* **推播**：略過（24h 內已推 {g['grade']} 買點提醒）  \n")
            else:
                actions.append((code, rule, title, msg))
                if code in ("0050", "00631L") and (
                    "--save-pending" in sys.argv or now.hour >= 14
                ):
                    append_watch_ops(
                        now.strftime("%Y-%m-%d"),
                        code,
                        f"{title}｜{msg.split(chr(10))[0][:120]}",
                        as_of_ts=now.isoformat(timespec="seconds"),
                    )
    if pause_ib:
        lines.append("## IB 狀態\n\n")
        lines.append(
            "* **pause_us_ib=true**：修復期不推「請匯款 IB／買美金 ETF」。"
            "報告僅觀測；要恢復推播請把 config 改 false。  \n\n"
        )
    elif us_ib_go:
        uniq = []
        for x in us_ib_go:
            if x not in uniq:
                uniq.append(x)
        plan_bits = []
        for ucode in ("VOO", "VXUS", "QQQ"):
            us = fetch_symbol(ucode, "US")
            if us:
                plan_bits.append(
                    f"【{ucode}】\n"
                    + entry_plan_for_symbol(us, code=ucode, market="US", grade="")
                )
        title = "美股可布局｜可匯款 IB 開始操作"
        msg = (
            "偵測到美股 ETF 進入可布局／偏多窗：\n"
            + "\n".join(f"• {x}" for x in uniq)
            + "\n\n建議：匯款 IB → 核心 VOO:VXUS≈7:3 分批；成長袖 QQQ/QQQM 小於 VOO。"
        )
        if plan_bits:
            msg += "\n\n進場／防守／停利：\n" + "\n\n".join(plan_bits)
        actions.append(("US_IB", "us_ib_go", title, msg))
        lines.append("## IB 匯款提醒\n\n")
        lines.append(f"* **{title}**  \n")
        for x in uniq:
            lines.append(f"  * {x}  \n")
        lines.append("\n")

    lines.append("## 推播摘要\n\n")
    if actions:
        for code, rule, title, _ in actions:
            if rule == "us_ib_go":
                tag = "匯款IB"
            elif "強烈" in title:
                tag = "強烈建議"
            elif "建議買進" in title or "請加碼" in title:
                tag = "建議"
            elif "允許" in title:
                tag = "允許"
            else:
                tag = "觀測"
            lines.append(f"* [{tag}] **{title}**\n")
    else:
        lines.append("* 無達門檻可推項目（或暫停IB）。\n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    if actions:
        body_lines = [f"{i}. {title}\n{msg}" for i, (_, _, title, msg) in enumerate(actions, 1)]
        notify(
            title=f"觀測評等 {now.strftime('%m/%d %H:%M')}（台北｜{len(actions)} 項）",
            body="\n".join(body_lines)[:3500] + "\n\n詳見 reports/latest/watch_grades.md",
            symbol="WATCH",
            rule_id="watch_grades_digest",
            urgency="eod_action",
            force=("--force-notify" in sys.argv),
        )

    print(f"寫入 {REPORT_PATH}；推播候選 {len(actions)} 項")


if __name__ == "__main__":
    main()
