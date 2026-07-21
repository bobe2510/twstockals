# -*- coding: utf-8 -*-
"""
配置權重穩健性 + 留一法（leave-one-out）分析。

回答兩個問題（不求過擬合的效率前緣，改用穩健性框架）：
  1. 現行 allocation_targets（35/12/25/17/3）在可承擔風險內是否夠好、落在穩健區間？
  2. 是否有商品風險收益比明顯差、移除後組合反而更好（→ 拖油瓶）？

各袖以「實際採用的規則」建立日報酬序列（含成本）：
  TW核心(0050代理)  買入長抱 + 3.5%/年股息
  正2(合成2x)       200MA(TAIEX)年線閘門，出場持現金(1%/年)
  美股(SPY×匯率)    200MA或12月動量閘門
  黃金(金價×匯率)   買入長抱
  美金(USDTWD)      持有美元(台幣值隨匯率) + 1.5%/年利差
  BTC(幣價×匯率)    200MA閘門
組合＝各袖日報酬加權，每季再平衡回目標權重。
滾動 5 年 cohort（每半年一個）取分布：CAGR/MDD/Sharpe/CP 的中位與 10 分位。
CP = CAGR − 0.25×|MDD|（此處不計 ops，各袖規則已內含）。

兩個宇宙：不含BTC(2004~，樣本足) / 含BTC(2014~，樣本少、信心低)。
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
DIV_TW = 0.035 / 252.0
CARRY_USD = 0.015 / 252.0
CASH_Y = 0.01 / 252.0
HORIZON = 252 * 5
COHORT_STEP = 126
REBAL = 63  # 每季再平衡
SLEEVES = ["tw", "lev", "us", "gold", "fx", "btc"]
NAMES = {"tw": "TW核心", "lev": "正2", "us": "美股", "gold": "黃金", "fx": "美金", "btc": "BTC"}
COST = {"tw": 0.001925, "lev": 0.001925, "us": 0.0007, "gold": 0.005, "fx": 0.0015, "btc": 0.0015}


def _read_csv(name, col):
    df = pd.read_csv(os.path.join(CACHE, name))
    df.columns = [c.lstrip("﻿") for c in df.columns]
    return df.rename(columns={"close": col})[["date", col]]


def build_sleeve_returns() -> pd.DataFrame:
    """回傳每個袖的『採用規則後』日報酬（欄位 r_<sleeve>），對齊日期。"""
    lev, _ = build_dataset()
    df = lev[["date", "twii_close", "ma200", "lev_open", "lev_close"]].copy()
    fx = _read_csv("USDTWD_full_history.csv", "fx")
    fx = fx[(fx["fx"] > 20) & (fx["fx"] < 45)]
    df = df.merge(_read_csv("SPY_adj_history.csv", "spy"), on="date", how="left")
    df = df.merge(fx, on="date", how="left")
    df = df.merge(_read_csv("GOLD_USD_full_history.csv", "gold"), on="date", how="left")
    df = df.merge(_read_csv("BTC-USD_adj_history.csv", "btc"), on="date", how="left")
    for c in ("spy", "fx", "gold", "btc"):
        df[c] = df[c].ffill()
    df = df.dropna(subset=["twii_close", "lev_close", "spy", "fx", "gold"]).reset_index(drop=True)

    # 台幣計價價格序列
    df["us_px"] = df["spy"] * df["fx"]
    df["gold_px"] = df["gold"] * df["fx"]
    df["btc_px"] = df["btc"] * df["fx"]

    twii = df["twii_close"].to_numpy(float)
    ma200 = df["ma200"].to_numpy(float)
    n = len(df)

    def gated_returns(px_col, gate_kind):
        """gate_kind: 'hold' | 'ma200_tw' | 'ma200_or_mom' | 'ma200_self'"""
        px = df[px_col].to_numpy(float)
        r = np.zeros(n)
        pos = 1.0  # 1=持有, 0=現金（隔日生效，避免未來函數）
        needs_self = gate_kind in ("ma200_or_mom", "ma200_self")
        self_ma200 = pd.Series(px).rolling(200).mean().to_numpy() if needs_self else None
        for i in range(1, n):
            asset_r = px[i] / px[i - 1] - 1.0 if px[i - 1] > 0 else 0.0
            r[i] = pos * asset_r + (1 - pos) * CASH_Y
            # 收盤定訊號、隔日生效
            if gate_kind == "hold":
                new = 1.0
            elif gate_kind == "ma200_tw":
                new = 1.0 if twii[i] > ma200[i] else 0.0
            elif gate_kind == "ma200_or_mom":
                mom = i >= 252 and px[i] > px[i - 252]
                new = 1.0 if (px[i] > self_ma200[i] if not math.isnan(self_ma200[i]) else False) or mom else 0.0
            elif gate_kind == "ma200_self":
                new = 1.0 if (not math.isnan(self_ma200[i]) and px[i] > self_ma200[i]) else 0.0
            else:
                new = 1.0
            # 換倉成本
            if new != pos:
                r[i] -= COST[px_col.split("_")[0]] if px_col.split("_")[0] in COST else 0.0
            pos = new
        return r

    out = pd.DataFrame({"date": df["date"]})
    # TW核心：長抱 + 股息
    tw_r = df["twii_close"].pct_change().fillna(0).to_numpy() + DIV_TW
    out["r_tw"] = tw_r
    # 正2：TAIEX 年線閘門（用實際/合成 2x 序列）
    out["r_lev"] = gated_returns("lev_close", "ma200_tw")
    # 美股：200MA或12月動量
    out["r_us"] = gated_returns("us_px", "ma200_or_mom")
    # 黃金：長抱
    out["r_gold"] = df["gold_px"].pct_change().fillna(0).to_numpy()
    # 美金：持有美元台幣值 + 利差
    out["r_fx"] = df["fx"].pct_change().fillna(0).to_numpy() + CARRY_USD
    # BTC：自身 200MA
    out["r_btc"] = gated_returns("btc_px", "ma200_self")
    out["btc_valid"] = df["btc_px"].notna() & (df["btc_px"] > 0)
    return out


def metrics_from_returns(r: np.ndarray) -> dict:
    nav = np.cumprod(1.0 + r)
    yrs = max(len(r) / 252.0, 0.1)
    cagr = (nav[-1] ** (1 / yrs) - 1) * 100
    peak = np.maximum.accumulate(nav)
    mdd = float(((nav - peak) / peak).min() * 100)
    vol = float(np.std(r) * math.sqrt(252) * 100)
    sharpe = float(np.mean(r) / np.std(r) * math.sqrt(252)) if np.std(r) > 0 else 0.0
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    cp = cagr - 0.25 * abs(mdd)
    return {"cagr": cagr, "mdd": mdd, "vol": vol, "sharpe": sharpe, "calmar": calmar, "cp": cp}


def portfolio_returns(rets: pd.DataFrame, weights: dict, i0: int, i1: int) -> np.ndarray:
    """每季再平衡回目標權重的組合日報酬。"""
    cols = [f"r_{s}" for s in weights]
    R = rets[cols].to_numpy()[i0:i1]
    w0 = np.array([weights[s] for s in weights], float)
    w0 = w0 / w0.sum()
    w = w0.copy()
    out = np.zeros(len(R))
    for t in range(len(R)):
        pr = float(np.dot(w, R[t]))
        out[t] = pr
        w = w * (1.0 + R[t])
        w = w / w.sum()
        if t % REBAL == 0:
            w = w0.copy()
    return out


def cohort_dist(rets, weights, sleeves_avail, start_i):
    idxs = list(range(start_i, len(rets) - HORIZON, COHORT_STEP))
    ms = []
    for i0 in idxs:
        r = portfolio_returns(rets, weights, i0, i0 + HORIZON)
        ms.append(metrics_from_returns(r))
    if not ms:
        return None
    agg = {}
    for k in ("cagr", "mdd", "sharpe", "cp"):
        v = np.array([m[k] for m in ms])
        agg[k + "_med"] = float(np.median(v))
        agg[k + "_p10"] = float(np.percentile(v, 10))
    agg["n_cohorts"] = len(ms)
    return agg


def main():
    print("=== 配置權重穩健性 + 留一法 ===")
    rets = build_sleeve_returns()
    d0, d1 = rets["date"].iloc[0], rets["date"].iloc[-1]
    btc_start_i = int(rets["btc_valid"].values.argmax())
    btc_start_date = rets["date"].iloc[btc_start_i]
    print(f"資料 {d0} ~ {d1}｜BTC 起 {btc_start_date}")

    # ---- 1. 各袖單獨體檢（全期，用各自可用資料） ----
    print("\n--- 各袖單獨體檢 ---")
    solo = {}
    for s in SLEEVES:
        col = f"r_{s}"
        if s == "btc":
            r = rets[col].to_numpy()[btc_start_i:]
        else:
            r = rets[col].to_numpy()
        m = metrics_from_returns(r)
        solo[s] = m
        print(f"  {NAMES[s]:5s} CAGR {m['cagr']:+6.2f}%  波動 {m['vol']:5.1f}%  MDD {m['mdd']:6.1f}%  "
              f"Sharpe {m['sharpe']:.2f}  Calmar {m['calmar']:.2f}")

    # ---- 2. 候選組合（不含BTC宇宙，big-5 正規化） ----
    big5 = ["tw", "lev", "us", "gold", "fx"]
    candidates = {
        "現行(正規化)": {"tw": 39.3, "lev": 13.5, "us": 19.1, "gold": 14.0, "fx": 14.0},
        "等權": {s: 20.0 for s in big5},
        "核心更重(防禦)": {"tw": 45, "lev": 3, "us": 27, "gold": 18, "fx": 7},
        "去正2": {"tw": 45, "lev": 0, "us": 25, "gold": 18, "fx": 12},
        "去美金": {"tw": 42, "lev": 14, "us": 22, "gold": 22, "fx": 0},
        "股債金三分": {"tw": 30, "lev": 8, "us": 25, "gold": 30, "fx": 7},
    }
    # 風險平價（逆波動）
    inv = {s: 1.0 / max(solo[s]["vol"], 1e-6) for s in big5}
    tot = sum(inv.values())
    candidates["風險平價(逆波動)"] = {s: round(inv[s] / tot * 100, 1) for s in big5}

    print("\n--- 候選組合（不含BTC，2004~，5年cohort分布）---")
    cand_res = {}
    for name, w in candidates.items():
        w2 = {s: w.get(s, 0) for s in big5 if w.get(s, 0) > 0}
        agg = cohort_dist(rets, w2, big5, 200)
        cand_res[name] = {"weights": w2, **agg}
        print(f"  {name:14s} CAGR中位 {agg['cagr_med']:+5.2f}%(10%位 {agg['cagr_p10']:+5.2f})  "
              f"MDD中位 {agg['mdd_med']:6.1f}%  CP中位 {agg['cp_med']:5.2f}  Sharpe {agg['sharpe_med']:.2f}")

    # ---- 3. 留一法（從現行正規化逐一移除） ----
    base = candidates["現行(正規化)"]
    print("\n--- 留一法（移除該袖、其餘按比例補足）---")
    loo_res = {}
    base_agg = cand_res["現行(正規化)"]
    print(f"  {'（基準）現行':14s} CP中位 {base_agg['cp_med']:5.2f}  CAGR中位 {base_agg['cagr_med']:+5.2f}%  MDD中位 {base_agg['mdd_med']:.1f}%")
    for drop in big5:
        w = {s: v for s, v in base.items() if s != drop}
        agg = cohort_dist(rets, w, big5, 200)
        loo_res[drop] = agg
        d_cp = agg["cp_med"] - base_agg["cp_med"]
        verdict = "← 移除後變好(拖累)" if d_cp > 0.05 else ("← 移除後明顯變差" if d_cp < -0.3 else "")
        print(f"  去{NAMES[drop]:12s} CP中位 {agg['cp_med']:5.2f}(Δ{d_cp:+.2f})  "
              f"CAGR {agg['cagr_med']:+5.2f}%  MDD {agg['mdd_med']:.1f}%  {verdict}")

    # ---- 4. 含BTC宇宙（信心低，僅供參考） ----
    print("\n--- 含BTC宇宙（2014~，cohort少、信心低）---")
    six_cur = {"tw": 35, "lev": 12, "us": 17, "gold": 12.5, "fx": 12.5, "btc": 3}
    six_nobtc = {"tw": 36, "lev": 12.4, "us": 17.5, "gold": 12.9, "fx": 12.9, "btc": 0}
    for name, w in [("現行含BTC3%", six_cur), ("現行去BTC", six_nobtc)]:
        w2 = {s: v for s, v in w.items() if v > 0}
        agg = cohort_dist(rets, w2, SLEEVES, btc_start_i + 200)
        if agg:
            print(f"  {name:12s} CP中位 {agg['cp_med']:5.2f}  CAGR中位 {agg['cagr_med']:+5.2f}%  "
                  f"MDD中位 {agg['mdd_med']:.1f}%  cohorts={agg['n_cohorts']}")

    # ---- 輸出報告 ----
    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "range": [d0, d1], "btc_start": btc_start_date,
        "solo": {s: {k: round(v, 3) for k, v in solo[s].items()} for s in SLEEVES},
        "candidates": {n: {k: (round(v, 3) if isinstance(v, float) else v)
                           for k, v in r.items()} for n, r in cand_res.items()},
        "leave_one_out": {NAMES[d]: {k: round(v, 3) for k, v in a.items()} for d, a in loo_res.items()},
    }
    with open(os.path.join(out_dir, "allocation_robustness_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = os.path.join(out_dir, "allocation_robustness_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 配置權重穩健性 + 留一法分析\n\n")
        f.write(f"產生：{payload['generated_at']}｜資料 `{d0}` ~ `{d1}`（BTC 起 {btc_start_date}）  \n")
        f.write("各袖用實際採用規則（正2/美股/BTC 帶趨勢閘門、0050/黃金長抱、美金含利差），"
                "含成本；每季再平衡；滾動5年cohort取中位與10分位。CP=CAGR−0.25×|MDD|。  \n\n")
        f.write("## 1. 各袖單獨體檢（風險收益比）\n\n")
        f.write("| 袖 | CAGR | 年化波動 | MDD | Sharpe | Calmar(報酬/回撤) |\n| :-- | --: | --: | --: | --: | --: |\n")
        for s in SLEEVES:
            m = solo[s]
            f.write(f"| {NAMES[s]} | {m['cagr']:+.2f}% | {m['vol']:.1f}% | {m['mdd']:.1f}% | "
                    f"{m['sharpe']:.2f} | {m['calmar']:.2f} |\n")
        f.write("\n> Calmar／Sharpe 明顯低於同儕者＝風險收益比差的候選。\n\n")
        f.write("## 2. 候選組合比較（不含BTC，2004~）\n\n")
        f.write("| 組合 | CAGR中位 | CAGR 10%位 | MDD中位 | CP中位 | Sharpe中位 |\n| :-- | --: | --: | --: | --: | --: |\n")
        for name, r in cand_res.items():
            f.write(f"| {name} | {r['cagr_med']:+.2f}% | {r['cagr_p10']:+.2f}% | {r['mdd_med']:.1f}% | "
                    f"{r['cp_med']:.2f} | {r['sharpe_med']:.2f} |\n")
        f.write("\n## 3. 留一法（從現行移除單一袖）\n\n")
        f.write(f"基準（現行正規化）CP中位 **{base_agg['cp_med']:.2f}**。\n\n")
        f.write("| 移除 | CP中位 | ΔCP | CAGR中位 | MDD中位 | 判讀 |\n| :-- | --: | --: | --: | --: | :-- |\n")
        for drop in big5:
            a = loo_res[drop]
            d_cp = a["cp_med"] - base_agg["cp_med"]
            v = "移除後變好→拖累" if d_cp > 0.05 else ("移除後明顯變差→重要" if d_cp < -0.3 else "影響不大")
            f.write(f"| 去{NAMES[drop]} | {a['cp_med']:.2f} | {d_cp:+.2f} | {a['cagr_med']:+.2f}% | {a['mdd_med']:.1f}% | {v} |\n")
        f.write("\n## 方法限制\n\n")
        f.write("- 各袖採現行採用規則，不是裸買入持有；換規則結論可能變。  \n")
        f.write("- cohort 高度重疊，獨立樣本約 4-5 段；差異在雜訊內時不宜過度解讀。  \n")
        f.write("- 未含個股殘倉（已出清）與美債（出清中，目標0）。  \n")
        f.write("- 這是穩健性檢驗，非效率前緣最佳解（後者易過擬合歷史報酬）。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
