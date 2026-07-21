# -*- coding: utf-8 -*-
"""
候選配置比較：沿「報酬↔風險」光譜排一組配置，給使用者選擇的資訊。

設計原則（來自 allocation_robustness_backtest 的發現）：
  - 降台灣集中（現行 0050+正2 ≈53%）
  - 美金目標砍到流動性尺寸（現行 14%，風險收益比最差）
  - 安置孤兒 tw_stocks 8%（個股已出清、政策不再開新個股）
  - 不整個移除任何商品

沿用同一套引擎：各袖採用規則後日報酬、每季再平衡、滾動5年cohort。
輸出報酬/風險/風險調整三類指標，含 10 分位(壞窗)與最差 cohort MDD(風險天花板)。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import numpy as np

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts", "research"))

from run_allocation_robustness_backtest import (  # noqa: E402
    build_sleeve_returns, portfolio_returns, metrics_from_returns,
    HORIZON, COHORT_STEP, NAMES,
)

BIG5 = ["tw", "lev", "us", "gold", "fx"]

# 候選配置（big-5，總和100）；沿報酬→風險光譜排列
CANDIDATES = {
    "現行(正規化)":   {"tw": 39.3, "lev": 13.5, "us": 19.1, "gold": 14.0, "fx": 14.0},
    "A 微調(砍美金)": {"tw": 38, "lev": 12, "us": 24, "gold": 18, "fx": 8},
    "B 降台灣(中改)": {"tw": 32, "lev": 10, "us": 28, "gold": 22, "fx": 8},
    "C 平衡":        {"tw": 28, "lev": 8,  "us": 28, "gold": 26, "fx": 10},
    "D 防禦(低波動)": {"tw": 25, "lev": 5,  "us": 30, "gold": 30, "fx": 10},
    "股債金三分":     {"tw": 30, "lev": 8,  "us": 25, "gold": 30, "fx": 7},
    "等權":          {s: 20.0 for s in BIG5},
}


def rich_cohorts(rets, weights, start_i):
    idxs = list(range(start_i, len(rets) - HORIZON, COHORT_STEP))
    ms = [metrics_from_returns(portfolio_returns(rets, weights, i0, i0 + HORIZON))
          for i0 in idxs]
    def col(k):
        return np.array([m[k] for m in ms])
    return {
        "cagr_med": float(np.median(col("cagr"))),
        "cagr_p10": float(np.percentile(col("cagr"), 10)),
        "mdd_med": float(np.median(col("mdd"))),
        "mdd_worst": float(col("mdd").min()),
        "cp_med": float(np.median(col("cp"))),
        "sharpe_med": float(np.median(col("sharpe"))),
        "n": len(ms),
    }


def taiwan_pct(w):
    return w.get("tw", 0) + w.get("lev", 0)


def main():
    print("=== 候選配置比較 ===")
    rets = build_sleeve_returns()
    d0, d1 = rets["date"].iloc[0], rets["date"].iloc[-1]
    print(f"資料 {d0} ~ {d1}（big-5，不含BTC）\n")

    rows = {}
    hdr = f"{'配置':16s} {'台灣%':>5s} {'CAGR中位':>8s} {'CAGR壞窗':>8s} {'MDD中位':>7s} {'MDD最差':>7s} {'CP':>6s} {'Sharpe':>6s}"
    print(hdr)
    print("-" * len(hdr))
    for name, w in CANDIDATES.items():
        w2 = {s: v for s, v in w.items() if v > 0}
        r = rich_cohorts(rets, w2, 200)
        rows[name] = {"weights": w2, "taiwan_pct": taiwan_pct(w), **r}
        print(f"{name:16s} {taiwan_pct(w):4.0f}% {r['cagr_med']:+7.2f}% {r['cagr_p10']:+7.2f}% "
              f"{r['mdd_med']:6.1f}% {r['mdd_worst']:6.1f}% {r['cp_med']:5.2f} {r['sharpe_med']:5.2f}")

    # 排名：CP（風險調整）與 CAGR壞窗（保守報酬）
    print("\n依 CP（風險調整報酬）排名：")
    for i, (n, r) in enumerate(sorted(rows.items(), key=lambda kv: kv[1]["cp_med"], reverse=True), 1):
        print(f"  {i}. {n}（CP {r['cp_med']:.2f}）")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "range": [d0, d1], "candidates": rows}
    with open(os.path.join(out_dir, "allocation_candidates_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = os.path.join(out_dir, "allocation_candidates_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 候選配置比較（給選擇用）\n\n")
        f.write(f"產生：{payload['generated_at']}｜資料 `{d0}` ~ `{d1}`（big-5，不含BTC；crypto 3% 另計小衛星）  \n")
        f.write("各袖採用規則後日報酬、每季再平衡、滾動5年cohort。"
                "『台灣%』＝0050+正2；『CAGR壞窗』＝cohort 10分位（差年份的報酬）；"
                "『MDD最差』＝所有cohort最深回撤（風險天花板）。CP=CAGR−0.25×|MDD|。  \n\n")
        f.write("| 配置 | 台灣% | 美金% | CAGR中位 | CAGR壞窗 | MDD中位 | MDD最差 | CP | Sharpe |\n")
        f.write("| :-- | --: | --: | --: | --: | --: | --: | --: | --: |\n")
        for name, r in rows.items():
            f.write(f"| {name} | {r['taiwan_pct']:.0f}% | {r['weights'].get('fx',0):.0f}% | "
                    f"{r['cagr_med']:+.2f}% | {r['cagr_p10']:+.2f}% | {r['mdd_med']:.1f}% | "
                    f"{r['mdd_worst']:.1f}% | {r['cp_med']:.2f} | {r['sharpe_med']:.2f} |\n")
        f.write("\n## 各候選權重明細（big-5）\n\n")
        f.write("| 配置 | 0050 | 正2 | 美股 | 黃金 | 美金 |\n| :-- | --: | --: | --: | --: | --: |\n")
        for name, r in rows.items():
            w = r["weights"]
            f.write(f"| {name} | {w.get('tw',0):.0f} | {w.get('lev',0):.0f} | "
                    f"{w.get('us',0):.0f} | {w.get('gold',0):.0f} | {w.get('fx',0):.0f} |\n")
        f.write("\n## 對應到 config（gold_fx 合併、加回 crypto 3%）\n\n")
        f.write("你的 allocation_targets 把黃金+美金合為 `gold_fx`。選定後乘 0.97 再加 crypto 0.03。  \n")
        f.write("例：C平衡 → tw_core_0050 27.2%、tw_lev 7.8%、us_etf 27.2%、gold_fx 34.9%、crypto 3%。  \n\n")
        f.write("## 怎麼讀這張表（選擇指引）\n\n")
        f.write("- **要最高報酬、扛得住深回撤** → 偏現行/A（台灣重、CAGR 稍高、MDD 深）。  \n")
        f.write("- **同報酬但更少回撤（Pareto改善）** → 股債金三分／C 平衡（CAGR 持平、MDD 更低、CP 更高）。  \n")
        f.write("- **最在意回撤、願讓一點報酬** → D 防禦／等權（MDD 最淺、CP 高、CAGR 略低）。  \n")
        f.write("- **CAGR壞窗** 是關鍵：它是『倒楣年份進場』的報酬，愈高代表對時機愈不敏感。  \n\n")
        f.write("## 限制\n\n")
        f.write("- cohort 高度重疊，獨立樣本約4-5段；名次接近時屬雜訊，別追第一名小數點。  \n")
        f.write("- 各袖採現行採用規則；BTC/crypto 未進 big-5（3% 小衛星、歷史短另評）。  \n")
        f.write("- 這是穩健性光譜，非效率前緣最佳解。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
