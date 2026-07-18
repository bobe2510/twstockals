# -*- coding: utf-8 -*-
"""
00631L 波動率目標 (vol targeting) vs 年線開關 vs 買入持有 三方回測。

- 長歷史：Yahoo ^TWII 日線（1997-07 起），涵蓋 2000／2008／2020／2022 空頭。
- 合成 2x：實際 00631L（2014-10-31 起，1拆22 還原）之外的區間，
  以 r_syn = 2×r_TWII + alpha_daily 合成；alpha 由重疊期殘差均值校準
  （自動吸收期貨貼水收益與內扣費用）。
- 成本模型：手續費 0.1425%（買賣）＋ ETF 證交稅 0.1%（賣出）＋滑價 0.05%（單邊）。
  （注意：舊 run_etf_backtest 用 0.3% 是個股稅率；ETF 為 0.1%。）
- 訊號一律 EOD 收盤判定 → 隔日開盤執行（與現行推播流程一致）。
- 參數選擇防偷看：IS（~2015-12-31）選 CP 冠軍 → OOS（2016 起）驗證。
- CP = CAGR − 0.25×|MDD| − 1.5×WorkdayOpsPerYear（EOD 每筆 0.2 ops）。
"""
import os
import sys
import json
import time
import math
import urllib.request
from datetime import datetime, timedelta, timezone

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

LAMBDA_MDD = 0.25
LAMBDA_OPS = 1.5
EOD_OPS_WEIGHT = 0.2

COMMISSION = 0.001425
ETF_TAX = 0.001
SLIPPAGE = 0.0005

INITIAL_CASH = 1_000_000.0
IS_END = "2015-12-31"          # IS：合成時代＋ETF 前期；OOS：2016 起（多為真實 ETF）
SPLIT_DATE = "2026-03-24"      # 00631L 1拆22
SPLIT_FACTOR = 22.0

CRISIS_WINDOWS = [
    ("2000 網路泡沫", "2000-02-01", "2001-10-31"),
    ("2008 金融海嘯", "2007-10-01", "2008-12-31"),
    ("2011 歐美債危機", "2011-07-01", "2011-12-31"),
    ("2015 陸股連鎖跌", "2015-04-01", "2015-09-30"),
    ("2018 Q4 修正", "2018-10-01", "2019-01-31"),
    ("2020 COVID", "2020-01-01", "2020-04-30"),
    ("2022 升息年", "2022-01-01", "2022-11-30"),
    ("2025-26 近期回檔", "2025-01-01", "2099-12-31"),
]


# ---------------------------------------------------------------- data loading

