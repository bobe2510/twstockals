# -*- coding: utf-8 -*-
"""
回測「現行核准宇宙」配置 vs 對照策略，用同一套 CP 公式選優。
CP = CAGR - 0.25*|MDD| - 1.5*WorkdayOpsPerYear
靜態組合預設每年再平衡 1 次（EOD 權重 0.2 → 年化 Ops≈0.2）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.append(WORKSPACE)

from src_scripts.run_etf_backtest import (  # noqa: E402
    LAMBDA_MDD,
    LAMBDA_OPS,
    EOD_OPS_WEIGHT,
    download_full_history,
    get_metrics,
)
from src_scripts.market_data import fetch_daily  # noqa: E402


def yahoo_rows_to_df(sym_key: str, col: str) -> pd.DataFrame:
    rows = fetch_daily(sym_key)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{"date": r["date"], col: r["close"]} for r in rows])


def bh_equity(closes: pd.Series, initial: float) -> pd.Series:
    return closes / float(closes.iloc[0]) * initial


def portfolio_rebalance(
    price_df: pd.DataFrame,
    weights: dict,
    initial: float = 1_000_000.0,
    rebalance_every_n_days: int = 252,
) -> tuple[pd.Series, int]:
    """Buy&hold with periodic rebalance to target weights. columns must match weights keys."""
    cols = list(weights.keys())
    w = np.array([weights[c] for c in cols], dtype=float)
    w = w / w.sum()
    px = price_df[cols].astype(float).copy()
    # drop rows with any na
    px = px.dropna()
    if px.empty:
        return pd.Series(dtype=float), 0

    n = len(px)
    units = None
    equity = []
    trades = 0
    for i in range(n):
        row = px.iloc[i].values
        if i == 0 or (rebalance_every_n_days and i % rebalance_every_n_days == 0):
            if i == 0:
                nav = initial
            else:
                nav = float(np.dot(units, row))
            units = (nav * w) / row
            trades += len(cols)  # one EOD touch per sleeve
        equity.append(float(np.dot(units, row)))
    return pd.Series(equity, index=px.index), trades


def prepare_tw_frame() -> pd.DataFrame:
    df_taiex = download_full_history("TAIEX")
    df_lev = download_full_history("00631L")
    df_0050 = download_full_history("0050")
    if df_taiex.empty or df_lev.empty:
        raise RuntimeError("TW history missing")

    df_taiex = df_taiex.sort_values("date").reset_index(drop=True)
    df_lev = df_lev.sort_values("date").reset_index(drop=True)

    split_date = "2026-03-24"
    mask = df_lev["date"] <= split_date
    df_lev.loc[mask, "open"] = df_lev.loc[mask, "open"] / 22.0
    df_lev.loc[mask, "close"] = df_lev.loc[mask, "close"] / 22.0

    df = pd.merge(
        df_taiex[["date", "close"]].rename(columns={"close": "taiex"}),
        df_lev[["date", "close"]].rename(columns={"close": "lev"}),
        on="date",
    )

    # 0050 quality guard (same idea as run_etf_backtest)
    use_proxy = True
    if not df_0050.empty:
        df_0050 = df_0050.sort_values("date")
        tmp = pd.merge(
            df_taiex[["date", "close"]].rename(columns={"close": "t"}),
            df_0050[["date", "close"]].rename(columns={"close": "c"}),
            on="date",
        )
        if len(tmp) > 200:
            mdd_0050 = float(((tmp["c"] / tmp["c"].cummax()) - 1).min() * 100)
            mdd_t = float(((tmp["t"] / tmp["t"].cummax()) - 1).min() * 100)
            use_proxy = mdd_0050 < -55 and mdd_0050 < (mdd_t - 20)
        if not use_proxy:
            df = pd.merge(
                df,
                df_0050[["date", "close"]].rename(columns={"close": "tw50"}),
                on="date",
            )
    if use_proxy or "tw50" not in df.columns:
        df["tw50"] = df["taiex"]
        print("0050 使用 TAIEX 代理")
    return df


def main():
    print("=== Universe CP Backtest ===")
    tw = prepare_tw_frame()

    print("下載行情: VOO / VXUS / QQQ / GC=F / USDTWD (Stooq→Yahoo)...")
    yahoo = {}
    for sym, key in [
        ("VOO", "voo"),
        ("VXUS", "vxus"),
        ("QQQ", "qqq"),
        ("GC=F", "gold"),
        ("USDTWD=X", "usdtwd"),
    ]:
        rows = fetch_daily(sym)
        if len(rows) < 500:
            print(f"  FAIL {sym} rows={len(rows)}")
            continue
        d = pd.DataFrame([{"date": r["date"], key: r["close"]} for r in rows])
        yahoo[key] = d
        print(
            f"  OK {sym}: {len(d)} rows ({d['date'].iloc[0]} ~ {d['date'].iloc[-1]}) "
            f"via {rows[-1].get('source')}"
        )

    need = ["voo", "vxus", "qqq", "gold", "usdtwd"]
    if any(k not in yahoo for k in need):
        raise RuntimeError("Yahoo data incomplete")

    # Start from TW calendar; left-join US/FX and forward-fill weekends/holidays gaps
    df = tw.sort_values("date").reset_index(drop=True)
    for k in need:
        df = pd.merge(df, yahoo[k][["date", k]], on="date", how="left")
    df = df.sort_values("date")
    for k in need:
        df[k] = df[k].ffill()
    df = df.dropna().reset_index(drop=True)

    # Price all sleeves in TWD terms (US assets * USD/TWD; gold oz -> rough TWD via USD)
    df["voo_twd"] = df["voo"] * df["usdtwd"]
    df["vxus_twd"] = df["vxus"] * df["usdtwd"]
    df["qqq_twd"] = df["qqq"] * df["usdtwd"]
    df["gold_twd"] = df["gold"] * df["usdtwd"]  # proxy for gold passbook direction
    df["cash"] = 1.0  # flat cash in TWD

    # Warmup drop for MA strategies on TW only subset not needed for static mixes
    df_test = df.dropna().reset_index(drop=True)
    years = len(df_test) / 252.0
    print(f"對齊後區間: {df_test['date'].iloc[0]} ~ {df_test['date'].iloc[-1]} ({years:.2f}y)")

    INITIAL = 1_000_000.0
    strategies = []

    def add_bh(name, col, note, trades=0):
        eq = bh_equity(df_test[col], INITIAL)
        strategies.append(
            {"name": name, "m": get_metrics(eq, trades, years, INITIAL), "note": note}
        )

    add_bh("0050/大盤 買入持有", "tw50", "台股核心基準")
    add_bh("00631L 買入持有", "lev", "舊CP冠軍：高報酬高MDD")
    add_bh("VOO 買入持有(TWD)", "voo_twd", "純美股核心")
    add_bh("VXUS 買入持有(TWD)", "vxus_twd", "純非美")
    add_bh("QQQ 買入持有(TWD)", "qqq_twd", "純成長袖")
    add_bh("黃金 買入持有(TWD代理)", "gold_twd", "避險袖代理")

    mixes = [
        (
            "現行核准組合（靜態年再平衡）",
            {
                "tw50": 0.35,
                "lev": 0.12,
                "gold_twd": 0.15,
                "voo_twd": 0.12,
                "vxus_twd": 0.05,
                "qqq_twd": 0.08,
                "cash": 0.13,
            },
            "對應 approved_universe 目標比重近似",
        ),
        (
            "現行但無成長袖（無正2/QQQ）",
            {
                "tw50": 0.40,
                "gold_twd": 0.15,
                "voo_twd": 0.18,
                "vxus_twd": 0.08,
                "cash": 0.19,
            },
            "更中低風險對照",
        ),
        (
            "核心+正2（無美股）",
            {"tw50": 0.50, "lev": 0.25, "gold_twd": 0.15, "cash": 0.10},
            "台股為主對照",
        ),
        (
            "VOO:VXUS=7:3",
            {"voo_twd": 0.70, "vxus_twd": 0.30},
            "美股國際對",
        ),
        (
            "VOO70 + QQQ30",
            {"voo_twd": 0.70, "qqq_twd": 0.30},
            "美股核心+成長",
        ),
        (
            "恐慌友好：半現金半0050",
            {"tw50": 0.50, "cash": 0.50},
            "留彈對照（報酬會較低）",
        ),
    ]

    for name, weights, note in mixes:
        eq, trades = portfolio_rebalance(df_test, weights, INITIAL, 252)
        # reindex equity to same length metrics — eq already full
        strategies.append(
            {
                "name": name,
                "m": get_metrics(eq.reset_index(drop=True), trades, years, INITIAL),
                "note": note,
            }
        )

    ranked = sorted(strategies, key=lambda x: x["m"]["cp"], reverse=True)
    best = ranked[0]

    print("\n=== CP Ranking ===")
    for i, s in enumerate(ranked, 1):
        m = s["m"]
        print(
            f"{i}. {s['name']}: CP {m['cp']:.2f} | CAGR {m['cagr']:.2f}% | "
            f"MDD {m['mdd']:.2f}% | Ops/yr {m['workday_ops_per_year']:.2f}"
        )
    print(f"BEST => {best['name']}")

    out_dir = os.path.join(WORKSPACE, "reports", "latest")
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "backtest_start": str(df_test["date"].iloc[0]),
        "backtest_end": str(df_test["date"].iloc[-1]),
        "total_years": round(years, 2),
        "lambda_mdd": LAMBDA_MDD,
        "lambda_ops": LAMBDA_OPS,
        "eod_ops_weight": EOD_OPS_WEIGHT,
        "best_strategy": best["name"],
        "best_cp": round(best["m"]["cp"], 2),
        "disclaimer": (
            "黃金用 GC=F×匯率代理台銀存摺；0050可能為TAIEX代理；"
            "未含加密；靜態再平衡不等於實盤擇時。CP最高≠最適合修復期。"
        ),
        "ranking": [
            {
                "rank": i,
                "name": s["name"],
                "cp": round(s["m"]["cp"], 2),
                "cagr": round(s["m"]["cagr"], 2),
                "mdd": round(s["m"]["mdd"], 2),
                "sharpe": round(s["m"]["sharpe"], 2),
                "trades": s["m"]["trades"],
                "workday_ops_per_year": round(s["m"]["workday_ops_per_year"], 2),
                "final": round(s["m"]["final"], 0),
                "note": s["note"],
            }
            for i, s in enumerate(ranked, 1)
        ],
    }
    json_path = os.path.join(out_dir, "universe_cp_best.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md_path = os.path.join(out_dir, "universe_cp_ranking.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 現行核准宇宙 vs 對照策略（CP 回測）\n\n")
        f.write(f"產生時間：{payload['generated_at']}  \n")
        f.write(
            f"區間：`{payload['backtest_start']}` ~ `{payload['backtest_end']}` "
            f"（約 {payload['total_years']} 年）  \n\n"
        )
        f.write(f"> **CP 最高 = {best['name']}（{best['m']['cp']:.2f}）**  \n")
        f.write(f"> {payload['disclaimer']}  \n\n")
        f.write("| 排名 | 策略 | CP | CAGR | MDD | Sharpe | 年化Ops | 備註 |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for row in payload["ranking"]:
            f.write(
                f"| {row['rank']} | {row['name']} | **{row['cp']:.2f}** | {row['cagr']:.2f}% | "
                f"{row['mdd']:.2f}% | {row['sharpe']:.2f} | {row['workday_ops_per_year']:.2f} | "
                f"{row['note']} |\n"
            )
        f.write("\n### 怎麼解讀\n")
        f.write("- **CP 冠軍常是高槓桿長抱**，MDD 很傷，修復期不適合當「唯一答案」。  \n")
        f.write("- **現行核准組合**追求的是可執行＋中低風險核心＋有限度成長袖，不一定 CP 第一。  \n")
        f.write("- 若現行組合 CP 明顯低於「無成長袖」，代表正2/QQQ 的回撤懲罰吃掉不少分數。  \n")

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
