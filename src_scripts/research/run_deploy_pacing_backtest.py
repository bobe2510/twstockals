# -*- coding: utf-8 -*-
"""
建倉節奏回測：趨勢閘門 ON 時，固定預算一次進 vs 分批進（SPY 1993~ 調整價）。

隊列法：每個「閘門 ON」的月初日為一個 cohort，比較四種節奏一年/三年後終值：
  LS=一次進；T3=每21日1/3×3；T6=每21日1/6×6；T12=每21日1/12×12。
未投入現金 0% 計。成本 0.07%/邊（分批多筆）。
輸出：中位數、10 分位（尾部風險）、LS 勝率。
"""
from __future__ import annotations

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

from run_trend_exit_backtest import fetch_yahoo_adj  # noqa: E402

COST = 0.0007
SCHEDULES = {"一次全進(LS)": 1, "3批×每月(T3)": 3, "6批(T6)": 6, "12批(T12)": 12}


def main():
    df = fetch_yahoo_adj("SPY")
    px = df["close"].to_numpy(float)
    dates = df["date"].tolist()
    n = len(px)
    ma200 = pd.Series(px).rolling(200).mean().to_numpy()

    cohorts = []
    for i in range(260, n - 756, 21):  # 月頻 cohort
        gate = px[i] > ma200[i] or px[i] > px[i - 252]
        if gate:
            cohorts.append(i)

    res = {name: {"v1": [], "v3": []} for name in SCHEDULES}
    for i0 in cohorts:
        for name, k in SCHEDULES.items():
            units, cash = 0.0, 1.0
            for j in range(k):
                t = i0 + j * 21
                spend = cash / (k - j)
                units += spend / (px[t] * (1 + COST))
                cash -= spend
            res[name]["v1"].append(units * px[i0 + 252] + cash)
            res[name]["v3"].append(units * px[i0 + 756] + cash)

    out = os.path.join(WORKSPACE, "reports", "latest", "backtest", "deploy_pacing_backtest.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# 建倉節奏回測（SPY 1993~｜閘門ON的月頻隊列）\n\n")
        f.write(f"產生：{datetime.now().isoformat(timespec='seconds')}｜cohorts={len(cohorts)}  \n")
        f.write("固定預算=1；未投入現金 0%；成本 0.07%/邊。  \n\n")
        for horizon, key in (("1年後", "v1"), ("3年後", "v3")):
            f.write(f"## {horizon}終值\n\n| 節奏 | 中位數 | 10分位(尾部) | vs LS 勝率 |\n| :--- | ---: | ---: | ---: |\n")
            ls = np.array(res["一次全進(LS)"][key])
            for name in SCHEDULES:
                v = np.array(res[name][key])
                win = float((v > ls).mean() * 100) if name != "一次全進(LS)" else 0.0
                f.write(f"| {name} | {np.median(v):.3f} | {np.percentile(v,10):.3f} "
                        f"| {'—' if name=='一次全進(LS)' else f'{win:.0f}%'} |\n")
            f.write("\n")
            print(f"[{horizon}] LS median {np.median(ls):.3f}")
        f.write("- 判讀：LS 期望值最高但尾部較差；分批是買心理保險。建議依此選批數並寫死於政策。  \n")
    print(f"報告：{out}")


if __name__ == "__main__":
    main()
