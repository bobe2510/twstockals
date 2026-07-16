# -*- coding: utf-8 -*-
"""
Multi-asset buy/sell zone scanner (gold passbook + BTC).
Gold: graded buy quality (D/C/B/A/S) + suggested TWD amount from deployable cash.
BTC: monitor / shock only when already overweight.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "multi_asset_levels.md")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from notify import notify, load_alert_rules  # noqa: E402
from market_data import fetch_daily  # noqa: E402
from tw_time import taiwan_now  # noqa: E402
from grade_buy_policy import (  # noqa: E402
    apply_policy_amount,
    cash_pool_snapshot,
    format_cash_pool_footer,
    load_grade_buy_policy,
    load_ladder_state,
    product_policy,
    push_short_label,
    push_verb,
    record_ladder_fill,
    reset_ladder_cycle,
)

OZ_TO_GRAM = 31.1034768

# Fallbacks if policy missing
GOLD_BUDGET_TWD = 600_000
GOLD_TRANCHE_CAP = 240_000


def gold_budget_and_room(multi: dict, bot_px: float, policy: dict) -> tuple[int, int, float]:
    """
    Return (budget, room_twd, held_approx).

    budget_scope=new_capital_only（預設）：budget = 自「新增可投資現金」可再投入黃金的上限，
    不扣既有公克市值（既有已投資另計）。
    若 budget_scope=total_sleeve：room = budget − 既有市值。
    """
    pol = product_policy("GOLD", policy)
    budget = int(pol.get("budget_twd") or GOLD_BUDGET_TWD)
    gp = multi.get("gold_passbook") or {}
    qty = float(gp.get("qty") or 0)
    held = qty * float(bot_px) if bot_px and qty else 0.0
    if gp.get("approx_twd"):
        try:
            held = float(gp["approx_twd"])
        except (TypeError, ValueError):
            pass
    scope = str(pol.get("budget_scope") or "new_capital_only")
    if scope == "total_sleeve":
        room = max(0, int(budget - held))
    else:
        room = max(0, int(budget))
    return budget, room, held


def grade_usd_fx(usdtwd: dict) -> dict:
    """對齊回測 grade_usd_i：囤匯評等。"""
    px = usdtwd["price"]
    closes = usdtwd.get("closes") or []
    ma200 = usdtwd.get("ma200")
    if not ma200 or len(closes) < 5:
        return {"grade": "D", "reason": "資料不足", "bias200": None, "stabilized": False}
    bias200 = (px - ma200) / ma200 * 100
    last5 = closes[-5:]
    fresh_low = px <= min(last5) * 1.001
    prev = usdtwd.get("prev") or closes[-2]
    up_day = px >= prev
    rising = len(closes) >= 3 and (
        closes[-1] >= closes[-2] or px > closes[-2]
    )
    stabilized = (not fresh_low) and (up_day or rising)
    if bias200 >= 1.5:
        return {
            "grade": "D",
            "reason": "美元偏強（乖離年線偏高），暫不追買外匯。",
            "bias200": bias200,
            "stabilized": stabilized,
        }
    if px > ma200:
        return {
            "grade": "C",
            "reason": "靠近年線上方，觀望。",
            "bias200": bias200,
            "stabilized": stabilized,
        }
    if bias200 <= -3 and stabilized:
        return {
            "grade": "S",
            "reason": "美元明顯偏弱且止穩，較佳囤匯窗。",
            "bias200": bias200,
            "stabilized": stabilized,
        }
    if bias200 <= -1.5 and stabilized:
        return {
            "grade": "A",
            "reason": "美元≤年線且偏弱止穩，可分批囤匯。",
            "bias200": bias200,
            "stabilized": stabilized,
        }
    return {
        "grade": "B",
        "reason": "美元≤年均線，規則上可小額（門檻要 A 以上才推播）。",
        "bias200": bias200,
        "stabilized": stabilized,
    }


def fetch_yahoo_history(sym: str, range_: str = "2y"):
    """Compat name: Stooq/Binance first, Yahoo fallback via market_data."""
    rows = fetch_daily(sym)
    if len(rows) < 5:
        print(f"market_data {sym} fail: insufficient rows")
        return None
    closes = [r["close"] for r in rows]
    px = closes[-1]
    prev = closes[-2]
    change_pct = ((px - prev) / prev) * 100 if prev else 0.0
    return {
        "symbol": sym,
        "price": px,
        "prev": prev,
        "change_pct": change_pct,
        "closes": closes,
        "ma50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
        "ma200": sum(closes[-200:]) / 200 if len(closes) >= 200 else None,
        "source": rows[-1].get("source"),
    }


def load_targets():
    if not os.path.exists(TARGETS_PATH):
        return {}
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def grade_gold_buy(gold: dict, usdtwd: dict) -> dict:
    """
    Grade buy quality after mania/mean-reversion:
      D = not in zone / wait
      C = in 50MA zone but unstable (watch only or tiny)
      B = in zone + mild depth (first small tranche OK)
      A = deep vs peak + below 200MA + short-term stabilize
      S = A + reclaim 5-day strength (best actionable add)
    """
    px = gold["price"]
    closes = gold.get("closes") or []
    ma50 = gold["ma50"]
    ma200 = gold["ma200"]
    fx = usdtwd["price"]
    bot = px * fx / OZ_TO_GRAM
    bot50 = ma50 * fx / OZ_TO_GRAM if ma50 else None
    bot200 = ma200 * fx / OZ_TO_GRAM if ma200 else None

    peak = max(closes[-252:]) if len(closes) >= 252 else (max(closes) if closes else px)
    from_peak = (px - peak) / peak * 100 if peak else 0.0
    bias50 = (px - ma50) / ma50 * 100 if ma50 else 0.0
    bias200 = (px - ma200) / ma200 * 100 if ma200 else 0.0

    last5 = closes[-5:] if len(closes) >= 5 else closes[:]
    # stabilize: today not making fresh 5-day low, and close >= prev day
    fresh_low = bool(last5) and px <= min(last5) * 1.001
    up_day = px >= gold["prev"] if gold.get("prev") else False
    # 3-day rising lows soft check
    rising = False
    if len(closes) >= 3:
        rising = closes[-1] >= closes[-2] >= closes[-3] or (
            px > closes[-2] and closes[-2] > min(closes[-5:-1]) if len(closes) >= 5 else False
        )
    stabilized = (not fresh_low) and (up_day or rising)

    in_50 = bot50 is not None and bot <= bot50
    in_200 = bot200 is not None and bot <= bot200 * 1.02
    deep_peak = from_peak <= -20  # >=20% off peak
    deep_ma200 = bias200 <= -8

    if not in_50:
        grade, reason = "D", "尚未進入季線買點區，等待拉回。"
    elif in_50 and not in_200 and not stabilized:
        grade, reason = "C", "剛進季線區但仍在下殺／未止穩，適合觀望或極小試單。"
    elif in_50 and not deep_peak and not stabilized:
        grade, reason = "C", "在季線區但回撤不深且未止穩（可能只是回測）。"
    elif in_50 and (deep_peak or in_200) and not stabilized:
        grade, reason = "B", "深度回撤／靠近年線，但尚未止穩 → 最多第一笔小額。"
    elif in_200 and deep_peak and stabilized and not deep_ma200:
        grade, reason = "B", "年線附近且略止穩，可第一笔；尚未到很棒加碼。"
    elif in_200 and deep_peak and deep_ma200 and stabilized:
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else px
        if px >= ma5:
            grade, reason = "A", "深回撤＋低於年線＋短線止穩，較佳分批買點。"
        else:
            grade, reason = "B", "位置不錯但短線均線未站回，先小額。"
    else:
        grade, reason = "B", "在規則買點內，採保守第一笔。"

    if grade == "A" and len(closes) >= 3:
        if px > closes[-2] and closes[-2] >= closes[-3]:
            if not fresh_low and bias200 <= -10 and from_peak <= -22:
                grade = "S"
                reason = "深回撤＋年線下＋連續止穩，屬較棒可執行買點（仍分批）。"

    return {
        "grade": grade,
        "reason": reason,
        "suggest_twd": 0,
        "bot": bot,
        "bot50": bot50,
        "bot200": bot200,
        "from_peak": from_peak,
        "bias50": bias50,
        "bias200": bias200,
        "stabilized": stabilized,
        "fresh_low": fresh_low,
        "peak": peak,
    }


def main():
    now = taiwan_now()
    force = "--force" in sys.argv
    day_mode = "--day" in sys.argv or "--multi-day" in sys.argv
    hhmm = now.strftime("%H%M")
    # 上班執行窗 10:00~15:30；晚間 18:00~08:00；或 --force / --day
    in_bank = "1000" <= hhmm <= "1530"
    in_evening = now.hour >= 18 or now.hour < 8
    if not force and not day_mode and not in_evening and not in_bank:
        print(
            f"非多資產視窗（台北銀行 10:00~15:30 或晚間）且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    policy = load_grade_buy_policy()
    rules = load_alert_rules()
    th = rules.get("thresholds") or {}
    gold_shock = float(th.get("gold_alert_pct", -5.0))
    btc_shock = float(th.get("crypto_alert_pct", -8.0))
    targets = load_targets()
    multi = targets.get("multi_asset") or {}
    cash = int(multi.get("deployable_cash_twd") or 2_000_000)
    pause_us = bool(multi.get("pause_us_ib"))

    pause_crypto_add = True
    crypto_approx = None
    for c in multi.get("crypto") or []:
        if c.get("approx_twd_total_crypto"):
            crypto_approx = c["approx_twd_total_crypto"]
            break
    if crypto_approx and crypto_approx >= 250000:
        pause_crypto_add = True

    gold = fetch_yahoo_history("GC=F")
    usdtwd = fetch_yahoo_history("USDTWD=X", "1y")
    btc = fetch_yahoo_history("BTC-USD")

    # day mode：略過美股 ETF 區塊（仍寫黃金／外匯；BTC 可選）
    skip_us_block = day_mode

    actions = []
    lines = []
    window_label = "上班窗" if day_mode or (in_bank and not in_evening) else "晚間窗"
    lines.append("# 多資產買點評等與建議金額 (Gold / FX / BTC / ETH)\n\n")
    lines.append(f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北｜{window_label}）  \n")
    ladder_state = load_ladder_state()
    pool_snap = cash_pool_snapshot(ladder_state, policy)
    lines.append(
        f"可運用現金約 **{cash:,}** 元｜門檻推播：≥該商品 buy_min_grade 才推買  \n"
    )
    lines.append(
        f"常態池 **{pool_snap['routine_budget']:,}**（剩 {pool_snap['routine_remaining']:,}）｜"
        f"**剩餘機會金 {pool_snap['opportunity_remaining']:,}**／池 {pool_snap['opportunity_budget']:,}  \n"
    )
    lines.append(
        "> 評等維持真實 D/C/B/A/S；語氣依回測級距："
        "**允許買進**／**建議買進**／**強烈建議買進（S）**；"
        "ladder 升級=**請加碼**；flat 升級只改語氣不加碼。  \n\n"
    )

    if gold and usdtwd and gold.get("ma50"):
        g = grade_gold_buy(gold, usdtwd)
        budget, room, held = gold_budget_and_room(multi, g["bot"], policy)
        applied = apply_policy_amount(
            "GOLD",
            g["grade"],
            policy=policy,
            room_twd=room,
            state=ladder_state,
        )
        g["suggest_twd"] = int(applied["suggest_twd"])
        stance = applied["stance"]
        action = applied.get("action") or "none"
        min_g = applied.get("min_grade") or "B"
        filled = applied.get("max_grade_filled")

        lines.append("## 黃金存摺\n\n")
        lines.append(f"* 國際金價：{gold['price']:.2f} USD ({gold['change_pct']:+.2f}%)  \n")
        lines.append(f"* 匯率 USD/TWD：{usdtwd['price']:.4f}  \n")
        lines.append(f"* 台銀換算：**{g['bot']:.2f}** 元/公克  \n")
        lines.append(f"* 季線區：{g['bot50']:.2f}（乖離 {g['bias50']:+.1f}%）  \n")
        lines.append(f"* 年線區：{g['bot200']:.2f}（乖離 {g['bias200']:+.1f}%）  \n")
        lines.append(
            f"* 距近一年高點：{g['from_peak']:+.1f}%（高點約 {g['peak']:.0f} USD）  \n"
        )
        lines.append(
            f"* 短線止穩：{'是' if g['stabilized'] else '否'}"
            f"{'／仍近新低' if g['fresh_low'] else ''}  \n"
        )
        gp = multi.get("gold_passbook") or {}
        qty = gp.get("qty")
        if qty:
            lines.append(
                f"* 既有約 **{qty}** 公克｜市值約 **{held:,.0f}** 元（已投資另計）｜"
                f"新增現金可再投黃金上限 **{budget:,}**／本次剩餘額度 **{room:,}** 元  \n"
            )
        lines.append(
            f"* 推播門檻：≥**{min_g}**｜sizing=`{applied.get('sizing') or 'flat'}`"
            f"｜已填階 **{filled or '—'}**  \n"
        )
        lines.append(f"\n### 評等 **{g['grade']}**｜")
        verb = push_verb(stance, action=action if action in ("enter", "add") else "enter")
        short = push_short_label(stance, action=action if action in ("enter", "add") else "enter")
        if action == "add" and g["suggest_twd"] > 0:
            lines.append(f"**{verb}**，本次 **{g['suggest_twd']:,}** 元\n\n")
        elif action == "enter" and g["suggest_twd"] > 0:
            lines.append(f"**{verb}**，本次 **{g['suggest_twd']:,}** 元\n\n")
        elif stance in ("recommend", "strong", "prefer") and applied.get("blocked") == "flat_no_add":
            lines.append(f"**{short}**（flat：升級不加碼，本次 **0** 元）\n\n")
        elif g["grade"] in ("B", "A", "S") and room <= 0:
            lines.append("預算已滿／無剩餘額度（**0** 元）\n\n")
        else:
            lines.append(f"暫不買（低於門檻 {min_g}、同階已推、或金額 0）\n\n")
        lines.append(f"{g['reason']}  \n\n")

        # 出場優先：站回 50MA → 重置階梯、不推買
        above_50 = bool(gold.get("ma50") and gold["price"] > gold["ma50"])
        if above_50:
            sell_note = product_policy("GOLD", policy).get("sell_note") or (
                "國際金價站回 50MA → 可減／暫不加"
            )
            lines.append(f"* **出場參考**：{sell_note}  \n")
            if filled or int(applied.get("invested_twd") or 0) > 0:
                ladder_state = reset_ladder_cycle("GOLD", state=ladder_state)
            if qty:
                actions.append(
                    (
                        "GOLD",
                        "gold_sell_zone",
                        "eod_action",
                        "黃金站回季線｜可減／暫不加",
                        f"{sell_note}\n現價 {gold['price']:.2f} > 50MA {gold['ma50']:.2f}。",
                    )
                )
        elif action in ("enter", "add") and g["suggest_twd"] > 0:
            wan = g["suggest_twd"] // 10000
            title = f"黃金評等{g['grade']}｜{short}（{wan}萬）"
            rule = (
                "gold_buy_grade_s"
                if stance == "strong"
                else (
                    "gold_buy_grade_a"
                    if action == "add" or stance in ("recommend", "prefer")
                    else "gold_buy_grade_b"
                )
            )
            msg = (
                f"評等 {g['grade']}（門檻≥{min_g}）：**{verb}**，"
                f"本次約 **{g['suggest_twd']:,}** 元"
                f"（剩餘額度 {room:,}／預算 {budget:,}）。\n"
                f"{format_cash_pool_footer('GOLD', state=ladder_state, policy=policy, suggest_twd=g['suggest_twd'])}\n"
                f"{g['reason']}\n"
                f"換算 {g['bot']:.0f} 元/g｜vs季線 {g['bias50']:+.1f}%｜vs年線 {g['bias200']:+.1f}%｜"
                f"距高點 {g['from_peak']:+.1f}%｜止穩={'Y' if g['stabilized'] else 'N'}\n"
                f"執行：台銀 App（銀行營業時間）。"
            )
            actions.append(("GOLD", rule, "eod_action", title, msg))
            ladder_state = record_ladder_fill(
                "GOLD", g["grade"], g["suggest_twd"], action, state=ladder_state
            )

        if gold["change_pct"] <= gold_shock:
            msg = f"黃金急跌 {gold['change_pct']:+.2f}%（閾值 {gold_shock}%）。急跌中不追买。"
            actions.append(("GOLD", "asset_shock", "emergency", "黃金急跌警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    if usdtwd and usdtwd.get("ma200"):
        fx = usdtwd["price"]
        ma200 = usdtwd["ma200"]
        ma50 = usdtwd.get("ma50")
        ug = grade_usd_fx(usdtwd)
        applied = apply_policy_amount(
            "USDTWD", ug["grade"], policy=policy, state=ladder_state
        )
        amt = int(applied["suggest_twd"])
        stance = applied["stance"]
        action = applied.get("action") or "none"
        min_g = applied.get("min_grade") or "A"
        bias200 = ug.get("bias200")

        lines.append("## 匯率／外匯存摺 (USD)\n\n")
        lines.append(f"* USD/TWD：**{fx:.4f}** ({usdtwd['change_pct']:+.2f}%)  \n")
        lines.append(f"* 200MA：{ma200:.4f}（乖離 {bias200:+.2f}%）  \n")
        if ma50:
            lines.append(f"* 50MA：{ma50:.4f}  \n")
        lines.append(
            f"* 評等 **{ug['grade']}**｜推播門檻 ≥**{min_g}**"
            f"｜已填階 **{applied.get('max_grade_filled') or '—'}**  \n"
        )
        lines.append(f"* {ug['reason']}  \n")

        if action in ("enter", "add") and amt > 0:
            verb = push_verb(
                stance,
                action=action,
                kind="add" if action == "add" else "fx",
            )
            short = (
                "請加碼囤匯"
                if action == "add"
                else {
                    "allow": "允許囤匯",
                    "buy": "允許囤匯",
                    "recommend": "建議囤匯",
                    "prefer": "建議囤匯",
                    "strong": "強烈建議囤匯",
                }.get(str(stance or ""), "允許囤匯")
            )
            title = f"美金評等{ug['grade']}｜{short}（{amt // 10000}萬）"
            msg = (
                f"USD/TWD {fx:.4f}｜評等 {ug['grade']}（門檻≥{min_g}）。\n"
                f"{ug['reason']}\n"
                f"**{verb}** 本次約 **{amt:,}** 元台幣換匯（台銀 App）。\n"
                f"{format_cash_pool_footer('USDTWD', state=ladder_state, policy=policy, suggest_twd=amt)}"
            )
            actions.append(("USDTWD", "fx_buy_zone", "eod_action", title, msg))
            lines.append(f"* **推播**：{title}  \n")
            ladder_state = record_ladder_fill(
                "USDTWD", ug["grade"], amt, action, state=ladder_state
            )
        elif stance in ("recommend", "strong", "prefer") and applied.get("blocked") == "flat_no_add":
            lines.append("* **狀態**：建議級（flat：升級不加碼）。  \n")
        elif bias200 is not None and bias200 >= 1.5:
            sell_note = product_policy("USDTWD", policy).get("sell_note") or (
                "美元偏強，暫不囤匯"
            )
            lines.append(f"* **狀態**：{sell_note}  \n")
            ladder_state = reset_ladder_cycle("USDTWD", state=ladder_state)
            actions.append(
                (
                    "USDTWD",
                    "fx_sell_zone",
                    "eod_action",
                    "美金偏強｜暫不囤匯",
                    f"{sell_note}\nUSD/TWD {fx:.4f}｜乖離年線 {bias200:+.1f}%。",
                )
            )
        else:
            lines.append("* **狀態**：未達推播門檻／同階已推，觀望。  \n")

        if usdtwd["change_pct"] >= float(th.get("twd_alert_pct", 0.40)):
            msg = f"台幣單日急貶／美元急升 {usdtwd['change_pct']:+.2f}%。外資撤資風險升高。"
            actions.append(("USDTWD", "asset_shock", "emergency", "匯率急貶警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    if not skip_us_block:
        lines.append("## 美股 ETF 觀測（尚未建倉也可提醒）\n\n")
        if pause_us:
            lines.append(
                "* 目前 **暫停 IB 新資金**：美股 ETF **只寫報告、不推播買點／匯款**。  \n"
            )
        us_etf_th = float(th.get("us_etf_alert_pct", -5.0))
        us_ib_notes: list[str] = []
        for sym, name in [
            ("VOO", "Vanguard S&P500"),
            ("VXUS", "Vanguard International ex-US"),
            ("QQQ", "Nasdaq100"),
        ]:
            q = fetch_yahoo_history(sym, "1y")
            if not q:
                continue
            bias200 = (
                (q["price"] - q["ma200"]) / q["ma200"] * 100 if q.get("ma200") else None
            )
            bias50 = (
                (q["price"] - q["ma50"]) / q["ma50"] * 100 if q.get("ma50") else None
            )
            lines.append(
                f"* **{sym} {name}**：{q['price']:.2f} ({q['change_pct']:+.2f}%)"
            )
            if bias200 is not None:
                lines.append(f"｜vs200MA {bias200:+.1f}%")
            if bias50 is not None:
                lines.append(f"｜vs50MA {bias50:+.1f}%")
            lines.append("  \n")
            if q["change_pct"] <= us_etf_th:
                title = f"{sym} 急跌觀測"
                msg = (
                    f"{sym} 單日 {q['change_pct']:+.2f}%（閾值 {us_etf_th}%）。\n"
                    f"現價 {q['price']:.2f}"
                    + (f"｜vs200MA {bias200:+.1f}%" if bias200 is not None else "")
                    + (
                        "\n（pause_us_ib：只警戒、不建議匯款追買）"
                        if pause_us
                        else "\n急跌日不追；若之後止穩再評估。"
                    )
                )
                actions.append((sym, "us_etf_shock", "emergency", title, msg))
            if bias200 is not None and bias200 <= -8:
                us_ib_notes.append(f"{sym} 年線下深回撤 {bias200:+.1f}%")
            elif (
                q.get("ma200")
                and q["price"] > q["ma200"]
                and bias50 is not None
                and -3.0 <= bias50 <= 1.5
            ):
                us_ib_notes.append(f"{sym} 年線上＋回測季線（乖離 {bias50:+.1f}%）")
            # 買點一律走觀測評等門檻（VOO/VXUS≥S、QQQ≥B），此處不再另推「試倉」

        if us_ib_notes:
            tag = "僅觀測，暫停推播" if pause_us else "詳見晚間觀測評等推播"
            lines.append(f"* **布局窗（{tag}）**：" + "；".join(us_ib_notes) + "  \n")
        lines.append("\n")

    if btc and not (day_mode and "--skip-btc" in sys.argv):
        lines.append("## 比特幣\n\n")
        lines.append(f"* 價格：{btc['price']:,.2f} USD ({btc['change_pct']:+.2f}%)  \n")
        if btc.get("ma50"):
            bias50 = (btc["price"] - btc["ma50"]) / btc["ma50"] * 100
            lines.append(f"* 50MA：{btc['ma50']:,.2f}（乖離 {bias50:+.2f}%）  \n")
        if btc.get("ma200"):
            bias200 = (btc["price"] - btc["ma200"]) / btc["ma200"] * 100
            lines.append(f"* 200MA：{btc['ma200']:,.2f}（乖離 {bias200:+.2f}%）  \n")
        if pause_crypto_add:
            lines.append("* **加碼：暫停**（既有部位已偏高）。建議金額 **0**。  \n")
        if btc.get("ma50") and btc["price"] < btc["ma50"]:
            sell_note = product_policy("BTC-USD", policy).get("sell_note") or (
                "破 50MA 可減（既有偏重則不加碼）"
            )
            bias50 = (btc["price"] - btc["ma50"]) / btc["ma50"] * 100
            lines.append(f"* **出場參考**：{sell_note}  \n")
            actions.append(
                (
                    "BTC",
                    "crypto_sell_zone",
                    "eod_action",
                    "BTC 破季線可減",
                    f"{sell_note}\n現價 {btc['price']:,.2f} < 50MA {btc['ma50']:,.2f}"
                    f"（乖離 {bias50:+.1f}%）。不加碼；反彈再評估減碼。",
                )
            )
        if btc["change_pct"] <= btc_shock:
            msg = f"BTC 急跌 {btc['change_pct']:+.2f}%（閾值 {btc_shock}%）。"
            actions.append(("BTC", "asset_shock", "emergency", "BTC 急跌警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    eth = None if (day_mode and "--skip-btc" in sys.argv) else fetch_yahoo_history("ETH-USD")
    if eth:
        lines.append("## 以太坊\n\n")
        lines.append(f"* 價格：{eth['price']:,.2f} USD ({eth['change_pct']:+.2f}%)  \n")
        if eth.get("ma50"):
            bias50 = (eth["price"] - eth["ma50"]) / eth["ma50"] * 100
            lines.append(f"* 50MA：{eth['ma50']:,.2f}（乖離 {bias50:+.2f}%）  \n")
        if eth.get("ma200"):
            bias200 = (eth["price"] - eth["ma200"]) / eth["ma200"] * 100
            lines.append(f"* 200MA：{eth['ma200']:,.2f}（乖離 {bias200:+.2f}%）  \n")
        if pause_crypto_add:
            lines.append("* **加碼：暫停**（既有部位已偏高）。建議金額 **0**。  \n")
        if eth.get("ma50") and eth["price"] < eth["ma50"]:
            sell_note = product_policy("ETH-USD", policy).get("sell_note") or (
                "破 50MA 可減（既有偏重則不加碼）"
            )
            bias50 = (eth["price"] - eth["ma50"]) / eth["ma50"] * 100
            lines.append(f"* **出場參考**：{sell_note}  \n")
            actions.append(
                (
                    "ETH",
                    "crypto_sell_zone",
                    "eod_action",
                    "ETH 破季線可減",
                    f"{sell_note}\n現價 {eth['price']:,.2f} < 50MA {eth['ma50']:,.2f}"
                    f"（乖離 {bias50:+.1f}%）。不加碼；反彈再評估減碼／換 USDT。",
                )
            )
        if eth["change_pct"] <= btc_shock:
            msg = f"ETH 急跌 {eth['change_pct']:+.2f}%（閾值 {btc_shock}%）。"
            actions.append(("ETH", "asset_shock", "emergency", "ETH 急跌警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    lines.append("## 推播摘要\n\n")
    if actions:
        for _, _, urg, title, msg in actions:
            if urg == "emergency":
                tag = "緊急"
            elif "強烈" in title:
                tag = "強烈建議"
            elif "建議" in title or "請加碼" in title:
                tag = "建議"
            elif "允許" in title or "請買進" in title or "請囤匯" in title:
                tag = "允許"
            else:
                tag = "通知"
            lines.append(f"* [{tag}] **{title}**\n")
    else:
        lines.append("* 無推播項目。\n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    if actions:
        body_lines = []
        for i, (_, _, urg, title, msg) in enumerate(actions, 1):
            tag = "🚨" if urg == "emergency" else "📋"
            body_lines.append(f"{tag} {i}. {title}\n{msg}")
        top_urg = "emergency" if any(a[2] == "emergency" for a in actions) else "eod_action"
        notify(
            title=f"多資產摘要 {now.strftime('%m/%d %H:%M')}（台北｜{len(actions)} 項）",
            body="\n".join(body_lines)[:3500] + "\n\n詳見 reports/latest/multi_asset_levels.md",
            symbol="MULTI",
            rule_id="multi_asset_digest",
            urgency=top_urg,
            force=("--force-notify" in sys.argv),
        )

    print(f"報告已寫入 {REPORT_PATH}；觸發 {len(actions)} 項")


if __name__ == "__main__":
    main()
