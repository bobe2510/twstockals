# -*- coding: utf-8 -*-
"""
風險-報酬取捨曲線（給使用者校準「可承受回撤」）。

回答：不同回撤底線各能換到多少報酬？20% vs 30% vs 40% 回撤，報酬差多少？
方法：一組從保守到積極的配置，各跑跨危機5年窗（同 allocation_regime_windows），
      report 每個配置的『最差窗 MDD』(風險) 與『中位 CAGR』(報酬) 與 Sharpe。
      按最差窗 MDD 排序＝效率前緣，使用者據此挑風險點。

額外測『加債券(TLT)』是否改善保守端前緣（長期全天候思路：通縮衰退時長債避險）。
各袖採用規則、含成本；債券以買入持有（全天候假設，含2022升息重挫）。
crypto 固定小衛星另計於各配置。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts", "research"))

from run_allocation_robustness_backtest import build_sleeve_returns, metrics_from_returns  # noqa: E402
from run_trend_exit_backtest import fetch_yahoo_adj  # noqa: E402

CACHE = os.path.join(WORKSPACE, "market_crawled_cache")
HORIZON = 252 * 5
COHORT_STEP = 63
CARRY_USD = 0.015 / 252.0

WINDOWS = [
    ("W1 04-08 GFC", "2004-01-01", "2008-12-31"),
    ("W2 09-13", "2009-01-01", "2013-12-31"),
    ("W3 14-18 金熊", "2014-01-01", "2018-12-31"),
    ("W4 19-23 COVID/升息", "2019-01-01", "2023-12-31"),
    ("W5 24-26", "2024-01-01", "2099-12-31"),
]

# 配置光譜（含 bond、btc 欄；總和=100）。從保守→積極。
ALLOCS = {
    "① 極保守":   {"tw": 10, "lev": 0, "us": 15, "gold": 20, "fx": 18, "bond": 37, "btc": 0},
    "② 保守+債":  {"tw": 18, "lev": 2, "us": 22, "gold": 18, "fx": 12, "bond": 28, "btc": 0},
    "③ 穩健+債":  {"tw": 24, "lev": 5, "us": 26, "gold": 16, "fx": 10, "bond": 16, "btc": 3},
    "④ 現行(無債)": {"tw": 29, "lev": 8, "us": 33, "gold": 16, "fx": 11, "bond": 0, "btc": 3},
    "⑤ 穩健(無債)": {"tw": 25, "lev": 6, "us": 30, "gold": 18, "fx": 15, "bond": 0, "btc": 3},
    "⑥ 成長":     {"tw": 30, "lev": 12, "us": 33, "gold": 12, "fx": 5, "bond": 0, "btc": 5},
    "⑦ 積極":     {"tw": 30, "lev": 20, "us": 30, "gold": 8, "fx": 2, "bond": 0, "btc": 8},
}


def add_bond(rets: pd.DataFrame) -> pd.DataFrame:
    """加 r_bond：TLT(美長債)×匯率 的台幣買入持有日報酬。"""
    tlt = fetch_yahoo_adj("TLT").rename(columns={"close": "tlt"})
    fx = pd.read_csv(os.path.join(CACHE, "USDTWD_full_history.csv"))
    fx.columns = [c.lstrip("﻿") for c in fx.columns]
    fx = fx.rename(columns={"close": "fx"})
    fx = fx[(fx["fx"] > 20) & (fx["fx"] < 45)]
    m = rets.merge(tlt, on="date", how="left").merge(fx, on="date", how="left")
    m["tlt"] = m["tlt"].ffill()
    m["fx"] = m["fx"].ffill()
    m["bond_px"] = m["tlt"] * m["fx"]
    m["r_bond"] = m["bond_px"].pct_change().fillna(0)
    return m


def win_bounds(rets, d0, d1):
    idx = rets.index[(rets["date"] >= d0) & (rets["date"] <= d1)]
    return (int(idx[0]), int(idx[-1]) + 1) if len(idx) >= 40 else None


def port_returns(rets, w, i0, i1, rebal=63):
    keys = [k for k in w if w[k] > 0]
    cols = [f"r_{k}" for k in keys]
    R = rets[cols].to_numpy()[i0:i1]
    w0 = np.array([w[k] for k in keys], float); w0 /= w0.sum()
    wt = w0.copy(); out = np.zeros(len(R))
    for t in range(len(R)):
        out[t] = float(np.dot(wt, R[t]))
        wt = wt * (1.0 + R[t]); wt /= wt.sum()
        if t % rebal == 0:
            wt = w0.copy()
    return out


def main():
    print("=== 風險-報酬取捨曲線 ===")
    rets = build_sleeve_returns()
    rets = add_bond(rets)
    d0, d1 = rets["date"].iloc[0], rets["date"].iloc[-1]
    bounds = [(l, win_bounds(rets, a, b)) for l, a, b in WINDOWS]
    bounds = [(l, b) for l, b in bounds if b]
    print(f"資料 {d0} ~ {d1}\n")

    # 每配置：跨窗最差MDD(風險) + 全期滾動cohort中位CAGR/Sharpe(報酬)
    idxs = list(range(200, len(rets) - HORIZON, COHORT_STEP))
    res = {}
    print(f"{'配置':14s} {'台股%':>5s} {'債%':>4s} | {'最差窗MDD':>9s} {'中位CAGR':>8s} {'CAGR壞窗':>8s} {'Sharpe':>6s}")
    print("-" * 74)
    for name, w in ALLOCS.items():
        worst_mdd = min(metrics_from_returns(port_returns(rets, w, i0, i1))["mdd"]
                        for l, (i0, i1) in bounds)
        cg = [metrics_from_returns(port_returns(rets, w, i0, i0 + HORIZON)) for i0 in idxs]
        cagr_med = float(np.median([m["cagr"] for m in cg]))
        cagr_p10 = float(np.percentile([m["cagr"] for m in cg], 10))
        sharpe_med = float(np.median([m["sharpe"] for m in cg]))
        res[name] = {"weights": w, "worst_mdd": worst_mdd, "cagr_med": cagr_med,
                     "cagr_p10": cagr_p10, "sharpe": sharpe_med,
                     "taiwan": w["tw"] + w["lev"], "bond": w["bond"]}
        print(f"{name:14s} {w['tw']+w['lev']:4.0f}% {w['bond']:3.0f}% | "
              f"{worst_mdd:8.1f}% {cagr_med:+7.1f}% {cagr_p10:+7.1f}% {sharpe_med:6.2f}")

    # 效率前緣：按最差窗MDD排序
    print("\n=== 效率前緣（按風險排序，看多冒風險換多少報酬）===")
    ordered = sorted(res.items(), key=lambda kv: abs(kv[1]["worst_mdd"]))
    prev = None
    for name, r in ordered:
        delta = ""
        if prev:
            dmdd = abs(r["worst_mdd"]) - abs(prev[1]["worst_mdd"])
            dcagr = r["cagr_med"] - prev[1]["cagr_med"]
            if dmdd > 0:
                delta = f"（多冒 {dmdd:.0f}% 回撤 → {'多賺' if dcagr>=0 else '少賺'} {abs(dcagr):.1f}% 報酬｜每1%回撤換 {dcagr/dmdd:+.2f}% 報酬）"
        print(f"  最差窗MDD {r['worst_mdd']:6.1f}%｜中位CAGR {r['cagr_med']:+5.1f}%  {name} {delta}")
        prev = (name, r)

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "range": [d0, d1], "allocations": res}
    with open(os.path.join(out_dir, "risk_return_frontier.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=float)
    md = os.path.join(out_dir, "risk_return_frontier.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 風險-報酬取捨曲線（校準可承受回撤用）\n\n")
        f.write(f"產生：{payload['generated_at']}｜資料 `{d0}` ~ `{d1}`  \n")
        f.write("風險＝跨5危機窗的最差窗MDD；報酬＝滾動5年cohort中位CAGR。"
                "各袖採用規則、含成本；債券(TLT×匯率)買入持有；crypto小衛星另計。  \n\n")
        f.write("| 配置 | 台股% | 債% | 最差窗MDD | 中位CAGR | CAGR壞窗 | Sharpe |\n")
        f.write("| :-- | --: | --: | --: | --: | --: | --: |\n")
        for name, r in ALLOCS.items():
            x = res[name]
            f.write(f"| {name} | {x['taiwan']:.0f}% | {x['bond']:.0f}% | {x['worst_mdd']:.1f}% | "
                    f"{x['cagr_med']:+.1f}% | {x['cagr_p10']:+.1f}% | {x['sharpe']:.2f} |\n")
        f.write("\n## 效率前緣（按風險排序）\n\n")
        f.write("| 最差窗MDD | 中位CAGR | 配置 | 每多1%回撤換到的報酬 |\n| --: | --: | :-- | --: |\n")
        prev = None
        for name, r in ordered:
            ratio = ""
            if prev:
                dmdd = abs(r["worst_mdd"]) - abs(prev[1]["worst_mdd"])
                dcagr = r["cagr_med"] - prev[1]["cagr_med"]
                if dmdd > 0:
                    ratio = f"{dcagr/dmdd:+.2f}%"
            f.write(f"| {r['worst_mdd']:.1f}% | {r['cagr_med']:+.1f}% | {name} | {ratio} |\n")
            prev = (name, r)
        f.write("\n## 怎麼讀\n\n")
        f.write("- 找你能忍受的『最差窗MDD』那一列，看對應中位CAGR。  \n")
        f.write("- 『每多1%回撤換到的報酬』：數字大＝多冒險划算；接近0或負＝多冒險不划算，該選較保守那檔。  \n")
        f.write("- 你直覺說30%：看-30%附近報酬 vs -20%附近，差多少值不值得。  \n")
        f.write("- 債券欄看①②③(含債) vs ④⑤(無債) 在保守端 MDD/CAGR 差異，決定要不要加債。  \n\n")
        f.write("## 限制\n- cohort重疊、獨立樣本少；1980-2000金熊、1970s高通膨不在資料內。  \n")
        f.write("- 這是穩健光譜非最佳解；債券TLT僅2002起、含2022重挫但缺更早的債券多頭。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
