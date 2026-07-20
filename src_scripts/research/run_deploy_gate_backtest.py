# -*- coding: utf-8 -*-
"""
現金部署閘門回測：全域 Level（現行）vs 各袖自己的 Level vs 無閘門。

問題：deployable_cash 上限目前由 TAIEX 單一指標決定（台股跌破月線→全部袖
只能用 15% 現金），連美股袖也被綁住。各袖看各自市場是否更好？

設定：起始全現金，每月依目標配置把現金投入四個袖：
  台股核心(TWII+3.5%股息) 39%｜正2(合成2x) 13%｜美股(SPY×匯率) 19%｜黃金(TWD) 28%
  （由 allocation_targets 35/12/17/25 正規化；現金孳息 1%/年）
Level 公式沿用 scan_watch_grades.macro_level：<20MA=3｜乖離≤1.5%=2｜否則=1
比率沿用 position_playbook：Level1/2/3 → 40%/30%/15%，地板 50%。

方案：
  A 無閘門（現金立即依目標配置投滿）
  B 全域 TAIEX Level（現行）
  C 各袖自己的 Level（台股袖看 TAIEX、美股袖看 SPY、黃金袖不受限）
  D 全域但放寬（60/50/30%）
多起點 cohort（每 6 個月一個、各持有 5 年）取中位數，避免單一路徑運氣。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

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
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


WORKSPACE = _find_workspace()
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts", "research"))

from run_voltarget_backtest import build_dataset  # noqa: E402
from run_trend_exit_backtest import fetch_yahoo_adj  # noqa: E402

CACHE = os.path.join(WORKSPACE, "market_crawled_cache")
INIT = 1_000_000.0
DIV_TW = 0.035 / 252.0
CASH_YIELD = 0.01 / 252.0
FLOOR_PCT = 0.5
STEP_M = 21          # 每 21 交易日檢一次
HORIZON = 252 * 5    # 每個 cohort 持有 5 年
COHORT_STEP = 126    # 每半年一個 cohort

WEIGHTS = {"tw": 0.39, "lev": 0.13, "us": 0.19, "gold": 0.28}
COSTS = {"tw": 0.001925, "lev": 0.001925, "us": 0.0007, "gold": 0.005}

RATIOS_STD = {1: 0.40, 2: 0.30, 3: 0.15}
RATIOS_WIDE = {1: 0.60, 2: 0.50, 3: 0.30}


def level_of(px: float, ma20: float) -> int:
    if not ma20 or math.isnan(ma20):
        return 2
    if px < ma20:
        return 3
    return 2 if (px - ma20) / ma20 * 100 <= 1.5 else 1


def load_data() -> pd.DataFrame:
    lev_df, _ = build_dataset()
    base = lev_df[["date", "twii_close", "lev_close"]].rename(
        columns={"twii_close": "tw_px", "lev_close": "lev_px"})
    spy = fetch_yahoo_adj("SPY").rename(columns={"close": "spy_usd"})
    fx = pd.read_csv(os.path.join(CACHE, "USDTWD_full_history.csv")).rename(
        columns={"close": "fx"})
    fx = fx[(fx["fx"] > 20) & (fx["fx"] < 45)]
    gold = pd.read_csv(os.path.join(CACHE, "GOLD_USD_full_history.csv")).rename(
        columns={"close": "gold_usd"})
    df = base.merge(spy, on="date", how="left").merge(fx, on="date", how="left") \
             .merge(gold, on="date", how="left")
    for c in ("spy_usd", "fx", "gold_usd"):
        df[c] = df[c].ffill()
    df = df.dropna(subset=["tw_px", "lev_px", "spy_usd", "fx", "gold_usd"]).reset_index(drop=True)
    df["us_px"] = df["spy_usd"] * df["fx"]
    df["gold_px"] = df["gold_usd"] * df["fx"] / 31.1034768
    df["tw_ma20"] = df["tw_px"].rolling(20).mean()
    df["us_ma20"] = df["us_px"].rolling(20).mean()
    return df.dropna(subset=["tw_ma20", "us_ma20"]).reset_index(drop=True)


def simulate(df: pd.DataFrame, i0: int, mode: str, ratios: dict) -> dict:
    px = {k: df[f"{k}_px"].to_numpy(float) for k in WEIGHTS}
    tw_ma20 = df["tw_ma20"].to_numpy(float)
    us_ma20 = df["us_ma20"].to_numpy(float)
    units = {k: 0.0 for k in WEIGHTS}
    cash = INIT
    eq = []
    i1 = min(i0 + HORIZON, len(df) - 1)

    for i in range(i0, i1 + 1):
        if i > i0:
            cash *= 1.0 + CASH_YIELD
            units["tw"] *= 1.0 + DIV_TW
        nav = cash + sum(units[k] * px[k][i] for k in WEIGHTS)
        eq.append(nav)
        if i >= i1 or (i - i0) % STEP_M != 0:
            continue

        lv_tw = level_of(px["tw"][i], tw_ma20[i])
        lv_us = level_of(px["us"][i], us_ma20[i])
        gaps = {k: max(WEIGHTS[k] * nav - units[k] * px[k][i], 0.0) for k in WEIGHTS}
        total_gap = sum(gaps.values())
        if total_gap <= 0 or cash <= nav * 0.001:
            continue

        per = None
        if mode == "none":
            budget = cash
        elif mode == "global":
            budget = min(cash, cash * ratios[lv_tw])
        elif mode == "per_sleeve":
            # 各袖各自的 level 決定各自可動用比例；黃金袖(避險)不受景氣閘門限制
            lv_map = {"tw": lv_tw, "lev": lv_tw, "us": lv_us, "gold": 1}
            per = {}
            for k in WEIGHTS:
                rk = 1.0 if k == "gold" else ratios[lv_map[k]]
                per[k] = cash * (gaps[k] / total_gap) * rk
            budget = sum(per.values())
        else:
            raise ValueError(mode)

        if budget <= 0:
            continue

        for k in WEIGHTS:
            if per is not None:
                spend = min(per[k], gaps[k], cash)
            else:
                spend = min(budget * gaps[k] / total_gap, gaps[k], cash)
            if spend < nav * 0.002:
                continue
            units[k] += spend / (px[k][i] * (1 + COSTS[k]))
            cash -= spend

    s = pd.Series(eq)
    yrs = max(len(s) / 252.0, 0.1)
    return {
        "final": float(s.iloc[-1]),
        "cagr": ((float(s.iloc[-1]) / INIT) ** (1 / yrs) - 1) * 100,
        "mdd": float(((s - s.cummax()) / s.cummax() * 100).min()),
    }


def main():
    print("=== 現金部署閘門：全域 vs 各袖 vs 無閘門 ===")
    df = load_data()
    print(f"資料 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}（{len(df)} 日）")

    modes = [
        ("A 無閘門（立即投滿）", "none", RATIOS_STD),
        ("B 全域TAIEX Level（現行40/30/15）", "global", RATIOS_STD),
        ("C 各袖自己Level（台股/美股分開）", "per_sleeve", RATIOS_STD),
        ("D 全域但放寬（60/50/30）", "global", RATIOS_WIDE),
    ]
    cohorts = list(range(0, len(df) - HORIZON, COHORT_STEP))
    print(f"cohorts={len(cohorts)}（每半年一個、各持有5年）\n")

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "range": [df["date"].iloc[0], df["date"].iloc[-1]],
           "cohorts": len(cohorts), "results": {}}
    rows = []
    for label, mode, ratios in modes:
        res = [simulate(df, i0, mode, ratios) for i0 in cohorts]
        cagrs = np.array([r["cagr"] for r in res])
        mdds = np.array([r["mdd"] for r in res])
        cp = np.median(cagrs) - 0.25 * abs(np.median(mdds))
        rows.append((label, np.median(cagrs), np.percentile(cagrs, 10),
                     np.median(mdds), cp))
        out["results"][label] = {
            "cagr_median": round(float(np.median(cagrs)), 3),
            "cagr_p10": round(float(np.percentile(cagrs, 10)), 3),
            "mdd_median": round(float(np.median(mdds)), 3),
            "cp": round(float(cp), 3),
        }
        print(f"  {label}: CAGR中位 {np.median(cagrs):+.2f}% "
              f"(10分位 {np.percentile(cagrs,10):+.2f}%)  MDD中位 {np.median(mdds):.1f}%  CP {cp:.2f}")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    md = os.path.join(out_dir, "deploy_gate_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 現金部署閘門回測（全域 Level vs 各袖 Level）\n\n")
        f.write(f"產生：{out['generated_at']}｜資料 `{out['range'][0]}` ~ `{out['range'][1]}`"
                f"｜cohorts {len(cohorts)}（每半年一個、各持有5年）  \n")
        f.write("起始全現金，每21日依目標配置投入；台股核心39%/正2 13%/美股19%/黃金28%"
                "（由 allocation_targets 正規化）；現金孳息1%/年，含各袖真實成本。  \n")
        f.write("Level 公式同 scan_watch_grades：<20MA=3｜乖離≤1.5%=2｜否則=1。  \n\n")
        f.write("| 方案 | CAGR中位 | CAGR 10分位 | MDD中位 | CP |\n")
        f.write("| :--- | ---: | ---: | ---: | ---: |\n")
        for label, cm, c10, mm, cp in rows:
            f.write(f"| {label} | {cm:+.2f}% | {c10:+.2f}% | {mm:.1f}% | {cp:.2f} |\n")
        f.write("\n## 判讀\n\n")
        f.write("- A vs B/C/D：閘門本身有沒有價值（拖慢部署的代價 vs 避開壞時機的好處）。  \n")
        f.write("- B vs C：全域用台股指標綁住美股袖，是否比各袖分開差。  \n")
        f.write("- B vs D：若閘門有價值，現行 15% 是否過緊。  \n")
        f.write("- 限制：未含各袖趨勢出場（本測只隔離「部署節奏」單一變數）；"
                "黃金袖在 C 方案不受限。  \n")
    with open(os.path.join(out_dir, "deploy_gate_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
