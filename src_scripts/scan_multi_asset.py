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

OZ_TO_GRAM = 31.1034768

# Gold budget from the 1M deployable cash plan
GOLD_BUDGET_TWD = 300_000
GOLD_TRANCHE_CAP = 100_000


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
        suggest = 0
    elif in_50 and not in_200 and not stabilized:
        grade, reason = "C", "剛進季線區但仍在下殺／未止穩，適合觀望或極小試單。"
        suggest = 0
    elif in_50 and not deep_peak and not stabilized:
        grade, reason = "C", "在季線區但回撤不深且未止穩（可能只是回測）。"
        suggest = 0
    elif in_50 and (deep_peak or in_200) and not stabilized:
        grade, reason = "B", "深度回撤／靠近年線，但尚未止穩 → 最多第一笔小額。"
        suggest = 80_000
    elif in_200 and deep_peak and stabilized and not deep_ma200:
        grade, reason = "B", "年線附近且略止穩，可第一笔；尚未到很棒加碼。"
        suggest = 100_000
    elif in_200 and deep_peak and deep_ma200 and stabilized:
        # check reclaim: price above 5-day MA of closes
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else px
        if px >= ma5:
            grade, reason = "A", "深回撤＋低於年線＋短線止穩，較佳分批買點。"
            suggest = 100_000
        else:
            grade, reason = "B", "位置不錯但短線均線未站回，先小額。"
            suggest = 80_000
    else:
        grade, reason = "B", "在規則買點內，採保守第一笔。"
        suggest = 80_000

    # S upgrade: A + consecutive strength + deep
    if grade == "A" and len(closes) >= 3:
        if px > closes[-2] and closes[-2] >= closes[-3]:
            if not fresh_low and bias200 <= -10 and from_peak <= -22:
                grade = "S"
                reason = "深回撤＋年線下＋連續止穩，屬較棒可執行買點（仍分批）。"
                suggest = 120_000

    suggest = min(int(suggest), 120_000 if grade == "S" else GOLD_TRANCHE_CAP)
    suggest = min(suggest, GOLD_BUDGET_TWD // 3)

    return {
        "grade": grade,
        "reason": reason,
        "suggest_twd": int(suggest),
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
    now = datetime.now()
    force = "--force" in sys.argv
    if not force and not (now.hour >= 18 or now.hour < 8):
        print("非晚間多資產視窗（18:00~08:00）且無 --force，退出。")
        sys.exit(0)

    rules = load_alert_rules()
    th = rules.get("thresholds") or {}
    gold_shock = float(th.get("gold_alert_pct", -5.0))
    btc_shock = float(th.get("crypto_alert_pct", -8.0))
    targets = load_targets()
    multi = targets.get("multi_asset") or {}
    cash = int(multi.get("deployable_cash_twd") or 1_000_000)

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

    actions = []
    lines = []
    lines.append("# 多資產買點評等與建議金額 (Gold / BTC)\n\n")
    lines.append(f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        f"可運用現金約 **{cash:,}** 元｜黃金預算上限約 **{GOLD_BUDGET_TWD:,}** 元（分 3 笔）  \n"
    )
    lines.append("> 評等 D/C=觀望；**B=允許小買（非必須）**；**A/S=較推薦分批**（仍禁止一次買滿）。  \n\n")

    if gold and usdtwd and gold.get("ma50"):
        g = grade_gold_buy(gold, usdtwd)
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
        lines.append(f"\n### 評等 **{g['grade']}**｜")
        if g["grade"] in ("A", "S"):
            lines.append(f"**推薦**分批，上限 **{g['suggest_twd']:,}** 元\n\n")
        elif g["grade"] == "B":
            lines.append(f"**允許**小買（非必須），上限 **{g['suggest_twd']:,}** 元\n\n")
        else:
            lines.append(f"暫不買（**0** 元）\n\n")
        lines.append(f"{g['reason']}  \n\n")

        if g["grade"] in ("B", "A", "S") and g["suggest_twd"] > 0:
            wan = g["suggest_twd"] // 10000
            if g["grade"] in ("A", "S"):
                title = f"黃金評等{g['grade']}｜推薦分批買（上限{wan}萬）"
                msg = (
                    f"評等 {g['grade']}：**推薦**可執行分批買入，本次上限約 **{g['suggest_twd']:,}** 元（不要超過）。\n"
                    f"{g['reason']}\n"
                    f"換算 {g['bot']:.0f} 元/g｜vs季線 {g['bias50']:+.1f}%｜vs年線 {g['bias200']:+.1f}%｜"
                    f"距高點 {g['from_peak']:+.1f}%｜止穩={'Y' if g['stabilized'] else 'N'}"
                )
                rule = "gold_buy_grade_a"
            else:
                title = f"黃金評等B｜允許小買上限{wan}萬（非必須）"
                msg = (
                    f"評等 B：規則上**允許**小買，上限約 **{g['suggest_twd']:,}** 元；"
                    f"**不是強烈推薦**，可不做。\n"
                    f"{g['reason']}\n"
                    f"換算 {g['bot']:.0f} 元/g｜vs季線 {g['bias50']:+.1f}%｜vs年線 {g['bias200']:+.1f}%｜"
                    f"距高點 {g['from_peak']:+.1f}%｜止穩={'Y' if g['stabilized'] else 'N'}\n"
                    f"（若已有黃金／外匯偏重，更傾向先按兵。）"
                )
                rule = "gold_buy_grade_b"
            urg = "eod_action"
            actions.append(("GOLD", rule, urg, title, msg))
        elif g["grade"] in ("C", "D"):
            title = f"黃金評等{g['grade']}｜暫不買"
            msg = (
                f"評等 {g['grade']}：本次 **0 元**（觀望）。\n{g['reason']}\n"
                f"換算 {g['bot']:.0f}｜距高點 {g['from_peak']:+.1f}%｜止穩={'Y' if g['stabilized'] else 'N'}"
            )
            # Only notify C/D when forced, to avoid spam — still write report
            if "--force-notify" in sys.argv:
                actions.append(("GOLD", "gold_wait", "eod_action", title, msg))

        if gold["change_pct"] <= gold_shock:
            msg = f"黃金急跌 {gold['change_pct']:+.2f}%（閾值 {gold_shock}%）。急跌中不追买。"
            actions.append(("GOLD", "asset_shock", "emergency", "黃金急跌警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    # FX USD/TWD — buy USD when weak (near/below 200MA)
    if usdtwd and usdtwd.get("ma200"):
        fx = usdtwd["price"]
        ma200 = usdtwd["ma200"]
        ma50 = usdtwd.get("ma50")
        bias200 = (fx - ma200) / ma200 * 100
        lines.append("## 匯率／外匯存摺 (USD)\n\n")
        lines.append(f"* USD/TWD：**{fx:.4f}** ({usdtwd['change_pct']:+.2f}%)  \n")
        lines.append(f"* 200MA：{ma200:.4f}（乖離 {bias200:+.2f}%）  \n")
        if ma50:
            lines.append(f"* 50MA：{ma50:.4f}  \n")
        pause_us = bool(multi.get("pause_us_ib"))
        # Sweet spot: at or below annual MA
        if fx <= ma200:
            amt = 50_000 if not pause_us else 30_000
            title = "美金偏弱｜可分批囤匯"
            msg = (
                f"USD/TWD {fx:.4f} ≤ 年均線 {ma200:.4f}（乖離 {bias200:+.1f}%）。\n"
                f"建議本次外匯分批約 **{amt:,}** 元台幣換匯（修復期小额）。"
            )
            actions.append(("USDTWD", "fx_buy_zone", "eod_action", title, msg))
            lines.append(f"* **訊號**：{msg.replace(chr(10), ' ')}  \n")
        elif bias200 >= 1.5:
            lines.append("* **狀態**：美元偏強，暫不追買外匯。  \n")
        else:
            lines.append("* **狀態**：靠近年均線，觀望。  \n")
        if usdtwd["change_pct"] >= float(th.get("twd_alert_pct", 0.40)):
            msg = f"台幣單日急貶／美元急升 {usdtwd['change_pct']:+.2f}%。外資撤資風險升高。"
            actions.append(("USDTWD", "asset_shock", "emergency", "匯率急貶警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    # US ETF watch (even if not held yet)
    lines.append("## 美股 ETF 觀測（尚未建倉也可提醒）\n\n")
    if multi.get("pause_us_ib"):
        lines.append("* 目前 **暫停 IB 新資金**；以下僅觀測跌深提醒，不建議立刻匯款買入。  \n")
    us_etf_th = float(th.get("us_etf_alert_pct", -5.0))
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
        lines.append(
            f"* **{sym} {name}**：{q['price']:.2f} ({q['change_pct']:+.2f}%)"
        )
        if bias200 is not None:
            lines.append(f"｜vs200MA {bias200:+.1f}%")
        lines.append("  \n")
        if q["change_pct"] <= us_etf_th:
            title = f"{sym} 急跌觀測"
            msg = (
                f"{sym} 單日 {q['change_pct']:+.2f}%（閾值 {us_etf_th}%）。\n"
                f"現價 {q['price']:.2f}"
                + (f"｜vs200MA {bias200:+.1f}%" if bias200 is not None else "")
                + ("\n（暫停 IB：只記錄，不建議立刻匯款追買）" if multi.get("pause_us_ib") else "\n可列入觀察買點。")
            )
            actions.append((sym, "us_etf_shock", "emergency", title, msg))
        if bias200 is not None and bias200 <= -8 and not multi.get("pause_us_ib"):
            title = f"{sym} 回撤至年線下"
            msg = f"{sym} 乖離年線 {bias200:+.1f}%，可規劃小額試倉（非一次滿倉）。"
            actions.append((sym, "us_etf_buy_zone", "eod_action", title, msg))
    lines.append("\n")

    if btc:
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
        if btc["change_pct"] <= btc_shock:
            msg = f"BTC 急跌 {btc['change_pct']:+.2f}%（閾值 {btc_shock}%）。"
            actions.append(("BTC", "asset_shock", "emergency", "BTC 急跌警戒", msg))
            lines.append(f"* **緊急**：{msg}  \n")
        lines.append("\n")

    lines.append("## 推播摘要\n\n")
    if actions:
        for _, _, urg, title, msg in actions:
            tag = "緊急" if urg == "emergency" else ("推薦" if "推薦" in title else ("允許" if "允許" in title else "通知"))
            lines.append(f"* [{tag}] **{title}**\n")
    else:
        lines.append("* 無推播項目。\n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    for symbol, rule_id, urgency, title, msg in actions:
        notify(
            title=title,
            body=msg + "\n\n詳見 reports/latest/multi_asset_levels.md",
            symbol=symbol,
            rule_id=rule_id,
            urgency=urgency,
            force=("--force-notify" in sys.argv),
        )

    print(f"報告已寫入 {REPORT_PATH}；觸發 {len(actions)} 項")


if __name__ == "__main__":
    main()
