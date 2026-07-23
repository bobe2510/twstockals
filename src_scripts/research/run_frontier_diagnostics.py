# -*- coding: utf-8 -*-
"""
前緣細部點（-18%~-28%）＋ 過擬合診斷。

在 ③(-18%)~⑥(-28%) 之間插密集點，每個點附三個過擬合檢查：
  ① 單調性：報酬是否隨風險平滑上升（沿排序看；亂序＝噪音）
  ② 近期依賴：只用『2019前進場』的cohort中位CAGR vs 全部；差很多＝靠近期(recency)
  ③ 擾動穩定：權重各 ±3pp 隨機擾動 N 次，中位CAGR 的散布；散布 > 相鄰點差距＝脆弱

各袖採用規則、含成本；債券TLT×匯率買入持有；BTC 固定 3% 小衛星。
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

from run_risk_return_frontier import (  # noqa: E402
    build_sleeve_returns, add_bond, metrics_from_returns, port_returns,
    win_bounds, WINDOWS, HORIZON,
)

COHORT_STEP = 126
N_PERTURB = 16
PERTURB_PP = 3.0
RNG = np.random.default_rng(42)

# 中間點：由防禦→溫和，逐步把 債/金/美金 換成 台股/美股，槓桿保持溫和、BTC固定3%
GRID = {
    "A ~18%": {"tw": 22, "lev": 4, "us": 26, "gold": 16, "fx": 12, "bond": 17, "btc": 3},
    "B ~20%": {"tw": 25, "lev": 5, "us": 28, "gold": 15, "fx": 11, "bond": 13, "btc": 3},
    "C ~22%": {"tw": 27, "lev": 6, "us": 30, "gold": 14, "fx": 10, "bond": 10, "btc": 3},
    "D ~24%": {"tw": 28, "lev": 7, "us": 31, "gold": 14, "fx": 9, "bond": 8, "btc": 3},
    "E ~26%": {"tw": 29, "lev": 9, "us": 32, "gold": 13, "fx": 7, "bond": 7, "btc": 3},
    "F ~28%": {"tw": 30, "lev": 11, "us": 33, "gold": 12, "fx": 6, "bond": 5, "btc": 3},
}


def median_cagr(rets, w, idxs):
    return float(np.median([metrics_from_returns(port_returns(rets, w, i0, i0 + HORIZON))["cagr"]
                            for i0 in idxs]))


def perturb(w):
    keys = [k for k in w if w[k] > 0 or k in ("bond",)]
    v = np.array([w[k] for k in keys], float) + RNG.uniform(-PERTURB_PP, PERTURB_PP, len(keys))
    v = np.clip(v, 0, None)
    if v.sum() <= 0:
        return dict(w)
    v = v / v.sum() * 100
    return {k: float(x) for k, x in zip(keys, v)}


def main():
    print("=== 前緣細部 + 過擬合診斷 ===")
    rets = add_bond(build_sleeve_returns())
    bounds = [(l, win_bounds(rets, a, b)) for l, a, b in WINDOWS]
    bounds = [(l, b) for l, b in bounds if b]
    all_idx = list(range(200, len(rets) - HORIZON, COHORT_STEP))
    old_idx = [i for i in all_idx if rets["date"].iloc[i] < "2019-01-01"]
    print(f"cohorts 全部 {len(all_idx)}｜2019前 {len(old_idx)}\n")

    rows = {}
    print(f"{'配置':8s} {'最差窗MDD':>9s} {'全期CAGR':>8s} {'2019前CAGR':>10s} {'近期依賴':>7s} {'擾動±':>7s}")
    print("-" * 60)
    for name, w in GRID.items():
        worst = min(metrics_from_returns(port_returns(rets, w, i0, i1))["mdd"] for l, (i0, i1) in bounds)
        cagr_all = median_cagr(rets, w, all_idx)
        cagr_old = median_cagr(rets, w, old_idx) if old_idx else float("nan")
        recency_gap = cagr_all - cagr_old
        pert = [median_cagr(rets, perturb(w), all_idx) for _ in range(N_PERTURB)]
        pert_spread = float(np.std(pert))
        rows[name] = {"worst_mdd": worst, "cagr_all": cagr_all, "cagr_old": cagr_old,
                      "recency_gap": recency_gap, "pert_std": pert_spread}
        print(f"{name:8s} {worst:8.1f}% {cagr_all:+7.1f}% {cagr_old:+9.1f}% "
              f"{recency_gap:+6.1f}% ±{pert_spread:5.2f}%")

    # 診斷
    print("\n=== 過擬合診斷 ===")
    ordered = sorted(rows.items(), key=lambda kv: abs(kv[1]["worst_mdd"]))
    prev = None
    mono_ok = True
    for name, r in ordered:
        if prev and r["cagr_all"] < prev[1]["cagr_all"] - 0.3:
            print(f"  ⚠️ 單調性破：{name} 比 {prev[0]} 回撤深卻報酬低 → 噪音")
            mono_ok = False
        prev = (name, r)
    if mono_ok:
        print("  ✅ 單調性：報酬隨風險平滑上升，無亂序")
    max_step = max(abs(ordered[i][1]["cagr_all"] - ordered[i-1][1]["cagr_all"])
                   for i in range(1, len(ordered)))
    max_pert = max(r["pert_std"] for _, r in rows.items())
    if max_pert > max_step:
        print(f"  ⚠️ 擾動散布(±{max_pert:.2f}%) > 相鄰點差距({max_step:.2f}%) → 前緣在噪音內，別追小數點")
    else:
        print(f"  ✅ 擾動散布(±{max_pert:.2f}%) < 相鄰點差距({max_step:.2f}%) → 排序穩健")
    worst_recency = max(rows.items(), key=lambda kv: kv[1]["recency_gap"])
    print(f"  近期依賴最大：{worst_recency[0]} 全期比2019前高 {worst_recency[1]['recency_gap']:+.1f}%"
          + ("（偏高，該配置報酬較靠近期）" if worst_recency[1]["recency_gap"] > 3 else "（尚可）"))

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    with open(os.path.join(out_dir, "frontier_diagnostics.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"), "rows": rows},
                  f, ensure_ascii=False, indent=2, default=float)
    md = os.path.join(out_dir, "frontier_diagnostics.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 前緣細部（-18%~-28%）+ 過擬合診斷\n\n")
        f.write(f"產生：{datetime.now().isoformat(timespec='seconds')}｜cohorts 全 {len(all_idx)}／2019前 {len(old_idx)}  \n\n")
        f.write("| 配置 | 最差窗MDD | 全期CAGR | 2019前CAGR | 近期依賴 | 擾動± | 每步換報酬 |\n")
        f.write("| :-- | --: | --: | --: | --: | --: | --: |\n")
        prev = None
        for name, r in ordered:
            step = ""
            if prev:
                dmdd = abs(r["worst_mdd"]) - abs(prev[1]["worst_mdd"])
                dc = r["cagr_all"] - prev[1]["cagr_all"]
                if dmdd > 0:
                    step = f"{dc/dmdd:+.2f}%/1%回撤"
            f.write(f"| {name} | {r['worst_mdd']:.1f}% | {r['cagr_all']:+.1f}% | {r['cagr_old']:+.1f}% | "
                    f"{r['recency_gap']:+.1f}% | ±{r['pert_std']:.2f}% | {step} |\n")
            prev = (name, r)
        f.write("\n## 過擬合診斷判讀\n\n")
        f.write("- **單調性**：沿最差窗MDD排序，全期CAGR是否平滑上升。破序＝噪音。  \n")
        f.write("- **近期依賴**：全期CAGR − 2019前CAGR。差距大（>3%）＝該配置報酬靠2019後(正2/幣近期噴)撐，較不穩。  \n")
        f.write("- **擾動±**：權重各±3pp隨機擾動後中位CAGR的標準差。若 > 相鄰配置差距，代表你在追的差異落在雜訊內。  \n")
        f.write("- **每步換報酬**：多冒1%回撤換到的CAGR；數字小＝該段不划算。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
