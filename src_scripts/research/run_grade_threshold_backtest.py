# -*- coding: utf-8 -*-
"""
評等門檻回測：同一套觀測評等 (S/A/B/C/D)，比較五種進場門檻。
  - S / A+ / B+ / C+ / D+（該級以上才買）

商品／評測窗：
  - 0050、00631L、VOO、VXUS、QQQ、黃金、美金：5 年
  - BTC：2 年（均線用更長歷史暖機）
  - USDT：不做

黃金另做「分批金額」最佳化（在冠軍門檻下，搜尋 B/A/S 各筆建議金額）。

規則對齊 scan_watch_grades / scan_multi_asset；EOD 訊號、隔日開盤（無開盤則收盤）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

def _find_workspace() -> str:
    env = os.environ.get("TWSTOCKALS_WORKSPACE")
    if env:
        return env
    d = os.path.abspath(os.path.dirname(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(d, "config", "my_targets.json")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


WORKSPACE = _find_workspace()
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from run_etf_backtest import download_full_history, get_metrics  # noqa: E402
from market_data import fetch_daily, fetch_yahoo_daily  # noqa: E402

INITIAL = 1_000_000.0
YEARS = 5
OZ_TO_GRAM = 31.1034768
WARMUP_BARS = 220

# 成本情境（單邊費率 (買, 賣)）：
#   legacy＝舊報告假設（黃金／美金／美股皆 0.1%；台股 ETF 誤用個股稅 0.3%）
#   real  ＝實際價差：台銀黃金存摺 ~0.5%/邊、台銀美金即期 ~0.15%/邊、
#           台股 ETF 手續費0.1425%+滑價0.05%（賣加 ETF 稅 0.1%）、
#           IB 美股 ~0.07%/邊、幣安 taker 0.1%+滑價0.05%
COST_SCENARIOS = {
    "legacy": {
        "gold": (0.001, 0.001),
        "usd": (0.001, 0.001),
        "tw_etf": (0.001425, 0.001425 + 0.003),
        "us_etf": (0.001, 0.001),
        "crypto": (0.001, 0.001),
    },
    "real": {
        "gold": (0.005, 0.005),
        "usd": (0.0015, 0.0015),
        "tw_etf": (0.001925, 0.002925),
        "us_etf": (0.0007, 0.0007),
        "crypto": (0.0015, 0.0015),
    },
}
COST_SCENARIO = "real"
COSTS = COST_SCENARIOS[COST_SCENARIO]

# 向後相容：ladder/momentum/shortlist/playbook 腳本仍 import 這些（維持 legacy 值）
COMM_TW = 0.001425
TAX_TW = 0.003
COMM_US = 0.001

GRADE_RANK = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}
MODES = ["S", "A+", "B+", "C+", "D+"]
MODE_MIN_RANK = {"S": 4, "A+": 3, "B+": 2, "C+": 1, "D+": 0}

# 黃金預算與現行分批（與 scan_multi_asset 對齊）
GOLD_BUDGET = 300_000.0
GOLD_LIVE_TRANCHE = {"S": 120_000.0, "A": 100_000.0, "B": 80_000.0, "C": 0.0, "D": 0.0}


def meets_threshold(grade: str, mode: str) -> bool:
    r = GRADE_RANK.get(grade, 0)
    return r >= MODE_MIN_RANK.get(mode, 99)


def _stabilized_row(closes: np.ndarray, i: int) -> bool:
    px = closes[i]
    prev = closes[i - 1] if i >= 1 else px
    last5 = closes[max(0, i - 4) : i + 1]
    fresh_low = px <= float(np.min(last5)) * 1.001
    up_day = px >= prev
    rising = False
    if i >= 2:
        rising = closes[i] >= closes[i - 1] or px > closes[i - 2]
    return (not fresh_low) and (up_day or rising)


def macro_level_from(closes: np.ndarray, i: int) -> int:
    if i < 19:
        return 2
    ma20 = float(np.mean(closes[i - 19 : i + 1]))
    px = closes[i]
    if px < ma20:
        return 3
    bias = (px - ma20) / ma20 * 100
    if bias <= 1.5:
        return 2
    return 1


def grade_pullback_core_i(closes: np.ndarray, i: int, level: int) -> str:
    if i < 199:
        return "D"
    px = closes[i]
    ma5 = float(np.mean(closes[i - 4 : i + 1]))
    ma10 = float(np.mean(closes[i - 9 : i + 1]))
    ma20 = float(np.mean(closes[i - 19 : i + 1]))
    ma200 = float(np.mean(closes[i - 199 : i + 1]))
    stab = _stabilized_row(closes, i)
    bias5 = (px - ma5) / ma5 * 100
    bias10 = (px - ma10) / ma10 * 100
    bias20 = (px - ma20) / ma20 * 100

    if level >= 3:
        return "D"
    if bias5 > 3 and bias10 > 5:
        return "D"
    near5 = abs(bias5) <= 1.5
    near10 = abs(bias10) <= 2.0
    near20 = -4 <= bias20 <= 1.0
    deep20 = bias20 <= -4

    if level == 2 and not (near20 or deep20):
        return "C"
    if (near5 or near10) and stab and level == 1:
        return "B"
    if (near5 or near10) and not stab:
        return "C"
    if near20 and stab and level == 1:
        return "A"
    if deep20 and stab and level == 1:
        return "S"
    if near20 or deep20:
        return "B"
    return "D"


def grade_lev_i(closes: np.ndarray, taiex: np.ndarray, i: int, level: int) -> str:
    if i < 199 or len(taiex) <= i:
        return "D"
    above200 = taiex[i] > float(np.mean(taiex[i - 199 : i + 1]))
    px = closes[i]
    ma10 = float(np.mean(closes[i - 9 : i + 1]))
    ma20 = float(np.mean(closes[i - 19 : i + 1]))
    stab = _stabilized_row(closes, i)
    bias10 = (px - ma10) / ma10 * 100
    bias20 = (px - ma20) / ma20 * 100

    if level >= 3:
        return "D"
    if not above200:
        return "D"
    if level == 2:
        return "C"
    if bias10 > 4 and bias20 > 6:
        return "D"
    if abs(bias10) <= 2.5 and stab:
        return "B"
    if -5 <= bias20 <= 1 and stab:
        return "A"
    if bias20 < -5 and stab:
        return "S"
    return "C"


def grade_growth_us_i(closes: np.ndarray, i: int) -> str:
    if i < 199:
        return "D"
    px = closes[i]
    ma50 = float(np.mean(closes[i - 49 : i + 1]))
    ma200 = float(np.mean(closes[i - 199 : i + 1]))
    stab = _stabilized_row(closes, i)
    bias50 = (px - ma50) / ma50 * 100
    bias200 = (px - ma200) / ma200 * 100

    if bias50 > 4:
        return "D"
    if -2 <= bias50 <= 2 and stab:
        return "B"
    if bias200 <= -8 and stab:
        return "A"
    if bias200 <= -3:
        return "C"
    return "D"


def grade_gold_i(gold_closes: np.ndarray, fx_closes: np.ndarray, i: int) -> str:
    """對齊 scan_multi_asset.grade_gold_buy（用國際金價＋匯率換算台銀價）。"""
    if i < 199 or i >= len(fx_closes):
        return "D"
    px = float(gold_closes[i])
    fx = float(fx_closes[i])
    closes = gold_closes[: i + 1]
    ma50 = float(np.mean(closes[i - 49 : i + 1]))
    ma200 = float(np.mean(closes[i - 199 : i + 1]))
    bot = px * fx / 31.1034768
    bot50 = ma50 * fx / 31.1034768
    bot200 = ma200 * fx / 31.1034768
    peak = float(np.max(closes[max(0, i - 251) : i + 1]))
    from_peak = (px - peak) / peak * 100 if peak else 0.0
    bias200 = (px - ma200) / ma200 * 100

    last5 = closes[max(0, i - 4) : i + 1]
    fresh_low = px <= float(np.min(last5)) * 1.001
    prev = float(closes[i - 1]) if i >= 1 else px
    up_day = px >= prev
    rising = False
    if i >= 2:
        rising = closes[i] >= closes[i - 1] or (
            px > closes[i - 1] and closes[i - 1] > float(np.min(closes[max(0, i - 4) : i]))
        )
    stabilized = (not fresh_low) and (up_day or rising)

    in_50 = bot <= bot50
    in_200 = bot <= bot200 * 1.02
    deep_peak = from_peak <= -20
    deep_ma200 = bias200 <= -8

    if not in_50:
        grade = "D"
    elif in_50 and not in_200 and not stabilized:
        grade = "C"
    elif in_50 and not deep_peak and not stabilized:
        grade = "C"
    elif in_50 and (deep_peak or in_200) and not stabilized:
        grade = "B"
    elif in_200 and deep_peak and stabilized and not deep_ma200:
        grade = "B"
    elif in_200 and deep_peak and deep_ma200 and stabilized:
        ma5 = float(np.mean(closes[i - 4 : i + 1]))
        grade = "A" if px >= ma5 else "B"
    else:
        grade = "B"

    if grade == "A" and i >= 2:
        if px > closes[i - 1] and closes[i - 1] >= closes[i - 2]:
            if not fresh_low and bias200 <= -10 and from_peak <= -22:
                grade = "S"
    return grade


def grade_usd_i(fx_closes: np.ndarray, i: int) -> str:
    """
    美金囤匯門檻（對齊「≤年均線可買」並分級）：
      D = 美元偏強（乖離年線 ≥ +1.5%）
      C = 靠近年線上方
      B = ≤ 年線
      A = ≤ 年線且低於 ≥1.5%＋止穩
      S = ≤ 年線且低於 ≥3%＋止穩
    """
    if i < 199:
        return "D"
    fx = float(fx_closes[i])
    ma200 = float(np.mean(fx_closes[i - 199 : i + 1]))
    bias200 = (fx - ma200) / ma200 * 100
    stab = _stabilized_row(fx_closes, i)
    if bias200 >= 1.5:
        return "D"
    if fx > ma200:
        return "C"
    if bias200 <= -3 and stab:
        return "S"
    if bias200 <= -1.5 and stab:
        return "A"
    return "B"


def simulate_asset_grade(
    *,
    mode: str,
    kind: str,
    trade_closes: np.ndarray,
    gold_usd: np.ndarray | None = None,
    fx_closes: np.ndarray | None = None,
    test_start: int = 200,
    sizing: str = "all_in",
    tranche_map: dict | None = None,
    budget: float | None = None,
) -> dict:
    """
    kind=gold：評等用 GC=F + 匯率；權益／成交用台幣／公克 (trade_closes)。
    kind=usd：評等與成交皆用 USD/TWD。

    sizing:
      all_in  — 空手才全倉買入（門檻比較用）
      tranche — 依評等分批加碼，總投入不超 budget（金額最佳化用）
    """
    n = len(trade_closes)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}

    tmap = tranche_map or GOLD_LIVE_TRANCHE
    cap = float(budget if budget is not None else (GOLD_BUDGET if kind == "gold" else INITIAL))
    buy_c, sell_c = COSTS["gold" if kind == "gold" else "usd"]

    cash = INITIAL
    units = 0.0
    invested = 0.0  # 成本累計（tranche 用）
    equity = []
    trades = 0
    buys = 0
    buy_grades = []
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    last_buy_i = -999

    for i in range(n):
        px = float(trade_closes[i])
        equity.append(cash + units * px)
        if i < test_start or i >= n - 1:
            continue

        should_sell = False
        if kind == "gold":
            g = grade_gold_i(gold_usd, fx_closes, i)
            ma50 = float(np.mean(gold_usd[i - 49 : i + 1]))
            should_sell = units > 0 and float(gold_usd[i]) > ma50
        else:
            g = grade_usd_i(trade_closes, i)
            ma200 = float(np.mean(trade_closes[i - 199 : i + 1]))
            should_sell = units > 0 and px > ma200 * 1.015

        grade_counts[g] = grade_counts.get(g, 0) + 1
        j = i + 1
        px_next = float(trade_closes[j])

        if should_sell and units > 0:
            cash += units * px_next * (1 - sell_c)
            units = 0.0
            invested = 0.0
            trades += 1

        if not meets_threshold(g, mode):
            continue

        if sizing == "all_in":
            if units == 0:
                spend = cash
                units = spend / (px_next * (1 + buy_c))
                cash = 0.0
                invested = spend
                trades += 1
                buys += 1
                buy_grades.append(g)
                last_buy_i = i
        else:
            # tranche：同評等至少隔 5 日再加；總成本 ≤ budget
            room = cap - invested
            suggest = float(tmap.get(g, 0.0) or 0.0)
            if suggest <= 0 or room < 10_000 or cash < 10_000:
                continue
            if i - last_buy_i < 5 and units > 0:
                continue
            spend = min(suggest, room, cash)
            if spend < 10_000:
                continue
            add_u = spend / (px_next * (1 + buy_c))
            units += add_u
            cash -= spend
            invested += spend
            trades += 1
            buys += 1
            buy_grades.append(g)
            last_buy_i = i

    eq = pd.Series(equity[test_start:], dtype=float)
    years = max(len(eq) / 252.0, 0.1)
    m = get_metrics(eq, trades, years, INITIAL)
    # B&H 對照同樣付一次買入成本，公平比較
    bh = trade_closes[test_start:] / trade_closes[test_start] * INITIAL / (1 + buy_c)
    m_bh = get_metrics(pd.Series(bh), 0, years, INITIAL)
    return {
        "ok": True,
        "mode": mode,
        "sizing": sizing,
        "tranche_map": {k: float(v) for k, v in (tmap or {}).items()} if sizing == "tranche" else None,
        "cagr": m["cagr"],
        "mdd": m["mdd"],
        "sharpe": m["sharpe"],
        "final": m["final"],
        "cp": m["cp"],
        "trades": m["trades"],
        "buys": buys,
        "buy_grades": dict(pd.Series(buy_grades).value_counts()) if buy_grades else {},
        "grade_days": grade_counts,
        "years": round(years, 2),
        "bh_cagr": m_bh["cagr"],
        "bh_mdd": m_bh["mdd"],
        "bh_final": m_bh["final"],
        "beat_bh": m["final"] > m_bh["final"],
    }


def optimize_gold_tranches(
    *,
    mode: str,
    bot: np.ndarray,
    gold_usd: np.ndarray,
    fx: np.ndarray,
    test_start: int,
) -> dict:
    """在冠軍門檻下，搜尋 B/A/S 分批金額組合（袖口資金=黃金預算 30 萬）。"""
    candidates = [
        ("現行8/10/12萬", {"B": 80_000, "A": 100_000, "S": 120_000, "C": 0, "D": 0}),
        ("偏保守5/8/10萬", {"B": 50_000, "A": 80_000, "S": 100_000, "C": 0, "D": 0}),
        ("B更小4/10/12萬", {"B": 40_000, "A": 100_000, "S": 120_000, "C": 0, "D": 0}),
        ("跳過B只買A+", {"B": 0, "A": 100_000, "S": 120_000, "C": 0, "D": 0}),
        ("B加碼10/10/12萬", {"B": 100_000, "A": 100_000, "S": 120_000, "C": 0, "D": 0}),
        ("均等10萬", {"B": 100_000, "A": 100_000, "S": 100_000, "C": 0, "D": 0}),
        ("積極B12/12/12", {"B": 120_000, "A": 120_000, "S": 120_000, "C": 0, "D": 0}),
        ("含C試單3/8/10/12", {"B": 80_000, "A": 100_000, "S": 120_000, "C": 30_000, "D": 0}),
    ]
    rows = []
    best = None
    # 袖口資金=預算，避免 100 萬本金裡 70 萬現金躺平扭曲 CP
    global INITIAL
    saved_initial = INITIAL
    INITIAL = GOLD_BUDGET
    try:
        for label, tmap in candidates:
            tmap = dict(tmap)
            if MODE_MIN_RANK[mode] > GRADE_RANK["B"]:
                tmap["B"] = 0
            if MODE_MIN_RANK[mode] > GRADE_RANK["C"]:
                tmap["C"] = 0
            r = simulate_asset_grade(
                mode=mode,
                kind="gold",
                trade_closes=bot,
                gold_usd=gold_usd,
                fx_closes=fx,
                test_start=test_start,
                sizing="tranche",
                tranche_map=tmap,
                budget=GOLD_BUDGET,
            )
            if not r.get("ok"):
                continue
            item = {
                "label": label,
                "tranche": {k: int(v) for k, v in tmap.items() if v},
                "cagr": r["cagr"],
                "mdd": r["mdd"],
                "final": r["final"],
                "cp": r["cp"],
                "buys": r["buys"],
                "buy_grades": r.get("buy_grades") or {},
            }
            rows.append(item)
            # 袖口內：終值優先，其次 CP（避免空倉幾乎不動「假優勝」）
            key = (item["final"], item["cp"])
            if best is None or key > (best["final"], best["cp"]):
                best = item
    finally:
        INITIAL = saved_initial
    return {"mode": mode, "sleeve_initial": GOLD_BUDGET, "candidates": rows, "best": best}


def align_on_date(df_a: pd.DataFrame, df_b: pd.DataFrame, col_b: str) -> pd.DataFrame:
    m = df_a.merge(df_b.rename(columns={"close": col_b}), on="date", how="inner")
    return m.sort_values("date").reset_index(drop=True)


def prepare_yahoo_or_daily(sym: str) -> pd.DataFrame:
    """長歷史：取 fetch_daily 與 Yahoo 10y 中較長者。"""
    rows = fetch_daily(sym) or []
    yrows = fetch_yahoo_daily(sym, "10y") or []
    if len(yrows) > len(rows):
        rows = yrows
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values("date").reset_index(drop=True)
    df["close"] = df["close"].astype(float)
    if "open" in df.columns:
        df["open"] = df["open"].astype(float)
        df["open"] = df["open"].fillna(df["close"])
    else:
        df["open"] = df["close"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "open", "close"]].dropna()


def prepare_tw(code: str) -> pd.DataFrame:
    df = download_full_history(code)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "close"):
        if c not in df.columns:
            if c.capitalize() in df.columns:
                df[c] = df[c.capitalize()]
    if "open" not in df.columns:
        df["open"] = df["close"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    if code == "00631L":
        split = "2026-03-24"
        mask = df["date"] <= split
        df.loc[mask, "close"] = df.loc[mask, "close"] / 22.0
        df.loc[mask, "open"] = df.loc[mask, "open"] / 22.0
    if code == "0050":
        # 2025-06-18 除權 1拆4；FinMind 原始價未還原（未修會出現假 -75% 崩跌）
        mask = df["date"] <= "2025-06-17"
        df.loc[mask, "close"] = df.loc[mask, "close"] / 4.0
        df.loc[mask, "open"] = df.loc[mask, "open"] / 4.0
    return df[["date", "open", "close"]].dropna()


def prepare_us(sym: str) -> pd.DataFrame:
    return prepare_yahoo_or_daily(sym)


def slice_with_warmup(df: pd.DataFrame, eval_years: float) -> tuple[pd.DataFrame, int]:
    """
    保留評測窗 + 暖機列。回傳 (切片 df, test_start index)。
    test_start 起才計入績效；之前只算均線／評等。
    """
    if df.empty:
        return df, 0
    end = pd.to_datetime(df["date"].iloc[-1])
    eval_start = end - timedelta(days=int(365 * eval_years))
    keep_from = (eval_start - timedelta(days=int(WARMUP_BARS * 1.7))).strftime("%Y-%m-%d")
    out = df[df["date"] >= keep_from].reset_index(drop=True)
    eval_s = eval_start.strftime("%Y-%m-%d")
    idxs = out.index[out["date"] >= eval_s]
    if len(idxs) == 0:
        test_start = min(WARMUP_BARS, max(len(out) - 20, 0))
    else:
        test_start = max(int(idxs[0]), 200)  # 至少 200 根均線暖機
        # 若暖機不足，從開頭夠 200 再評測
        if test_start < 200:
            test_start = 200
    return out, test_start


def slice_5y(df: pd.DataFrame) -> pd.DataFrame:
    out, _ = slice_with_warmup(df, YEARS)
    return out


def simulate_grade_strategy(
    df: pd.DataFrame,
    *,
    mode: str,
    kind: str,
    taiex_closes: np.ndarray | None = None,
    is_tw: bool = True,
    test_start: int = 200,
    cost_class: str | None = None,
) -> dict:
    """
    kind: core_tw | lev | us_growth | us_core
    cost_class: COSTS 鍵；未指定依 is_tw 推 tw_etf / us_etf
    """
    buy_c, sell_c = COSTS[cost_class or ("tw_etf" if is_tw else "us_etf")]
    closes = df["close"].astype(float).values
    opens = df["open"].astype(float).values
    n = len(closes)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}

    cash = INITIAL
    shares = 0.0
    equity = []
    trades = 0
    buys = 0
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    buy_grades = []

    for i in range(n):
        equity.append(cash + shares * closes[i])

        if i < test_start or i >= n - 1:
            continue

        if kind == "lev":
            level = macro_level_from(taiex_closes, i)
            g = grade_lev_i(closes, taiex_closes, i, level)
        elif kind == "us_growth":
            g = grade_growth_us_i(closes, i)
        else:
            if is_tw and taiex_closes is not None:
                level = macro_level_from(taiex_closes, i)
            else:
                level = 1
            g = grade_pullback_core_i(closes, i, level)

        grade_counts[g] = grade_counts.get(g, 0) + 1

        should_sell = False
        if shares > 0:
            if kind == "lev":
                taiex_ma200 = float(np.mean(taiex_closes[i - 199 : i + 1]))
                if taiex_closes[i] < taiex_ma200:
                    should_sell = True
                ma10 = float(np.mean(closes[i - 9 : i + 1]))
                if closes[i] < ma10:
                    should_sell = True
            elif kind in ("us_growth", "us_core"):
                ma50 = float(np.mean(closes[i - 49 : i + 1]))
                if closes[i] < ma50:
                    should_sell = True
            else:
                ma10 = float(np.mean(closes[i - 9 : i + 1]))
                if closes[i] < ma10:
                    should_sell = True

        j = i + 1
        px = opens[j] if opens[j] > 0 else closes[j]
        if should_sell and shares > 0:
            cash = shares * px * (1 - sell_c)
            shares = 0.0
            trades += 1

        if shares == 0 and meets_threshold(g, mode):
            shares = cash / (px * (1 + buy_c))
            cash = 0.0
            trades += 1
            buys += 1
            buy_grades.append(g)

    eq = pd.Series(equity[test_start:], dtype=float)
    days = len(eq)
    years = max(days / 252.0, 0.1)
    m = get_metrics(eq, trades, years, INITIAL)
    bh_start = closes[test_start]
    # B&H 對照同樣付一次買入成本，公平比較
    bh = closes[test_start:] / bh_start * INITIAL / (1 + buy_c)
    m_bh = get_metrics(pd.Series(bh), 0, years, INITIAL)

    return {
        "ok": True,
        "mode": mode,
        "cagr": m["cagr"],
        "mdd": m["mdd"],
        "sharpe": m["sharpe"],
        "final": m["final"],
        "cp": m["cp"],
        "trades": m["trades"],
        "buys": buys,
        "buy_grades": dict(pd.Series(buy_grades).value_counts()) if buy_grades else {},
        "grade_days": grade_counts,
        "years": round(years, 2),
        "bh_cagr": m_bh["cagr"],
        "bh_mdd": m_bh["mdd"],
        "bh_final": m_bh["final"],
        "beat_bh": m["final"] > m_bh["final"],
    }


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _run_modes_etf(code, name, kind, is_tw, df, taiex_df, modes, eval_years, cost_class=None):
    df, test_start = slice_with_warmup(df, eval_years)
    print(f"--- {code} {name}（{eval_years:g}年）：{len(df)} 列｜test_start={test_start} ---")
    if df.empty or len(df) < test_start + 20:
        print("  資料不足，略過")
        return None

    t_closes = None
    if is_tw and taiex_df is not None and not taiex_df.empty:
        taiex_s, _ = slice_with_warmup(taiex_df, eval_years)
        m = df.merge(
            taiex_s.rename(columns={"close": "taiex", "open": "taiex_o"}),
            on="date",
            how="inner",
        )
        if len(m) < test_start + 20:
            print("  與大盤對齊後資料不足")
            return None
        # recompute test_start on aligned frame
        end = pd.to_datetime(m["date"].iloc[-1])
        eval_s = (end - timedelta(days=int(365 * eval_years))).strftime("%Y-%m-%d")
        idxs = m.index[m["date"] >= eval_s]
        test_start = max(int(idxs[0]) if len(idxs) else 200, 200)
        df = m[["date", "open", "close"]].reset_index(drop=True)
        t_closes = m["taiex"].astype(float).values

    row_block = {
        "code": code,
        "name": name,
        "eval_years": eval_years,
        "asset_class": "etf",
    }
    best_mode = None
    best_final = -1
    for mode in modes:
        r = simulate_grade_strategy(
            df,
            mode=mode,
            kind=kind,
            taiex_closes=t_closes,
            is_tw=is_tw,
            test_start=test_start,
            cost_class=cost_class,
        )
        if not r.get("ok"):
            print(f"  {mode}: 失敗 {r.get('reason')}")
            continue
        print(
            f"  {mode:3s}  CAGR {r['cagr']:+6.2f}%  MDD {r['mdd']:6.1f}%  "
            f"終值 {r['final']/1e4:7.1f}萬  買入{r['buys']:3d}次  "
            f"{'勝B&H' if r['beat_bh'] else '輸B&H'}(B&H {r['bh_cagr']:+.1f}%)"
        )
        row_block[mode] = r
        if r["final"] > best_final:
            best_final = r["final"]
            best_mode = mode
    if best_mode:
        print(f"  → {eval_years:g}年終值最高：【{best_mode}】\n")
        row_block["winner"] = best_mode
    return row_block


def _run_modes_gold_usd(modes):
    blocks = []
    df_gold = prepare_yahoo_or_daily("GC=F")
    df_fx = prepare_yahoo_or_daily("USDTWD=X")
    if df_gold.empty or df_fx.empty:
        print("--- 黃金／美金：資料不足 ---")
        return blocks

    aligned = align_on_date(
        df_gold.rename(columns={"close": "gold", "open": "gold_o"}),
        df_fx[["date", "close"]],
        "fx",
    )
    aligned, test_start = slice_with_warmup(aligned, 5)
    print(f"--- GC=F 黃金台幣換算（5年｜全倉門檻比較）：{len(aligned)} 列｜test_start={test_start} ---")
    if len(aligned) < test_start + 20:
        print("  資料不足")
    else:
        gold_usd = aligned["gold"].astype(float).values
        fx = aligned["fx"].astype(float).values
        bot = gold_usd * fx / OZ_TO_GRAM
        row = {"code": "GOLD", "name": "黃金存摺(台幣/g)", "eval_years": 5, "asset_class": "gold"}
        best_mode, best_final = None, -1
        for mode in modes:
            r = simulate_asset_grade(
                mode=mode,
                kind="gold",
                trade_closes=bot,
                gold_usd=gold_usd,
                fx_closes=fx,
                test_start=test_start,
                sizing="all_in",
            )
            if not r.get("ok"):
                print(f"  {mode}: 失敗 {r.get('reason')}")
                continue
            print(
                f"  {mode:3s}  CAGR {r['cagr']:+6.2f}%  MDD {r['mdd']:6.1f}%  "
                f"終值 {r['final']/1e4:7.1f}萬  買入{r['buys']:3d}次  "
                f"{'勝B&H' if r['beat_bh'] else '輸B&H'}(B&H {r['bh_cagr']:+.1f}%)"
            )
            gd = r.get("grade_days") or {}
            total_g = sum(gd.values()) or 1
            r["b_day_pct"] = round(100.0 * gd.get("B", 0) / total_g, 1)
            row[mode] = r
            if r["final"] > best_final:
                best_final = r["final"]
                best_mode = mode
        if best_mode:
            print(f"  → 5年終值最高：【{best_mode}】\n")
            row["winner"] = best_mode
            print(f"--- 黃金分批金額最佳化（門檻={best_mode}，預算{GOLD_BUDGET/1e4:.0f}萬）---")
            opt = optimize_gold_tranches(
                mode=best_mode,
                bot=bot,
                gold_usd=gold_usd,
                fx=fx,
                test_start=test_start,
            )
            row["size_opt"] = opt
            if opt.get("best"):
                b = opt["best"]
                print(
                    f"  → 金額冠軍【{b['label']}】CP {b['cp']:+.2f}  "
                    f"CAGR {b['cagr']:+.1f}%  MDD {b['mdd']:.1f}%  "
                    f"終值 {b['final']/1e4:.1f}萬  買{b['buys']}次  "
                    f"金額 {b['tranche']}\n"
                )
        blocks.append(row)

    fx_df, fx_start = slice_with_warmup(df_fx, 5)
    print(f"--- USDTWD 美金（5年）：{len(fx_df)} 列｜test_start={fx_start} ---")
    if len(fx_df) < fx_start + 20:
        print("  資料不足")
    else:
        fx_c = fx_df["close"].astype(float).values
        row = {"code": "USDTWD", "name": "美金外匯", "eval_years": 5, "asset_class": "usd"}
        best_mode, best_final = None, -1
        for mode in modes:
            r = simulate_asset_grade(
                mode=mode,
                kind="usd",
                trade_closes=fx_c,
                test_start=fx_start,
                sizing="all_in",
            )
            if not r.get("ok"):
                print(f"  {mode}: 失敗 {r.get('reason')}")
                continue
            print(
                f"  {mode:3s}  CAGR {r['cagr']:+6.2f}%  MDD {r['mdd']:6.1f}%  "
                f"終值 {r['final']/1e4:7.1f}萬  買入{r['buys']:3d}次  "
                f"{'勝B&H' if r['beat_bh'] else '輸B&H'}(B&H {r['bh_cagr']:+.1f}%)"
            )
            row[mode] = r
            if r["final"] > best_final:
                best_final = r["final"]
                best_mode = mode
        if best_mode:
            print(f"  → 5年終值最高：【{best_mode}】\n")
            row["winner"] = best_mode
        blocks.append(row)
    return blocks


def main():
    global COST_SCENARIO, COSTS
    if "--costs" in sys.argv:
        COST_SCENARIO = sys.argv[sys.argv.index("--costs") + 1]
        COSTS = COST_SCENARIOS[COST_SCENARIO]

    print("=== 評等門檻回測（五級距 S/A+/B+/C+/D+｜不含 USDT）===")
    print(f"成本情境：{COST_SCENARIO}｜{COSTS}")
    print(f"起始資金 {INITIAL:,.0f}｜門檻：該級以上才買；黃金另最佳化分批金額\n")

    modes = list(MODES)
    all_rows = []

    all_rows.extend(_run_modes_gold_usd(modes))

    btc_block = _run_modes_etf(
        "BTC-USD",
        "Bitcoin",
        "us_core",
        False,
        prepare_yahoo_or_daily("BTC-USD"),
        None,
        modes,
        2,
        cost_class="crypto",
    )
    if btc_block:
        btc_block["asset_class"] = "crypto"
        all_rows.append(btc_block)

    df_taiex = prepare_tw("TAIEX")
    products = [
        ("0050", "台股底倉", "core_tw", True, prepare_tw("0050")),
        ("00631L", "台股正2", "lev", True, prepare_tw("00631L")),
        ("VOO", "美股S&P", "us_core", False, prepare_us("VOO")),
        ("VXUS", "美股非美", "us_core", False, prepare_us("VXUS")),
        ("QQQ", "美股成長", "us_growth", False, prepare_us("QQQ")),
    ]
    for code, name, kind, is_tw, df in products:
        block = _run_modes_etf(code, name, kind, is_tw, df, df_taiex, modes, 5)
        if block:
            all_rows.append(block)

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    os.makedirs(out_dir, exist_ok=True)
    suffix = "" if COST_SCENARIO == "real" else f"_{COST_SCENARIO}"
    out_md = os.path.join(out_dir, f"grade_threshold_backtest{suffix}.md")
    out_json = os.path.join(out_dir, f"grade_threshold_backtest{suffix}.json")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)

    lines = []
    lines.append("# 評等門檻回測（五級距｜不含 USDT）\n\n")
    lines.append(f"產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "評測窗：黃金／美金／ETF **5 年**；BTC **2 年**（均線另留暖機）。  \n"
    )
    lines.append(
        f"成本情境：**{COST_SCENARIO}**"
        "（real＝含實際價差：黃金存摺 0.5%/邊、美金 0.15%/邊、台股ETF 手續費+0.1%稅+滑價、"
        "IB 0.07%/邊、幣 0.15%/邊；B&H 對照亦計一次買入成本）  \n"
    )
    lines.append(
        "門檻：S／A+／B+／C+／D+（該級以上才買）；訊號日收盤、隔日開盤。  \n"
    )
    lines.append(
        "出場：黃金回上 50MA；美金乖離年線 >+1.5%；BTC／美股破 50MA；"
        "0050 破 10MA；正2 大盤破年線或破 10MA。  \n"
    )
    lines.append(
        "門檻比較採**全倉進出**；黃金另在冠軍門檻下做**分批金額** CP 最佳化（預算 30 萬）。  \n"
    )
    lines.append("對照：同期間買入持有（B&H）。  \n\n")

    hdr = "| 商品 | 年 | " + " | ".join(modes) + " | 終值冠軍 | 實戰建議 |\n"
    lines.append(hdr)
    lines.append("| :--- | ---: | " + " | ".join(["---:"] * len(modes)) + " | :---: | :--- |\n")

    json_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "modes": modes,
        "note": "5 thresholds; gold size opt under winner; gold/usd/etf=5y; btc=2y",
        "products": [],
        "action_rules": [],
    }

    for block in all_rows:
        code, name = block["code"], block["name"]
        ey = block.get("eval_years", 5)
        cells = []
        for mode in modes:
            r = block.get(mode) or {}
            if r.get("ok"):
                cells.append(f"{r['cagr']:+.1f}%")
            else:
                cells.append("—")
        winner = block.get("winner", "—")
        wr = block.get(winner) or {}
        # 實戰建議：冠軍門檻以上才「推薦買」
        if winner == "S":
            tip = "僅 S 才買"
        elif winner == "A+":
            tip = "A/S 才買（B 不強制）"
        elif winner == "B+":
            tip = "B 以上可買（允許）"
        elif winner == "C+":
            tip = "C 以上可試；實務優先等 B"
        elif winner == "D+":
            tip = "幾乎天天買（過寬，勿跟）"
        else:
            tip = "—"
        # 黃金：若 C+ 僅小勝 B+，標註雙門檻
        if code == "GOLD" and winner == "C+":
            bplus = block.get("B+") or {}
            cplus = block.get("C+") or {}
            if bplus.get("ok") and cplus.get("ok"):
                tip = (
                    f"冠軍C+（終值{cplus['final']/1e4:.0f}萬）≈B+（{bplus['final']/1e4:.0f}萬）；"
                    "今日B→允許買"
                )
        if code == "GOLD" and block.get("size_opt", {}).get("best"):
            tr = block["size_opt"]["best"]["tranche"]
            tip += "｜金額 " + "/".join(f"{k}{int(v)//10000}萬" for k, v in tr.items() if v)
        lines.append(
            f"| `{code}` {name} | {ey:g} | "
            + " | ".join(cells)
            + f" | **{winner}** | {tip} |\n"
        )

        modes_out = {}
        for m in modes:
            if not block.get(m):
                continue
            r = dict(block[m])
            r.pop("grade_days", None)
            if isinstance(r.get("buy_grades"), dict):
                r["buy_grades"] = {str(k): int(v) for k, v in r["buy_grades"].items()}
            modes_out[m] = _json_safe(r)

        rec = {
            "code": code,
            "name": name,
            "eval_years": ey,
            "asset_class": block.get("asset_class"),
            "winner": winner,
            "recommend_min_grade": winner.replace("+", "") if winner.endswith("+") else winner,
            "recommend_rule": tip,
            "modes": modes_out,
        }
        if block.get("size_opt"):
            rec["size_opt"] = _json_safe(block["size_opt"])
        json_payload["products"].append(rec)
        json_payload["action_rules"].append(
            {
                "code": code,
                "min_mode": winner,
                "buy_when": tip,
                "size": (block.get("size_opt") or {}).get("best", {}).get("tranche")
                if code == "GOLD"
                else "全倉比較用／實戰仍分批",
            }
        )

    # 黃金金額表
    gold = next((b for b in all_rows if b.get("code") == "GOLD"), None)
    if gold and gold.get("size_opt"):
        lines.append("\n## 黃金分批金額最佳化（在冠軍門檻下）\n\n")
        lines.append(
            f"冠軍門檻：**{gold.get('winner')}**｜預算上限 **{GOLD_BUDGET/1e4:.0f} 萬**｜"
            "選優指標：CP（報酬 − 回撤懲罰 − 交易摩擦）。  \n\n"
        )
        lines.append("| 方案 | B | A | S | CAGR | MDD | 終值 | CP | 買次 |\n")
        lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for c in gold["size_opt"].get("candidates") or []:
            tr = c.get("tranche") or {}
            mark = " ←" if gold["size_opt"].get("best", {}).get("label") == c["label"] else ""
            lines.append(
                f"| {c['label']}{mark} | {int(tr.get('B', 0))//10000 or '—'} | "
                f"{int(tr.get('A', 0))//10000 or '—'} | {int(tr.get('S', 0))//10000 or '—'} | "
                f"{c['cagr']:+.1f}% | {c['mdd']:.1f}% | {c['final']/1e4:.1f}萬 | "
                f"{c['cp']:+.2f} | {c['buys']} |\n"
            )
        best = gold["size_opt"].get("best") or {}
        b_amt = int((best.get("tranche") or {}).get("B", 0) or 0)
        c_amt = int((best.get("tranche") or {}).get("C", 0) or 0)
        lines.append(
            f"\n**結論**：五級距下黃金全倉冠軍是 **{gold.get('winner')}**；"
            f"與 **B+** 終值接近。今日若評等 **B** → **允許買進**（非必須追價）。  \n"
            f"建議本次金額約 **"
            f"{(b_amt if b_amt else 80_000):,}** 元"
            f"（方案：{best.get('label', '現行')}）"
        )
        if c_amt:
            lines.append(f"；若僅 **C** 最多試 **{c_amt:,}** 元")
        lines.append("；總預算 30 萬內分批，勿一次打滿。  \n")
        lines.append(
            "金額最佳化以**黃金袖口 30 萬**為本金計算（避免現金躺平扭曲）。  \n"
        )

    lines.append("\n## 解讀建議\n\n")
    lines.append(
        "- **終值冠軍＝該商品實戰「最低可買級距」**：例如冠軍 B+ → 評等 ≥B 才建議買。  \n"
        "- **黃金常卡 B**：若冠軍是 B+，這幾天 B **理論上該買**（允許、非必須追高）。  \n"
        "- **金額可最佳化**：見上表；現行 8/10/12 萬未必最優。  \n"
        "- **S 最嚴／D+ 最寬**：過寬易摩擦、過嚴易空倉；同時看 MDD 與買次。  \n"
        "- **多數商品 B&H 仍可能贏擇時**：評等適合「分批進場時機」，非保證打敗長抱。  \n"
        "- **USDT** 刻意略過。  \n"
    )

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(_json_safe(json_payload), f, ensure_ascii=False, indent=2)

    print(f"\n報告：{out_md}")
    print(f"JSON：{out_json}")


if __name__ == "__main__":
    main()
