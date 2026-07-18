# -*- coding: utf-8 -*-
"""
美股 ETF（SPY→VOO 代理／QQQ／EFA→VXUS 代理）與 BTC/ETH 的
建倉／出場規則長歷史回測（含股息調整價與真實成本）。

策略（每資產同一組）：
  A. 買入持有
  B. 評等進場、永不出場（評等只管新錢節奏）
  C. 評等進場＋破50MA出場（現行 us/crypto sell_rule）
  D. 200MA 趨勢開關（日檢）
  E. 絕對動量 12個月（月檢 on/off）
  F. 複合AND：200MA上「且」動量>0 才持有（較安全）
  G. 複合OR：200MA上「或」動量>0 即持有（較貼市）

成本：美股 ETF 0.07%/邊；幣 0.15%/邊。訊號 EOD → 隔日執行（用調整價近似）。
OOS：ETF 2016~；幣 2022~。CP = CAGR − 0.25×|MDD| − 1.5×Ops。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
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
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts", "research"))

from run_grade_threshold_backtest import (  # noqa: E402
    grade_pullback_core_i,
    grade_growth_us_i,
)

INITIAL = 1_000_000.0
LAMBDA_MDD = 0.25
LAMBDA_OPS = 1.5
EOD_OPS_WEIGHT = 0.2
WARMUP = 260
MOM_LB = 252
MOM_FREQ = 21

ASSETS = [
    # (symbol, label, cost/side, grade_kind, oos_start, note)
    ("SPY", "SPY（VOO代理）", 0.0007, "core", "2016-01-01", "1993~，含網路泡沫+GFC"),
    ("QQQ", "QQQ", 0.0007, "growth", "2016-01-01", "1999~，含 -83% 網路泡沫"),
    ("EFA", "EFA（VXUS代理）", 0.0007, "core", "2016-01-01", "2001~"),
    ("BTC-USD", "BTC", 0.0015, "core", "2022-01-01", "2014~"),
    ("ETH-USD", "ETH", 0.0015, "core", "2022-01-01", "2017~"),
]

CRISIS = [
    ("2000 網路泡沫", "2000-02-01", "2002-10-31"),
    ("2008 金融海嘯", "2007-10-01", "2009-03-31"),
    ("2020 COVID", "2020-01-01", "2020-04-30"),
    ("2022 升息年", "2022-01-01", "2022-12-31"),
    ("2025-26 回檔", "2025-01-01", "2099-12-31"),
]


def fetch_yahoo_adj(sym: str) -> pd.DataFrame:
    cache = os.path.join(WORKSPACE, "market_crawled_cache", f"{sym.replace('=','_')}_adj_history.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache)
        if (pd.Timestamp.now() - pd.Timestamp(df["date"].iloc[-1])).days <= 5:
            return df
    p2 = int(time.time())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
        f"?period1=0&period2={p2}&interval=1d&events=div%2Csplit"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    r = d["chart"]["result"][0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    tw = timezone(timedelta(hours=8))
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        a = adj[i] if adj else c
        if not c or not a or a <= 0:
            continue
        rows.append({"date": datetime.fromtimestamp(t, tw).strftime("%Y-%m-%d"), "close": a})
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    return df


def metrics(series: pd.Series, trades: int) -> dict:
    years = max(len(series) / 252.0, 0.1)
    final = float(series.iloc[-1])
    cagr = ((final / INITIAL) ** (1 / years) - 1) * 100.0
    peak = series.cummax()
    mdd = float(((series - peak) / peak * 100.0).min())
    ops = trades * EOD_OPS_WEIGHT / years
    cp = cagr - LAMBDA_MDD * abs(mdd) - LAMBDA_OPS * ops
    return {"final": final, "cagr": cagr, "mdd": mdd, "cp": cp,
            "trades": trades, "ops_yr": ops, "years": years}


def sim(closes, dates, *, entry: str, exit_rule: str, cost: float,
        grade_kind: str, start: str | None = None) -> dict:
    n = len(closes)
    ma50 = pd.Series(closes).rolling(50).mean().to_numpy()
    ma200 = pd.Series(closes).rolling(200).mean().to_numpy()
    i0 = WARMUP
    if start:
        while i0 < n and dates[i0] < start:
            i0 += 1

    cash, units = INITIAL, 0.0
    pending = None
    equity, eq_dates = [], []
    trades = 0
    mom_ok = False
    last_mom_check = -999

    for i in range(i0, n):
        px = closes[i]
        if pending == "buy" and units == 0.0:
            units = cash / (px * (1 + cost))
            cash = 0.0
            trades += 1
        elif pending == "sell" and units > 0.0:
            cash = units * px * (1 - cost)
            units = 0.0
            trades += 1
        pending = None

        equity.append(cash + units * px)
        eq_dates.append(dates[i])
        if i >= n - 1:
            continue

        if i - last_mom_check >= MOM_FREQ:
            mom_ok = i >= MOM_LB and closes[i] > closes[i - MOM_LB]
            last_mom_check = i

        above200 = not math.isnan(ma200[i]) and px > ma200[i]
        above50 = not math.isnan(ma50[i]) and px > ma50[i]

        def grade_ok():
            if grade_kind == "growth":
                g = grade_growth_us_i(closes, i)
            else:
                g = grade_pullback_core_i(closes, i, 1)
            return g in ("B", "A", "S")

        want_hold = None  # None=依 entry/exit 分開判斷
        if entry == "ma200" and exit_rule == "ma200":
            want_hold = above200
        elif entry == "mom" and exit_rule == "mom":
            want_hold = mom_ok
        elif entry == "and" and exit_rule == "and":
            want_hold = above200 and mom_ok
        elif entry == "or" and exit_rule == "or":
            want_hold = above200 or mom_ok

        if want_hold is not None:
            if want_hold and units == 0.0:
                pending = "buy"
            elif not want_hold and units > 0.0:
                pending = "sell"
            continue

        if units > 0.0:
            if exit_rule == "ma50" and not above50:
                pending = "sell"
                continue
        if units == 0.0:
            if entry == "always":
                pending = "buy"
            elif entry == "grade" and grade_ok():
                pending = "buy"

    return {"m": metrics(pd.Series(equity), trades), "eq": pd.Series(equity), "dt": eq_dates}


STRATS = {
    "A. 買入持有": dict(entry="always", exit_rule="none"),
    "B. 評等進場、永不出場": dict(entry="grade", exit_rule="none"),
    "C. 評等進場＋破50MA出場（現行）": dict(entry="grade", exit_rule="ma50"),
    "D. 200MA 趨勢開關": dict(entry="ma200", exit_rule="ma200"),
    "E. 絕對動量12月（月檢）": dict(entry="mom", exit_rule="mom"),
    "F. 複合AND（200MA且動量）": dict(entry="and", exit_rule="and"),
    "G. 複合OR（200MA或動量）": dict(entry="or", exit_rule="or"),
}


def crisis_dd(eq: pd.Series, dts, w0, w1) -> float:
    s = pd.Series(eq.values, index=pd.to_datetime(dts))
    s = s[(s.index >= w0) & (s.index <= w1)]
    if len(s) < 2:
        return float("nan")
    return float(((s - s.cummax()) / s.cummax() * 100).min())


def main():
    print("=== 美股 ETF／BTC／ETH 趨勢出場回測 ===")
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "assets": {}}
    md_lines = [
        "# 美股 ETF／BTC／ETH 建倉出場規則回測（長歷史＋調整價＋真實成本）\n\n",
        f"產生：{out['generated_at']}  \n",
        "SPY=VOO 代理（1993~）；EFA=VXUS 代理（2001~）；價格用含息調整價。  \n",
        "成本：ETF 0.07%/邊；幣 0.15%/邊。動量=12月報酬>0、每21日檢。  \n\n",
    ]

    for sym, label, cost, gkind, oos, note in ASSETS:
        df = fetch_yahoo_adj(sym)
        if df.empty or len(df) < WARMUP + 300:
            print(f"{label}: 資料不足，略過")
            continue
        closes = df["close"].to_numpy(float)
        dates = df["date"].tolist()
        print(f"\n--- {label}（{dates[0]} ~ {dates[-1]}｜{note}）---")
        md_lines.append(f"## {label}（{dates[0]} ~ {dates[-1]}）\n\n")
        md_lines.append("| 策略 | 全期CAGR | 全期MDD | 全期CP | OOS CAGR | OOS MDD | OOS CP | 交易/年 |\n")
        md_lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        res = {}
        for name, kw in STRATS.items():
            full = sim(closes, dates, cost=cost, grade_kind=gkind, **kw)
            o = sim(closes, dates, cost=cost, grade_kind=gkind, start=oos, **kw)
            res[name] = full
            mf, mo = full["m"], o["m"]
            print(f"  {name}: 全期 {mf['cagr']:+6.2f}%/{mf['mdd']:6.1f}%/CP{mf['cp']:7.2f} "
                  f"| OOS {mo['cagr']:+6.2f}%/{mo['mdd']:6.1f}%/CP{mo['cp']:7.2f}")
            md_lines.append(
                f"| {name} | {mf['cagr']:+.2f}% | {mf['mdd']:.1f}% | {mf['cp']:.2f} "
                f"| {mo['cagr']:+.2f}% | {mo['mdd']:.1f}% | {mo['cp']:.2f} "
                f"| {mf['trades']/max(mf['years'],0.1):.1f} |\n")
            out["assets"].setdefault(label, {})[name] = {
                "full": {k: round(v, 3) for k, v in mf.items()},
                "oos": {k: round(v, 3) for k, v in mo.items()},
            }
        md_lines.append("\n### 危機窗 MDD\n\n")
        names = list(STRATS.keys())
        md_lines.append("| 危機窗 | " + " | ".join(n.split("（")[0] for n in names) + " |\n")
        md_lines.append("| :--- |" + " ---: |" * len(names) + "\n")
        for clabel, w0, w1 in CRISIS:
            if w0 > dates[-1] or w1 < dates[0]:
                continue
            cells = []
            for name in names:
                v = crisis_dd(res[name]["eq"], res[name]["dt"], w0, w1)
                cells.append("—" if math.isnan(v) else f"{v:.1f}%")
            md_lines.append(f"| {clabel} | " + " | ".join(cells) + " |\n")
        md_lines.append("\n")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    md_path = os.path.join(out_dir, "trend_exit_backtest.md")
    md_lines.append("## 方法限制\n\n")
    md_lines.append("- SPY/EFA 為 VOO/VXUS 代理（同指數家族、費用略高，長歷史覆蓋 2000/2008）。  \n")
    md_lines.append("- 評等函數與現行 scan 對齊（core=拉回均線分級；growth=年線深回撤帶）。  \n")
    md_lines.append("- 幣類僅 1~2 個完整週期樣本，結論信心低於 ETF。  \n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(md_lines)
    with open(os.path.join(out_dir, "trend_exit_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)
    print(f"\n報告：{md_path}")


if __name__ == "__main__":
    main()