def load_twii() -> pd.DataFrame:
    """Yahoo ^TWII 全期日線；快取 csv，末日距今 >3 個交易日則重抓。"""
    cache = os.path.join(WORKSPACE, "market_crawled_cache", "TWII_long_history.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache)
        last = pd.Timestamp(df["date"].iloc[-1])
        if (pd.Timestamp.now() - last).days <= 5:
            print(f"載入 TWII 快取（{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}，{len(df)} 筆）")
            return df

    print("自 Yahoo 下載 ^TWII 全期日線...")
    p2 = int(time.time())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII"
        f"?period1=0&period2={p2}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    r = d["chart"]["result"][0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    tw = timezone(timedelta(hours=8))
    rows = []
    for i, t in enumerate(ts):
        c, o = q["close"][i], q["open"][i]
        if c is None:
            continue
        rows.append({
            "date": datetime.fromtimestamp(t, tw).strftime("%Y-%m-%d"),
            "open": o if o else c,
            "close": c,
        })
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    print(f"TWII 下載完成：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}，{len(df)} 筆")
    return df


def load_lev_actual() -> pd.DataFrame:
    path = os.path.join(WORKSPACE, "market_crawled_cache", "00631L_full_history.csv")
    df = pd.read_csv(path).sort_values("date").reset_index(drop=True)
    mask = df["date"] <= SPLIT_DATE
    df.loc[mask, "open"] = df.loc[mask, "open"] / SPLIT_FACTOR
    df.loc[mask, "close"] = df.loc[mask, "close"] / SPLIT_FACTOR
    return df[["date", "open", "close"]]


def build_dataset() -> tuple[pd.DataFrame, dict]:
    """以 TWII 交易日為主軸，拼接實際 00631L 與合成 2x。"""
    twii = load_twii()
    lev = load_lev_actual()

    df = twii.rename(columns={"open": "twii_open", "close": "twii_close"})
    df["ret"] = df["twii_close"].pct_change()

    # 指數不可能超過漲跌停（7%／2015-06 後 10%）；異常值視為壞資料截斷
    bad = df["ret"].abs() > 0.105
    n_bad = int(bad.sum())
    df.loc[bad, "ret"] = df.loc[bad, "ret"].clip(-0.10, 0.10)

    lev = lev.rename(columns={"open": "lev_open_act", "close": "lev_close_act"})
    df = df.merge(lev, on="date", how="left")

    # --- alpha 校準（重疊期：實際 00631L 日報酬 − 2×TWII 日報酬 的殘差均值）
    ov = df.dropna(subset=["lev_close_act"]).copy()
    ov["lev_ret"] = ov["lev_close_act"].pct_change()
    ov = ov.dropna(subset=["lev_ret", "ret"])
    resid = ov["lev_ret"] - 2.0 * ov["ret"]
    alpha_daily = float(resid.mean())
    beta_fit = float(np.polyfit(ov["ret"], ov["lev_ret"], 1)[0])
    corr = float(np.corrcoef(2.0 * ov["ret"], ov["lev_ret"])[0, 1])

    # --- 合成驗證：從實際起點用 2x+alpha 重建，比對終值
    syn_val = 1.0
    for _, row in ov.iterrows():
        syn_val *= 1.0 + 2.0 * row["ret"] + alpha_daily
    syn_terminal_ratio = syn_val / (ov["lev_close_act"].iloc[-1] / ov["lev_close_act"].iloc[0])

    # --- 拼接：實際區間用實際報酬，其餘用合成報酬
    n = len(df)
    lev_close = np.full(n, np.nan)
    lev_open = np.full(n, np.nan)
    is_syn = np.zeros(n, dtype=bool)

    act_close = df["lev_close_act"].to_numpy()
    act_open = df["lev_open_act"].to_numpy()
    twii_close = df["twii_close"].to_numpy()
    twii_open = df["twii_open"].to_numpy()
    ret = df["ret"].to_numpy()

    first_act = int(np.argmax(~np.isnan(act_close)))
    # 實際區間直接放
    for i in range(n):
        if not math.isnan(act_close[i]):
            lev_close[i] = act_close[i]
            lev_open[i] = act_open[i]
    # 往前合成（backward）
    for i in range(first_act - 1, -1, -1):
        nxt = lev_close[i + 1] if not math.isnan(lev_close[i + 1]) else None
        r_nxt = ret[i + 1]
        if nxt is None or math.isnan(r_nxt):
            lev_close[i] = lev_close[i + 1]
        else:
            lev_close[i] = nxt / (1.0 + 2.0 * r_nxt + alpha_daily)
        is_syn[i] = True
    # 中段／尾段缺值往後合成（forward）
    for i in range(first_act, n):
        if math.isnan(lev_close[i]):
            r_i = ret[i] if not math.isnan(ret[i]) else 0.0
            lev_close[i] = lev_close[i - 1] * (1.0 + 2.0 * r_i + alpha_daily)
            is_syn[i] = True
    # 合成開盤：以 2x 隔夜報酬近似
    for i in range(n):
        if math.isnan(lev_open[i]):
            if i == 0 or math.isnan(twii_close[i - 1]):
                lev_open[i] = lev_close[i]
            else:
                overnight = twii_open[i] / twii_close[i - 1] - 1.0
                lev_open[i] = lev_close[i - 1] * (1.0 + 2.0 * overnight)

    df["lev_close"] = lev_close
    df["lev_open"] = lev_open
    df["is_syn"] = is_syn

    df["ma200"] = df["twii_close"].rolling(200).mean()
    for lb in (20, 60):
        df[f"vol{lb}"] = df["ret"].rolling(lb).std() * math.sqrt(252)

    df = df.dropna(subset=["ma200", "vol60", "lev_close"]).reset_index(drop=True)

    calib = {
        "alpha_daily": alpha_daily,
        "alpha_annual_pct": alpha_daily * 252 * 100,
        "beta_fit": beta_fit,
        "corr_2x": corr,
        "overlap_days": int(len(ov)),
        "syn_terminal_ratio": float(syn_terminal_ratio),
        "n_ret_clipped": n_bad,
        "synthetic_days": int(df["is_syn"].sum()),
        "actual_days": int((~df["is_syn"]).sum()),
    }
    return df, calib


# ---------------------------------------------------------------- simulation

def simulate(df: pd.DataFrame, target_w, band: float, freq: int,
             start: str = None, end: str = None) -> tuple[pd.Series, list, int]:
    """
    通用引擎：收盤算目標權重 w*∈[0,1] → 隔日開盤調整。
    target_w(row_index) -> float；band：|w*−目前w| 超過才交易；freq：每 N 個交易日才檢查訊號。
    回傳 (equity, dates, trades)。
    """
    idx = df.index
    if start:
        idx = idx[df["date"] >= start]
    if end:
        idx = idx[df["date"] <= end]
    idx = list(idx)
    if not idx:
        return pd.Series(dtype=float), [], 0

    cash, shares = INITIAL_CASH, 0.0
    pending = None
    equity, dates = [], []
    trades = 0

    for k, i in enumerate(idx):
        o = df.at[i, "lev_open"]
        c = df.at[i, "lev_close"]

        # 1) 開盤執行昨日訊號
        if pending is not None and o > 0:
            port = cash + shares * o
            tgt_shares = pending * port / o
            delta = tgt_shares - shares
            if delta > 0:
                buy_cost_rate = 1.0 + COMMISSION + SLIPPAGE
                notional = min(delta * o * buy_cost_rate, cash)
                if notional > port * 0.001:
                    add = notional / (o * buy_cost_rate)
                    shares += add
                    cash -= notional
                    trades += 1
            elif delta < 0:
                notional = -delta * o
                if notional > port * 0.001:
                    cash += notional * (1.0 - COMMISSION - ETF_TAX - SLIPPAGE)
                    shares += delta
                    trades += 1
            pending = None

        # 2) 收盤估值＋產生明日訊號
        port = cash + shares * c
        equity.append(port)
        dates.append(df.at[i, "date"])

        if k % freq == 0 and k < len(idx) - 1:
            w_now = shares * c / port if port > 0 else 0.0
            w_star = min(max(target_w(i), 0.0), 1.0)
            if abs(w_star - w_now) > band:
                pending = w_star

    return pd.Series(equity), dates, trades


def metrics(series: pd.Series, trades: int) -> dict:
    if len(series) < 2:
        return {"cagr": 0, "mdd": 0, "sharpe": 0, "cp": -999, "final": 0,
                "trades": trades, "ops_yr": 0, "years": 0}
    years = len(series) / 252.0
    final = float(series.iloc[-1])
    cagr = ((final / INITIAL_CASH) ** (1 / years) - 1) * 100.0
    peak = series.cummax()
    mdd = float(((series - peak) / peak * 100.0).min())
    dr = series.pct_change().dropna()
    sharpe = float(dr.mean() / dr.std() * math.sqrt(252)) if dr.std() > 0 else 0.0
    ops = trades * EOD_OPS_WEIGHT / years
    cp = cagr - LAMBDA_MDD * abs(mdd) - LAMBDA_OPS * ops
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe, "cp": cp, "final": final,
            "trades": trades, "ops_yr": ops, "years": years}


