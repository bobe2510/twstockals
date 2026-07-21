# -*- coding: utf-8 -*-
"""
配置的跨危機穩健性：獨立(不重疊)5年窗，每窗一種不同機制的黑天鵝。

哲學（與使用者對齊）：無法預測下一隻黑天鵝長什麼樣，所以不挑「對某次危機最優」，
而選「在各種不同類型的過去危機裡都活得下來」的配置——判準是『最差窗有多難看』
(minimax)，不是平均。

各袖用實際採用規則（正2/美股帶趨勢閘門、0050/黃金長抱、美金含利差），含成本，
每季再平衡。crypto 3% 小衛星另計、不進此表（歷史短、採用期噴發會歪，已決定固定3%）。

窗（不同壓力機制）：
  W1 2004-2008  多頭→GFC 信用海嘯
  W2 2009-2013  復甦＋歐債＋黃金大多頭
  W3 2014-2018  黃金熊市(-45%)＋2015中國股災＋低波動
  W4 2019-2023  COVID閃崩＋2022升息股債雙殺
  W5 2024-2026  近期(部分年)
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
    build_sleeve_returns, portfolio_returns, metrics_from_returns, NAMES,
)

BIG5 = ["tw", "lev", "us", "gold", "fx"]

WINDOWS = [
    ("W1 04-08 GFC", "2004-01-01", "2008-12-31"),
    ("W2 09-13 歐債/金牛", "2009-01-01", "2013-12-31"),
    ("W3 14-18 金熊/中股", "2014-01-01", "2018-12-31"),
    ("W4 19-23 COVID/升息", "2019-01-01", "2023-12-31"),
    ("W5 24-26 近期", "2024-01-01", "2099-12-31"),
]

# 一組「適度分散」候選：台股降、黃金由低到高，看高黃金是否只在金牛窗贏
CANDS = {
    "現行(台53/金14)":   {"tw": 39.3, "lev": 13.5, "us": 19.1, "gold": 14.0, "fx": 14.0},
    "降台-低金(台38/金16)": {"tw": 30, "lev": 8, "us": 34, "gold": 16, "fx": 12},
    "降台-中金(台36/金22)": {"tw": 28, "lev": 8, "us": 28, "gold": 22, "fx": 14},
    "平衡-高金(台36/金26)": {"tw": 28, "lev": 8, "us": 28, "gold": 26, "fx": 10},
    "等權(台40/金20)":    {s: 20.0 for s in BIG5},
}


def win_bounds(rets, d0, d1):
    idx = rets.index[(rets["date"] >= d0) & (rets["date"] <= d1)]
    if len(idx) < 40:
        return None
    return int(idx[0]), int(idx[-1]) + 1


def main():
    print("=== 配置跨危機穩健性（獨立5年窗）===")
    rets = build_sleeve_returns()
    print(f"資料 {rets['date'].iloc[0]} ~ {rets['date'].iloc[-1]}\n")

    bounds = [(lbl, win_bounds(rets, a, b)) for lbl, a, b in WINDOWS]
    bounds = [(l, b) for l, b in bounds if b]

    # 各袖參考（看每窗是什麼regime）
    print("--- 各袖 CAGR%／MDD% 每窗（regime 參考）---")
    hdr = "袖     " + " ".join(f"{l.split()[0]:>16s}" for l, _ in bounds)
    print(hdr)
    sleeve_ref = {}
    for s in BIG5:
        cells, row = [], f"{NAMES[s]:6s}"
        for lbl, (i0, i1) in bounds:
            m = metrics_from_returns(rets[f"r_{s}"].to_numpy()[i0:i1])
            cells.append(f"{m['cagr']:+.0f}/{m['mdd']:.0f}")
            sleeve_ref.setdefault(s, {})[lbl] = {"cagr": round(m["cagr"], 1), "mdd": round(m["mdd"], 1)}
        print(row + " " + " ".join(f"{c:>16s}" for c in cells))

    # 候選 × 窗
    print("\n--- 候選組合 CAGR%／MDD% 每窗 ---")
    print("組合                " + " ".join(f"{l.split()[0]:>16s}" for l, _ in bounds) + "   最差窗CAGR 最差窗MDD")
    res = {}
    for name, w in CANDS.items():
        w2 = {s: v for s, v in w.items() if v > 0}
        cells, cagrs, mdds = [], [], []
        per_win = {}
        for lbl, (i0, i1) in bounds:
            m = metrics_from_returns(portfolio_returns(rets, w2, i0, i1))
            cells.append(f"{m['cagr']:+.0f}/{m['mdd']:.0f}")
            cagrs.append(m["cagr"]); mdds.append(m["mdd"])
            per_win[lbl] = {"cagr": round(m["cagr"], 1), "mdd": round(m["mdd"], 1)}
        worst_cagr, worst_mdd = min(cagrs), min(mdds)
        res[name] = {"per_win": per_win, "worst_cagr": worst_cagr, "worst_mdd": worst_mdd,
                     "mean_cagr": float(np.mean(cagrs))}
        print(f"{name:20s} " + " ".join(f"{c:>16s}" for c in cells) +
              f"   {worst_cagr:+8.1f}%  {worst_mdd:8.1f}%")

    # minimax 排名
    print("\n依『最差窗 CAGR』排名（愈高＝各種危機都撐得住）：")
    for i, (n, r) in enumerate(sorted(res.items(), key=lambda kv: kv[1]["worst_cagr"], reverse=True), 1):
        print(f"  {i}. {n}：最差窗 CAGR {r['worst_cagr']:+.1f}%、最差窗 MDD {r['worst_mdd']:.1f}%、平均 {r['mean_cagr']:+.1f}%")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "windows": [{"label": l, "start": a, "end": b} for l, a, b in WINDOWS],
               "sleeve_ref": sleeve_ref, "candidates": res}
    with open(os.path.join(out_dir, "allocation_regime_windows.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = os.path.join(out_dir, "allocation_regime_windows.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 配置跨危機穩健性（獨立5年窗）\n\n")
        f.write(f"產生：{payload['generated_at']}｜資料 `{rets['date'].iloc[0]}` ~ `{rets['date'].iloc[-1]}`  \n")
        f.write("哲學：無法預測下一隻黑天鵝長相，故選『各種過去危機都撐得住』者；"
                "判準＝**最差窗**(minimax)，非平均。各袖採用規則、含成本、每季再平衡；"
                "crypto 3% 另計不入表。  \n\n")
        f.write("## 各袖每窗 CAGR%／MDD%（看每窗是什麼regime）\n\n")
        f.write("| 袖 | " + " | ".join(l for l, _ in bounds) + " |\n")
        f.write("| :-- |" + " --: |" * len(bounds) + "\n")
        for s in BIG5:
            f.write(f"| {NAMES[s]} | " + " | ".join(
                f"{sleeve_ref[s][l]['cagr']:+.0f}/{sleeve_ref[s][l]['mdd']:.0f}" for l, _ in bounds) + " |\n")
        f.write("\n> 例：W3 看黃金那格＝黃金熊市有多慘；W4 看正2/美股＝COVID+升息雙殺。\n\n")
        f.write("## 候選組合每窗 CAGR%／MDD% ＋ 最差窗\n\n")
        f.write("| 組合 | " + " | ".join(l for l, _ in bounds) + " | 最差窗CAGR | 最差窗MDD |\n")
        f.write("| :-- |" + " --: |" * (len(bounds) + 2) + "\n")
        for name, r in res.items():
            cells = " | ".join(f"{r['per_win'][l]['cagr']:+.0f}/{r['per_win'][l]['mdd']:.0f}" for l, _ in bounds)
            f.write(f"| {name} | {cells} | {r['worst_cagr']:+.1f}% | {r['worst_mdd']:.1f}% |\n")
        f.write("\n## 依最差窗 CAGR 排名（minimax）\n\n")
        for i, (n, r) in enumerate(sorted(res.items(), key=lambda kv: kv[1]["worst_cagr"], reverse=True), 1):
            f.write(f"{i}. **{n}**：最差窗 CAGR {r['worst_cagr']:+.1f}%、最差窗 MDD {r['worst_mdd']:.1f}%、平均 {r['mean_cagr']:+.1f}%  \n")
        f.write("\n## 判讀\n\n")
        f.write("- 看『高黃金(平衡-高金)』是否只在 W2/W4(金牛)贏、在 W3(金熊)墊底＝賭regime不穩健。  \n")
        f.write("- 最差窗 CAGR 最高者＝哪種危機來都不會太難看，抗未知黑天鵝。  \n")
        f.write("- 限制：僅 4-5 個獨立窗、樣本少；且 1980-2000 黃金大熊市不在資料內"
                "（無免費源），故對黃金仍宜保守設上限。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
