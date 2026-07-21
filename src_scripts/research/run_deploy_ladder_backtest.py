# -*- coding: utf-8 -*-
"""
分批進場的檔位分配：一次進 vs 時間分批 vs 逢回檔階梯。

回答使用者兩問：
  1. 從「像現在的位置」，未來出現更佳回檔的機率多高？（回檔頻率表）
  2. 各檔位分配多少合理？平均進場價落在整段第幾百分位（「買得比人高」的客觀量尺），
     以及最終報酬——逢回檔階梯是否真的比穩定分批好，還是只是感覺好。

資料：SPY 含息調整價（1993~，多空頭）。趨勢ON時進場，成本 0.07%/邊。
每季一個 cohort：12 個月內把固定預算部署完，持有到 +3 年衡量。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts", "research"))

from run_trend_exit_backtest import fetch_yahoo_adj  # noqa: E402

COST = 0.0007
DEPLOY_DAYS = 252          # 12 個月部署窗
HOLD_DAYS = 252 * 3        # 部署後再持有到 +3 年
COHORT_STEP = 63           # 每季一個 cohort
MONTH = 21


def pullback_frequency(px, ma200):
    """趨勢ON日，依『比年線高多少』分桶，統計未來6月內出現 -5%/-10% 回檔的頻率。"""
    n = len(px)
    buckets = {"<0%(年線下)": [], "0~3%": [], "3~6%": [], "6~10%": [], ">10%": []}
    horizon = 126
    for i in range(200, n - horizon):
        if px[i] <= ma200[i]:
            b = "<0%(年線下)"
        else:
            ext = (px[i] / ma200[i] - 1) * 100
            b = "0~3%" if ext < 3 else "3~6%" if ext < 6 else "6~10%" if ext < 10 else ">10%"
        fut = px[i + 1:i + 1 + horizon]
        d5 = bool((fut <= px[i] * 0.95).any())
        d10 = bool((fut <= px[i] * 0.90).any())
        buckets[b].append((d5, d10))
    out = {}
    for b, rows in buckets.items():
        if not rows:
            continue
        a = np.array(rows)
        out[b] = {"n": len(rows), "p_dip5": float(a[:, 0].mean()*100), "p_dip10": float(a[:, 1].mean()*100)}
    return out


def deploy(px_window, schedule):
    """
    在 12 個月窗內部署預算 1.0，回傳 (累積單位, 平均成本, 進場價百分位)。
    schedule: 'lump' | 'dca' | 'dip_ladder'
    dip_ladder：40% 立即；30% 留待 -5%；30% 留待 -10%（相對窗起始價）；未觸發則月底/窗末補。
    """
    p0 = px_window[0]
    n = len(px_window)
    units, spent = 0.0, 0.0
    fills = []  # (price, amount)

    def buy(amount, price):
        nonlocal units, spent
        amount = min(amount, 1.0 - spent)
        if amount <= 1e-9:
            return
        units += amount / (price * (1 + COST))
        spent += amount
        fills.append((price, amount))

    if schedule == "lump":
        buy(1.0, p0)
    elif schedule == "dca":
        months = [min(m * MONTH, n - 1) for m in range(12)]
        for t in months:
            buy(1.0 / 12, px_window[t])
    elif schedule == "dip_ladder":
        buy(0.4, p0)                      # 立即一半不到
        got5 = got10 = False
        for t in range(1, n):
            price = px_window[t]
            if not got5 and price <= p0 * 0.95:
                buy(0.3, price); got5 = True
            if not got10 and price <= p0 * 0.90:
                buy(0.3, price); got10 = True
        if not got5:
            buy(0.3, px_window[-1])       # 沒等到 -5% → 窗末補
        if not got10:
            buy(0.3, px_window[-1])
    # 進場價百分位：平均成本落在整段每日價的第幾百分位（0=最便宜、100=最貴）
    avg_cost = spent / units if units > 0 else p0
    pct_rank = float((px_window < avg_cost).mean() * 100)
    return units, avg_cost, pct_rank


def main():
    print("=== 分批檔位分配：一次進 vs 時間分批 vs 逢回檔階梯 ===")
    df = fetch_yahoo_adj("SPY")
    px = df["close"].to_numpy(float)
    ma200 = pd.Series(px).rolling(200).mean().to_numpy()
    n = len(px)
    print(f"SPY {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}\n")

    # 1) 回檔頻率
    print("--- 未來6個月內出現回檔的機率（依現在比年線高多少）---")
    freq = pullback_frequency(px, ma200)
    print(f"  {'位置':14s} {'樣本':>7s} {'-5%回檔':>8s} {'-10%回檔':>9s}")
    for b, r in freq.items():
        print(f"  {b:14s} {r['n']:7d} {r['p_dip5']:7.0f}% {r['p_dip10']:8.0f}%")

    # 2) 部署排程比較
    print("\n--- 部署排程比較（每季cohort、12月部署、持有到+3年）---")
    cohorts = [i for i in range(200, n - DEPLOY_DAYS - HOLD_DAYS, COHORT_STEP)
               if px[i] > ma200[i]]  # 只在趨勢ON進場
    scheds = ["lump", "dca", "dip_ladder"]
    names = {"lump": "一次進(lump)", "dca": "時間分批(每月×12)", "dip_ladder": "逢回檔階梯(40/30/30)"}
    agg = {s: {"final": [], "pctrank": [], "avgcost_vs_lump": []} for s in scheds}
    for i0 in cohorts:
        win = px[i0:i0 + DEPLOY_DAYS]
        end_px = px[i0 + DEPLOY_DAYS + HOLD_DAYS - 1]
        lump_units = 1.0 / (win[0] * (1 + COST))
        for s in scheds:
            u, avg_cost, pr = deploy(win, s)
            agg[s]["final"].append(u * end_px)          # +3年後每1元變多少
            agg[s]["pctrank"].append(pr)
            agg[s]["avgcost_vs_lump"].append((avg_cost / win[0] - 1) * 100)

    print(f"  {'排程':22s} {'+3年終值(中位)':>12s} {'進場價%位(中位)':>14s} {'均價vs一次進':>12s}")
    res = {}
    for s in scheds:
        fmed = float(np.median(agg[s]["final"]))
        prmed = float(np.median(agg[s]["pctrank"]))
        acmed = float(np.median(agg[s]["avgcost_vs_lump"]))
        res[s] = {"final_med": fmed, "pctrank_med": prmed, "avgcost_vs_lump_med": acmed,
                  "final_p10": float(np.percentile(agg[s]["final"], 10))}
        print(f"  {names[s]:22s} {fmed:11.3f}  {prmed:12.0f}%  {acmed:+10.2f}%")

    print("\n判讀：")
    print("  · 進場價%位愈低＝買得愈便宜（相對整段）；一次進通常最高（買最貴），階梯最低。")
    print("  · 但看+3年終值：若階梯終值沒比較高，代表『買得便宜』被『等待時少賺的漲幅』抵掉。")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "range": [df["date"].iloc[0], df["date"].iloc[-1]],
               "pullback_freq": freq, "schedules": res, "n_cohorts": len(cohorts)}
    with open(os.path.join(out_dir, "deploy_ladder_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    md = os.path.join(out_dir, "deploy_ladder_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 分批檔位分配：一次進 vs 時間分批 vs 逢回檔階梯\n\n")
        f.write(f"產生：{payload['generated_at']}｜SPY `{df['date'].iloc[0]}`~`{df['date'].iloc[-1]}`"
                f"｜{len(cohorts)} cohorts  \n\n")
        f.write("## 1. 從「像現在的位置」未來6月出現回檔的機率\n\n")
        f.write("| 現在位置(比年線) | 樣本 | 未來6月 -5%回檔 | -10%回檔 |\n| :-- | --: | --: | --: |\n")
        for b, r in freq.items():
            f.write(f"| {b} | {r['n']} | {r['p_dip5']:.0f}% | {r['p_dip10']:.0f}% |\n")
        f.write("\n> 讀法：若現在比年線高6~10%，未來6月內出現 -5% 回檔的機率＝該列。"
                "機率不低不代表『等得到且更划算』——見下表終值。\n\n")
        f.write("## 2. 部署排程（12月部署、持有到+3年、每季cohort中位數）\n\n")
        f.write("| 排程 | +3年終值 | +3年終值(壞窗10%) | 進場價%位 | 均價vs一次進 |\n")
        f.write("| :-- | --: | --: | --: | --: |\n")
        for s in scheds:
            r = res[s]
            f.write(f"| {names[s]} | {r['final_med']:.3f} | {r['final_p10']:.3f} | "
                    f"{r['pctrank_med']:.0f}% | {r['avgcost_vs_lump_med']:+.2f}% |\n")
        f.write("\n## 判讀\n\n")
        f.write("- **進場價%位**：愈低＝相對整段買得愈便宜（0=最便宜日）。這是「買得比人高多少」的客觀量尺。  \n")
        f.write("- **+3年終值**：把「買得便宜」和「等待少賺」都算進去的淨結果。  \n")
        f.write("- 若逢回檔階梯的『進場價%位』較低但『終值』沒較高 → 便宜被少賺抵掉，"
                "省的是心理不是報酬。  \n")
        f.write("- 限制：SPY 長多頭市場;結論對趨勢向上資產有效,對長期盤整/下跌資產可能相反。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
