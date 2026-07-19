# -*- coding: utf-8 -*-
"""
再平衡帶寬最佳化：多資產組合依 allocation_targets 權重，
比較「偏離觸發帶寬」0.5%~10%／永不／季度日曆，各資產真實成本。

組合（台幣計價）：
  0050代理(TWII+3.5%股息) 43%｜正2(合成+實際) 12%｜黃金TWD 12.5%｜
  美金(+1.5%/年利差) 12.5%｜SPY(調整價×匯率) 17%｜BTC(×匯率) 3%
兩個窗：含BTC(2015~)；長窗不含BTC(2006~，權重等比放大)。
觸發＝任一資產絕對偏離>帶寬 → 全組回到目標權重（賣付賣邊、買付買邊）。
CP = CAGR − 0.25×|MDD| − 1.5×Ops（每筆資產交易 0.2 ops）。
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
INITIAL = 1_000_000.0
LAMBDA_MDD = 0.25
LAMBDA_OPS = 1.5
EOD_OPS = 0.2
DIV_0050 = 0.035 / 252.0
CARRY_USD = 0.015 / 252.0

# (asset, target_weight, buy_cost, sell_cost)
ASSETS = [
    ("tw0050", 0.43, 0.001925, 0.002925),
    ("lev", 0.12, 0.001925, 0.002925),
    ("gold", 0.125, 0.005, 0.005),
    ("usd", 0.125, 0.0015, 0.0015),
    ("spy", 0.17, 0.0007, 0.0007),
    ("btc", 0.03, 0.0015, 0.0015),
]


def load_prices() -> pd.DataFrame:
    lev_df, _ = build_dataset()
    base = lev_df[["date", "twii_close", "lev_close"]].rename(
        columns={"twii_close": "tw0050_px", "lev_close": "lev_px"}
    )
    gold = pd.read_csv(os.path.join(CACHE, "GOLD_USD_full_history.csv")).rename(
        columns={"close": "gold_usd"}
    )
    fx = pd.read_csv(os.path.join(CACHE, "USDTWD_full_history.csv")).rename(
        columns={"close": "usd_px"}
    )
    fx = fx[(fx["usd_px"] > 20) & (fx["usd_px"] < 45)]
    spy = fetch_yahoo_adj("SPY").rename(columns={"close": "spy_usd"})
    btc = fetch_yahoo_adj("BTC-USD").rename(columns={"close": "btc_usd"})

    df = base
    for other in (gold, fx, spy, btc):
        df = df.merge(other, on="date", how="left")
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("gold_usd", "usd_px", "spy_usd", "btc_usd"):
        df[c] = df[c].ffill()
    df["gold_px"] = df["gold_usd"] * df["usd_px"]
    df["spy_px"] = df["spy_usd"] * df["usd_px"]
    df["btc_px"] = df["btc_usd"] * df["usd_px"]
    return df.dropna(subset=["tw0050_px", "lev_px", "gold_px", "usd_px", "spy_px"]).reset_index(drop=True)


def simulate(df: pd.DataFrame, assets: list, *, band: float | None, calendar_days: int | None) -> dict:
    n = len(df)
    px = {a: df[f"{a}_px"].to_numpy(float) for a, _, _, _ in assets}
    tgt = {a: w for a, w, _, _ in assets}
    # 權重正規化（不含 BTC 的長窗）
    s = sum(tgt.values())
    tgt = {a: w / s for a, w in tgt.items()}
    bc = {a: b for a, _, b, _ in assets}
    sc = {a: c for a, _, _, c in assets}

    units = {a: INITIAL * tgt[a] / px[a][0] for a in tgt}
    equity = []
    trades = 0
    rebalances = 0
    turnover = 0.0

    for i in range(n):
        # 持有收益調整：0050 股息、美金利差（以增值近似）
        if i > 0:
            units["tw0050"] *= 1.0 + DIV_0050
            units["usd"] *= 1.0 + CARRY_USD
        vals = {a: units[a] * px[a][i] for a in tgt}
        total = sum(vals.values())
        equity.append(total)
        if i >= n - 1 or total <= 0:
            continue

        do_rb = False
        if calendar_days:
            do_rb = i > 0 and i % calendar_days == 0
        elif band is not None:
            do_rb = any(abs(vals[a] / total - tgt[a]) > band for a in tgt)

        if do_rb:
            rebalances += 1
            for a in tgt:
                want = tgt[a] * total
                diff = want - vals[a]
                if abs(diff) < total * 0.001:
                    continue
                if diff < 0:  # sell
                    cost = -diff * sc[a]
                else:  # buy
                    cost = diff * bc[a]
                units[a] = (want - cost * (1 if diff > 0 else 0)) / px[a][i]
                total -= cost if diff < 0 else 0  # 簡化：賣邊成本自總值扣
                trades += 1
                turnover += abs(diff)

    eq = pd.Series(equity)
    years = max(len(eq) / 252.0, 0.1)
    final = float(eq.iloc[-1])
    cagr = ((final / INITIAL) ** (1 / years) - 1) * 100
    mdd = float(((eq - eq.cummax()) / eq.cummax() * 100).min())
    ops = trades * EOD_OPS / years
    cp = cagr - LAMBDA_MDD * abs(mdd) - LAMBDA_OPS * ops
    return {
        "cagr": cagr, "mdd": mdd, "cp": cp, "final": final,
        "rebalances_yr": rebalances / years, "trades_yr": trades / years,
        "turnover_yr_pct": turnover / years / INITIAL * 100, "years": years,
    }


def main():
    print("=== 再平衡帶寬最佳化 ===")
    df = load_prices()

    windows = []
    with_btc = df.dropna(subset=["btc_px"]).reset_index(drop=True)
    if len(with_btc) > 500:
        windows.append(("含BTC", with_btc, ASSETS))
    long_no_btc = df[df["date"] >= "2006-08-01"].reset_index(drop=True)
    windows.append(("長窗不含BTC", long_no_btc, [a for a in ASSETS if a[0] != "btc"]))

    configs = [
        ("永不再平衡", None, None),
        ("帶寬 1%", 0.01, None),
        ("帶寬 2%", 0.02, None),
        ("帶寬 3%", 0.03, None),
        ("帶寬 5%", 0.05, None),
        ("帶寬 10%", 0.10, None),
        ("季度日曆", None, 63),
        ("年度日曆", None, 252),
    ]

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "windows": {}}
    md_lines = ["# 再平衡帶寬最佳化回測\n\n",
                f"產生：{out['generated_at']}  \n",
                "組合＝allocation_targets 權重（0050代理43%/正2 12%/金12.5%/美金12.5%/SPY17%/BTC3%）；"
                "台幣計價；0050+3.5%股息、美金+1.5%利差；各資產真實成本。  \n",
                "觸發＝任一資產絕對偏離＞帶寬 → 全組回目標。  \n\n"]

    for wname, wdf, assets in windows:
        drop = wdf.dropna(subset=[f"{a}_px" for a, _, _, _ in assets]).reset_index(drop=True)
        md_lines.append(f"## {wname}（{drop['date'].iloc[0]} ~ {drop['date'].iloc[-1]}）\n\n")
        md_lines.append("| 方案 | CAGR | MDD | CP | 再平衡/年 | 換手率/年 |\n")
        md_lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |\n")
        out["windows"][wname] = {}
        print(f"\n--- {wname}（{drop['date'].iloc[0]} ~ {drop['date'].iloc[-1]}）---")
        for label, band, cal in configs:
            m = simulate(drop, assets, band=band, calendar_days=cal)
            out["windows"][wname][label] = {k: round(v, 3) for k, v in m.items()}
            md_lines.append(f"| {label} | {m['cagr']:+.2f}% | {m['mdd']:.1f}% | {m['cp']:.2f} "
                            f"| {m['rebalances_yr']:.1f} | {m['turnover_yr_pct']:.1f}% |\n")
            print(f"  {label}: CAGR {m['cagr']:+.2f}% MDD {m['mdd']:.1f}% CP {m['cp']:.2f} "
                  f"rb/yr {m['rebalances_yr']:.1f}")
        md_lines.append("\n")

    md_lines.append("## 判讀\n\n- 帶寬過窄→摩擦（黃金0.5%/邊最痛）；過寬→風控鈍化。  \n"
                    "- 實務上新錢流入會做掉大半再平衡；此回測無新錢，帶寬結論偏保守（可再寬一檔）。  \n")
    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    with open(os.path.join(out_dir, "rebalance_band_backtest.md"), "w", encoding="utf-8") as f:
        f.writelines(md_lines)
    with open(os.path.join(out_dir, "rebalance_band_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n報告：{os.path.join(out_dir, 'rebalance_band_backtest.md')}")


if __name__ == "__main__":
    main()