def crisis_dd(series: pd.Series, dates: list, w0: str, w1: str) -> float:
    s = pd.Series(series.values, index=pd.to_datetime(dates))
    s = s[(s.index >= w0) & (s.index <= w1)]
    if len(s) < 2:
        return float("nan")
    peak = s.cummax()
    return float(((s - peak) / peak * 100.0).min())


# ---------------------------------------------------------------- strategies

def make_voltarget(df, tv, lb):
    col = f"vol{lb}"
    def f(i):
        v = df.at[i, col]
        if not v or math.isnan(v) or v <= 0:
            return 0.0
        return tv / (2.0 * v)
    return f


def make_ma200(df):
    def f(i):
        return 1.0 if df.at[i, "twii_close"] > df.at[i, "ma200"] else 0.0
    return f


def make_voltarget_ma200(df, tv, lb):
    vt = make_voltarget(df, tv, lb)
    def f(i):
        if df.at[i, "twii_close"] <= df.at[i, "ma200"]:
            return 0.0
        return vt(i)
    return f


def make_bh():
    return lambda i: 1.0


# ---------------------------------------------------------------- main

def main():
    print("=" * 60)
    print("  [Backtest] 00631L Vol-Targeting vs 200MA vs B&H")
    print("=" * 60)

    df, calib = build_dataset()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]
    print(f"回測區間：{d0} ~ {d1}（{len(df)} 交易日，約 {len(df)/252:.1f} 年）")
    print(f"合成天數 {calib['synthetic_days']}｜實際天數 {calib['actual_days']}")
    print(f"alpha 年化 {calib['alpha_annual_pct']:+.2f}%｜beta {calib['beta_fit']:.3f}｜"
          f"corr {calib['corr_2x']:.4f}｜合成/實際終值比 {calib['syn_terminal_ratio']:.3f}")

    # ---- IS 網格選參（只用 vol-target 家族）
    grid = []
    for tv in (0.10, 0.15, 0.20, 0.25):
        for lb in (20, 60):
            for band in (0.10, 0.20):
                for freq in (1, 5):
                    eq, dt, tr = simulate(df, make_voltarget(df, tv, lb), band, freq, end=IS_END)
                    m = metrics(eq, tr)
                    grid.append({"tv": tv, "lb": lb, "band": band, "freq": freq, **m})
    grid.sort(key=lambda x: x["cp"], reverse=True)
    champ = grid[0]
    print(f"\nIS 冠軍參數：目標波動 {champ['tv']:.0%}｜lookback {champ['lb']}d｜"
          f"band {champ['band']:.0%}｜檢查頻率 {champ['freq']}d（IS CP {champ['cp']:.2f}）")

    tv, lb, band, freq = champ["tv"], champ["lb"], champ["band"], champ["freq"]

    # ---- 三方＋輔助策略：全期 / IS / OOS
    strategies = {
        "00631L 買入持有": (make_bh(), 0.05, 1),
        "00631L × 200MA 年線開關": (make_ma200(df), 0.05, 1),
        f"Vol-Target {tv:.0%}（{lb}d, band{band:.0%}, 每{freq}日檢）": (
            make_voltarget(df, tv, lb), band, freq),
        f"Vol-Target {tv:.0%} + 200MA 濾網": (
            make_voltarget_ma200(df, tv, lb), band, freq),
    }

    results = {}
    for name, (fn, b, fq) in strategies.items():
        eq_full, dt_full, tr_full = simulate(df, fn, b, fq)
        eq_is, _, tr_is = simulate(df, fn, b, fq, end=IS_END)
        eq_oos, _, tr_oos = simulate(df, fn, b, fq, start="2016-01-01")
        results[name] = {
            "full": metrics(eq_full, tr_full),
            "is": metrics(eq_is, tr_is),
            "oos": metrics(eq_oos, tr_oos),
            "eq_full": eq_full, "dt_full": dt_full,
        }

    # TAIEX 1x 基準（無成本近似）
    base = df["twii_close"] / df["twii_close"].iloc[0] * INITIAL_CASH
    results["大盤 1x 基準（參考）"] = {
        "full": metrics(pd.Series(base.values), 0),
        "is": metrics(pd.Series(base[df["date"] <= IS_END].values), 0),
        "oos": metrics(pd.Series((base[df["date"] >= "2016-01-01"]
                                  / base[df["date"] >= "2016-01-01"].iloc[0]
                                  * INITIAL_CASH).values), 0),
        "eq_full": pd.Series(base.values), "dt_full": list(df["date"]),
    }

    # ---- 風險對照前緣：不同目標波動下的 CAGR vs MDD（lb=60, band=10%, 每日檢）
    frontier = []
    for ftv in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35):
        for combo in (False, True):
            fn = make_voltarget_ma200(df, ftv, 60) if combo else make_voltarget(df, ftv, 60)
            eq_f, _, tr_f = simulate(df, fn, 0.10, 1)
            eq_fo, _, tr_fo = simulate(df, fn, 0.10, 1, start="2016-01-01")
            frontier.append({"tv": ftv, "combo": combo,
                             "full": metrics(eq_f, tr_f), "oos": metrics(eq_fo, tr_fo)})

    # ---- 危機窗 MDD
    crisis_rows = []
    for label, w0, w1 in CRISIS_WINDOWS:
        row = {"window": label, "range": f"{w0}~{min(w1, d1)}"}
        for name, r in results.items():
            row[name] = crisis_dd(r["eq_full"], r["dt_full"], w0, w1)
        crisis_rows.append(row)

    # ---- 目前建議曝險（最新收盤）
    i_last = df.index[-1]
    v_now = df.at[i_last, f"vol{lb}"]
    w_now = min(max(tv / (2.0 * v_now), 0.0), 1.0) if v_now > 0 else 0.0
    above200 = bool(df.at[i_last, "twii_close"] > df.at[i_last, "ma200"])

    # ---- 輸出
    print("\n" + "=" * 60)
    print("  [Result] 全期（含合成 1998~）三方對比")
    print("=" * 60)
    for name, r in results.items():
        m = r["full"]
        print(f"{name}: CP {m['cp']:.2f} | CAGR {m['cagr']:.2f}% | MDD {m['mdd']:.2f}% "
              f"| Sharpe {m['sharpe']:.2f} | Ops/yr {m['ops_yr']:.2f}")

    report_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    os.makedirs(report_dir, exist_ok=True)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "range": [d0, d1],
        "is_end": IS_END,
        "costs": {"commission": COMMISSION, "etf_tax": ETF_TAX, "slippage": SLIPPAGE},
        "calibration": calib,
        "champion": {k: champ[k] for k in ("tv", "lb", "band", "freq", "cp", "cagr", "mdd")},
        "grid_top10": [{k: g[k] for k in ("tv", "lb", "band", "freq", "cp", "cagr", "mdd", "ops_yr")}
                       for g in grid[:10]],
        "results": {
            name: {per: {k: round(v, 3) for k, v in r[per].items() if k not in ()}
                   for per in ("full", "is", "oos")}
            for name, r in results.items()
        },
        "crisis_mdd": crisis_rows,
        "frontier": [
            {"tv": fr["tv"], "combo": fr["combo"],
             "full": {k: round(v, 3) for k, v in fr["full"].items()},
             "oos": {k: round(v, 3) for k, v in fr["oos"].items()}}
            for fr in frontier
        ],
        "current_suggestion": {
            "vol_now_pct": round(v_now * 100, 1),
            "voltarget_weight": round(w_now, 3),
            "above_200ma": above200,
        },
    }
    json_path = os.path.join(report_dir, "voltarget_00631L_backtest.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=float)

    md_path = os.path.join(report_dir, "voltarget_00631L_backtest.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 00631L 波動率目標回測（合成 2x 長歷史＋成本模型）\n\n")
        f.write(f"產生：{payload['generated_at']}｜區間 `{d0}` ~ `{d1}`"
                f"（約 {len(df)/252:.1f} 年；合成 {calib['synthetic_days']} 日＋實際 {calib['actual_days']} 日）  \n")
        f.write(f"成本：手續費 {COMMISSION:.4%}｜ETF 證交稅 {ETF_TAX:.2%}（賣出）｜滑價 {SLIPPAGE:.2%}"
                f"（舊 ETF 回測誤用個股稅率 0.3%，本回測改用 ETF 0.1%）  \n")
        f.write(f"合成校準：alpha 年化 **{calib['alpha_annual_pct']:+.2f}%**（期貨貼水收益−內扣）｜"
                f"beta {calib['beta_fit']:.3f}｜與 2×TWII 相關 {calib['corr_2x']:.4f}｜"
                f"重疊期合成/實際終值比 **{calib['syn_terminal_ratio']:.3f}**  \n")
        f.write(f"訊號：EOD 收盤判定 → 隔日開盤執行。IS（~{IS_END}）選參 → OOS（2016~）驗證。  \n\n")

        f.write(f"**IS 冠軍參數：目標年化波動 {tv:.0%}｜實現波動 lookback {lb} 日｜"
                f"再平衡帶 {band:.0%}｜每 {freq} 交易日檢查**  \n\n")

        for per, label in (("full", f"全期 {d0[:4]}~{d1[:4]}"), ("is", f"IS（~{IS_END[:4]}）"),
                           ("oos", "OOS（2016~）")):
            f.write(f"## {label}\n\n")
            f.write("| 策略 | CAGR | MDD | Sharpe | 年化Ops | CP |\n")
            f.write("| :--- | ---: | ---: | ---: | ---: | ---: |\n")
            ranked = sorted(results.items(), key=lambda kv: kv[1][per]["cp"], reverse=True)
            for name, r in ranked:
                m = r[per]
                f.write(f"| {name} | {m['cagr']:+.2f}% | {m['mdd']:.2f}% | {m['sharpe']:.2f} "
                        f"| {m['ops_yr']:.2f} | **{m['cp']:.2f}** |\n")
            f.write("\n")

        f.write("## 危機窗最大回撤對比\n\n")
        names = list(results.keys())
        f.write("| 危機窗 | " + " | ".join(names) + " |\n")
        f.write("| :--- |" + " ---: |" * len(names) + "\n")
        for row in crisis_rows:
            cells = " | ".join(
                f"{row[n]:.1f}%" if isinstance(row[n], float) and not math.isnan(row[n]) else "—"
                for n in names)
            f.write(f"| {row['window']}（{row['range'][:7]}） | {cells} |\n")

        f.write("\n## 風險對照前緣：目標波動 vs 200MA（lb=60, band=10%）\n\n")
        f.write("要回答「同風險下能否更高報酬」：找 MDD 與 200MA 相近的目標波動檔位，比 CAGR。  \n\n")
        f.write("| 策略檔位 | 全期 CAGR | 全期 MDD | 全期 CP | OOS CAGR | OOS MDD | OOS CP |\n")
        f.write("| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for fr in frontier:
            mf, mo = fr["full"], fr["oos"]
            label = f"VT {fr['tv']:.0%}" + ("＋200MA濾網" if fr["combo"] else "")
            f.write(f"| {label} | {mf['cagr']:+.2f}% | {mf['mdd']:.2f}% | {mf['cp']:.2f} "
                    f"| {mo['cagr']:+.2f}% | {mo['mdd']:.2f}% | {mo['cp']:.2f} |\n")
        m200f = results["00631L × 200MA 年線開關"]["full"]
        m200o = results["00631L × 200MA 年線開關"]["oos"]
        mbhf = results["00631L 買入持有"]["full"]
        mbho = results["00631L 買入持有"]["oos"]
        f.write(f"| （對照）200MA 開關 | {m200f['cagr']:+.2f}% | {m200f['mdd']:.2f}% | {m200f['cp']:.2f} "
                f"| {m200o['cagr']:+.2f}% | {m200o['mdd']:.2f}% | {m200o['cp']:.2f} |\n")
        f.write(f"| （對照）買入持有 | {mbhf['cagr']:+.2f}% | {mbhf['mdd']:.2f}% | {mbhf['cp']:.2f} "
                f"| {mbho['cagr']:+.2f}% | {mbho['mdd']:.2f}% | {mbho['cp']:.2f} |\n")

        f.write("\n## IS 參數敏感度（Top 10 / 共 %d 組）\n\n" % len(grid))
        f.write("| 目標波動 | lookback | band | 檢查頻率 | IS CP | CAGR | MDD | Ops/yr |\n")
        f.write("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for g in grid[:10]:
            f.write(f"| {g['tv']:.0%} | {g['lb']}d | {g['band']:.0%} | {g['freq']}d "
                    f"| **{g['cp']:.2f}** | {g['cagr']:+.2f}% | {g['mdd']:.2f}% | {g['ops_yr']:.2f} |\n")

        f.write(f"\n## 目前狀態（{d1}）\n\n")
        f.write(f"- 大盤 {lb} 日實現波動（年化）：**{v_now*100:.1f}%**  \n")
        f.write(f"- Vol-target 建議正2權重：**{w_now:.0%}**（其餘現金）  \n")
        f.write(f"- 大盤在年線之{'上' if above200 else '下'}  \n")

        f.write("\n## 方法限制（誠實揭露）\n\n")
        f.write("- 合成 2x 以 **TWII 價格指數**（不含息）＋校準 alpha 近似；00631L 實際追蹤台灣50指數，"
                "訊號與合成都用 TWII（與現行 macro_level 用大盤一致）。  \n")
        f.write("- 1998~2014 合成段假設現代期貨市場結構存在，成本以現行 ETF 費率估。  \n")
        f.write(f"- TWII 原始資料異常日報酬截斷 {calib['n_ret_clipped']} 筆（|r|>10.5%）。  \n")
        f.write("- IS 冠軍為 32 組網格挑選，仍有選擇偏誤；請以 OOS 段與敏感度表為主要判讀依據。  \n")

    print(f"\n報告：{md_path}")
    print(f"JSON：{json_path}")


if __name__ == "__main__":
    main()
