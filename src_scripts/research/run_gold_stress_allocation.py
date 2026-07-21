# -*- coding: utf-8 -*-
"""
黃金配置的抗壓性檢驗：回答「25%黃金是不是只因近期金價飆漲才顯得好」。

方法（用真實資料，不 embedding，誠實面對資料限制）：
  1. 黃金熊市壓力窗：2011-08 ~ 2016-01（金價真實崩約 -45%，就在資料內）——
     各候選在這段的報酬/回撤，看高黃金配置傷多重。
  2. 排除近期黃金飆漲：把資料截到 2018-12（切掉 2019-2026 黃金＋全資產大多頭），
     重跑 cohort 排名，看結論是否只靠近期。
  3. 全期 vs 截尾 的 CP 排名對照。

資料限制誠實揭露：1980-2000 黃金 20 年大熊市無免費資料源，本測涵蓋
2004-2026（含 2011-2015 熊市），不含 1980-2000。結論須配合此限制解讀。
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

from run_allocation_robustness_backtest import (  # noqa: E402
    build_sleeve_returns, portfolio_returns, metrics_from_returns,
    HORIZON, COHORT_STEP,
)

BIG5 = ["tw", "lev", "us", "gold", "fx"]
CANDS = {
    "現行(正規化)":   {"tw": 39.3, "lev": 13.5, "us": 19.1, "gold": 14.0, "fx": 14.0},
    "C 平衡(金26)":   {"tw": 28, "lev": 8, "us": 28, "gold": 26, "fx": 10},
    "股債金三分(金30)": {"tw": 30, "lev": 8, "us": 25, "gold": 30, "fx": 7},
    "C-低金(金18)":   {"tw": 28, "lev": 8, "us": 34, "gold": 18, "fx": 12},
    "等權(金20)":     {s: 20.0 for s in BIG5},
}
GOLD_BEAR = ("2011-08-22", "2016-01-04")  # 金價高峰→谷底


def window_metrics(rets, w, d0, d1):
    idx = rets.index[(rets["date"] >= d0) & (rets["date"] <= d1)]
    if len(idx) < 20:
        return None
    r = portfolio_returns(rets, w, int(idx[0]), int(idx[-1]) + 1)
    return metrics_from_returns(r)


def cohort_cp(rets, w, start_i, end_i):
    idxs = [i for i in range(start_i, end_i - HORIZON, COHORT_STEP) if i + HORIZON <= end_i]
    if not idxs:
        return None
    cps = [metrics_from_returns(portfolio_returns(rets, w, i0, i0 + HORIZON))["cp"] for i0 in idxs]
    cagrs = [metrics_from_returns(portfolio_returns(rets, w, i0, i0 + HORIZON))["cagr"] for i0 in idxs]
    return {"cp_med": float(np.median(cps)), "cagr_med": float(np.median(cagrs)), "n": len(idxs)}


def main():
    print("=== 黃金配置抗壓性 ===")
    rets = build_sleeve_returns()
    d0, d1 = rets["date"].iloc[0], rets["date"].iloc[-1]
    end2018 = int(rets.index[rets["date"] <= "2018-12-31"][-1]) + 1
    print(f"資料 {d0} ~ {d1}｜截尾點 2018-12（cohort 只用 ≤2018 進場）\n")

    # 黃金單袖在熊市窗
    gser = rets["r_gold"].to_numpy()
    gi = rets.index[(rets["date"] >= GOLD_BEAR[0]) & (rets["date"] <= GOLD_BEAR[1])]
    gnav = np.cumprod(1 + gser[int(gi[0]):int(gi[-1]) + 1])
    print(f"[壓力窗 {GOLD_BEAR[0]}~{GOLD_BEAR[1]}] 黃金單袖總報酬 "
          f"{(gnav[-1]-1)*100:+.1f}%，最深 {((gnav-np.maximum.accumulate(gnav))/np.maximum.accumulate(gnav)).min()*100:.1f}%\n")

    rows = {}
    print(f"{'配置':16s} {'金%':>4s} | {'熊市窗報酬':>9s} {'熊市窗MDD':>9s} | "
          f"{'全期CP':>6s} {'截2018CP':>8s} {'CP差':>6s}")
    print("-" * 74)
    for name, w in CANDS.items():
        w2 = {s: v for s, v in w.items() if v > 0}
        bear = window_metrics(rets, w2, *GOLD_BEAR)
        full = cohort_cp(rets, w2, 200, len(rets))
        trim = cohort_cp(rets, w2, 200, end2018)
        gp = w.get("gold", 0)
        d_cp = full["cp_med"] - trim["cp_med"]
        rows[name] = {"gold_pct": gp, "bear_ret": bear["cagr"], "bear_mdd": bear["mdd"],
                      "cp_full": full["cp_med"], "cp_trim2018": trim["cp_med"], "cp_delta": d_cp}
        print(f"{name:16s} {gp:3.0f}% | {bear['cagr']:+8.2f}% {bear['mdd']:8.1f}% | "
              f"{full['cp_med']:5.2f} {trim['cp_med']:7.2f} {d_cp:+6.2f}")

    print("\n判讀：")
    print("  · 熊市窗報酬/MDD＝高黃金配置在黃金崩盤時的實際傷害")
    print("  · CP差(全期−截2018)大＝該配置的好處主要來自 2019+ 近期，較不穩健")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "range": [d0, d1], "gold_bear_window": GOLD_BEAR,
               "data_limit_note": "1980-2000 黃金大熊市無免費資料，本測 2004-2026（含2011-2015熊市）",
               "results": rows}
    with open(os.path.join(out_dir, "gold_stress_allocation.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    md = os.path.join(out_dir, "gold_stress_allocation.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 黃金配置抗壓性檢驗\n\n")
        f.write(f"產生：{payload['generated_at']}｜資料 `{d0}` ~ `{d1}`  \n")
        f.write(f"**資料限制（誠實揭露）**：黃金 1980-2000 的 20 年大熊市無免費資料源可取得，"
                f"本測涵蓋 2004-2026（**含** 2011-2015 約 -45% 熊市），**不含** 1980-2000。  \n\n")
        f.write(f"## 黃金熊市壓力窗（{GOLD_BEAR[0]} ~ {GOLD_BEAR[1]}，金價真實崩約 -45%）\n\n")
        f.write("| 配置 | 黃金% | 熊市窗報酬 | 熊市窗MDD | 全期CP | 截至2018CP | CP差(近期貢獻) |\n")
        f.write("| :-- | --: | --: | --: | --: | --: | --: |\n")
        for name, r in rows.items():
            f.write(f"| {name} | {r['gold_pct']:.0f}% | {r['bear_ret']:+.2f}% | {r['bear_mdd']:.1f}% | "
                    f"{r['cp_full']:.2f} | {r['cp_trim2018']:.2f} | {r['cp_delta']:+.2f} |\n")
        f.write("\n## 判讀\n\n")
        f.write("- **熊市窗**：高黃金配置在 2011-2015 黃金崩盤時傷多重（報酬/回撤）。  \n")
        f.write("- **CP差(全期−截2018)**：若某配置的好處主要來自 2019+，CP差會大＝較依賴近期、較不穩健。  \n")
        f.write("- **仍缺 1980-2000**：那段黃金腰斬再腰斬，25-30% 黃金會是明顯拖累；"
                "故即使本測黃金看來不錯，仍宜對黃金設上限、保守看待。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
