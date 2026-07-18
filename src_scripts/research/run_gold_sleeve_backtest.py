# -*- coding: utf-8 -*-
"""
黃金袖回測：擇時 vs 配置（DCA／買後長抱）對比，含台銀存摺價差成本。

問題：評等門檻回測顯示黃金擇時（評等分批＋站回50MA減）遠輸 B&H。
本回測拆解「輸在哪」：進場規則的問題，還是出場規則的問題？

策略：
  A. 單筆買入持有（B&H）
  B. 定期定額 24 個月後長抱（DCA）
  C. 現行擇時：評等分批進場 ＋ 金價站回 50MA 全數出場（對齊 scan_multi_asset）
  D. 評等分批進場、永不出場（用評等只決定「何時投入新錢」）
  E. 樸素逢低：金價 < 200MA 就分批買、永不出場（對照：評等有沒有比無腦逢低強）

成本：台銀黃金存摺買賣價差 ~0.5%/邊（來回 1%）。
資料：Yahoo GC=F（美元金價）× USDTWD=X 換算台幣/克；max 歷史，快取。
評測窗：全期／10年／5年。CP = CAGR − 0.25×|MDD| − 1.5×Ops。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
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

from run_grade_threshold_backtest import grade_gold_i  # noqa: E402  對齊現行評等

INITIAL = 600_000.0          # 黃金袖預算（對齊 grade_buy_policy GOLD.budget_twd）
SPREAD = 0.005               # 台銀存摺單邊 ~0.5%
TRANCHE_FRAC = 0.4           # 每筆 24萬/60萬（對齊現行 B/A/S 各 24 萬）
OZ_TO_GRAM = 31.1034768
LAMBDA_MDD = 0.25
LAMBDA_OPS = 1.5
EOD_OPS_WEIGHT = 0.2
WARMUP = 200


def fetch_yahoo_max(sym: str, cache_name: str) -> pd.DataFrame:
    cache = os.path.join(WORKSPACE, "market_crawled_cache", cache_name)
    if os.path.exists(cache):
        df = pd.read_csv(cache)
        if (pd.Timestamp.now() - pd.Timestamp(df["date"].iloc[-1])).days <= 5:
            return df
    p2 = int(time.time())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
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
        c = q["close"][i]
        if c is None or c <= 0:
            continue
        rows.append({"date": datetime.fromtimestamp(t, tw).strftime("%Y-%m-%d"), "close": c})
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    return df


import urllib.parse  # noqa: E402


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


def simulate(kind: str, bot: np.ndarray, gold: np.ndarray, fx: np.ndarray) -> dict:
    """kind: bh | dca | grade_ma50 | grade_hold | dip200_hold"""
    n = len(bot)
    cash, units = INITIAL, 0.0
    invested = 0.0
    trades = buys = 0
    last_buy = -999
    equity = []
    frac_sum = 0.0

    def buy(amount: float, px: float):
        nonlocal cash, units, invested, trades, buys, last_buy
        amount = min(amount, cash)
        if amount < 1_000:
            return
        units += amount / (px * (1 + SPREAD))
        cash -= amount
        invested += amount
        trades += 1
        buys += 1

    for i in range(n):
        px = float(bot[i])
        port = cash + units * px
        equity.append(port)
        frac_sum += (units * px) / port if port > 0 else 0
        if i < WARMUP or i >= n - 1:
            continue
        pxn = float(bot[i + 1])

        if kind == "bh":
            if i == WARMUP:
                buy(cash, pxn)
        elif kind == "dca":
            if (i - WARMUP) % 21 == 0 and (i - WARMUP) // 21 < 24:
                buy(INITIAL / 24.0, pxn)
        elif kind in ("grade_ma50", "grade_hold"):
            g = grade_gold_i(gold, fx, i)
            if kind == "grade_ma50" and units > 0:
                ma50 = float(np.mean(gold[i - 49 : i + 1]))
                if float(gold[i]) > ma50:
                    cash += units * pxn * (1 - SPREAD)
                    units = 0.0
                    invested = 0.0
                    trades += 1
                    continue
            if g in ("B", "A", "S") and invested < INITIAL - 1_000:
                if i - last_buy >= 5 or units == 0:
                    buy(TRANCHE_FRAC * INITIAL, pxn)
                    last_buy = i
        elif kind == "dip200_hold":
            ma200 = float(np.mean(gold[i - 199 : i + 1]))
            if float(gold[i]) < ma200 and invested < INITIAL - 1_000:
                if i - last_buy >= 5 or units == 0:
                    buy(TRANCHE_FRAC * INITIAL, pxn)
                    last_buy = i

    eq = pd.Series(equity[WARMUP:], dtype=float)
    m = metrics(eq, trades)
    m["buys"] = buys
    m["avg_invested_pct"] = round(100.0 * frac_sum / n, 1)
    return m


NAMES = {
    "bh": "A. 單筆買入持有",
    "dca": "B. 定期定額24月後長抱",
    "grade_ma50": "C. 現行擇時（評等分批＋站回50MA出場）",
    "grade_hold": "D. 評等分批進場、永不出場",
    "dip200_hold": "E. 樸素<200MA分批、永不出場",
}


def main():
    print("=== 黃金袖回測：擇時 vs 配置（含 0.5%/邊價差）===")
    gold_df = fetch_yahoo_max("GC=F", "GOLD_USD_full_history.csv")
    fx_df = fetch_yahoo_max("USDTWD=X", "USDTWD_full_history.csv")
    df = gold_df.rename(columns={"close": "gold"}).merge(
        fx_df.rename(columns={"close": "fx"}), on="date", how="inner"
    )
    df = df.sort_values("date").reset_index(drop=True)
    # 匯率壞點防呆（Yahoo TWD 偶有 0.03 之類壞值）
    df = df[(df["fx"] > 20) & (df["fx"] < 45)].reset_index(drop=True)
    df["bot"] = df["gold"] * df["fx"] / OZ_TO_GRAM
    print(f"資料：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}（{len(df)} 交易日）")

    windows = [("全期", None), ("10年", 10), ("5年", 5)]
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "spread_per_side": SPREAD, "initial": INITIAL,
           "range": [df["date"].iloc[0], df["date"].iloc[-1]],
           "windows": {}}

    for wname, yrs in windows:
        sub = df
        if yrs:
            end = pd.to_datetime(df["date"].iloc[-1])
            start = (end - timedelta(days=int(365.25 * yrs))).strftime("%Y-%m-%d")
            idx = df.index[df["date"] >= start]
            i0 = max(int(idx[0]) - WARMUP, 0) if len(idx) else 0
            sub = df.iloc[i0:].reset_index(drop=True)
        bot = sub["bot"].to_numpy(float)
        gold = sub["gold"].to_numpy(float)
        fx = sub["fx"].to_numpy(float)
        if len(sub) < WARMUP + 260:
            continue
        res = {}
        print(f"\n--- {wname}（{sub['date'].iloc[WARMUP]} ~ {sub['date'].iloc[-1]}）---")
        for kind, name in NAMES.items():
            m = simulate(kind, bot, gold, fx)
            res[kind] = m
            print(f"  {name}: 終值 {m['final']/1e4:6.1f}萬  CAGR {m['cagr']:+6.2f}%  "
                  f"MDD {m['mdd']:6.1f}%  CP {m['cp']:6.2f}  買{m['buys']}次  "
                  f"平均投入 {m['avg_invested_pct']}%")
        out["windows"][wname] = {
            "start": sub["date"].iloc[WARMUP], "end": sub["date"].iloc[-1],
            "results": {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in res.items()},
        }

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "gold_sleeve_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    md = os.path.join(out_dir, "gold_sleeve_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 黃金袖回測：擇時 vs 配置（含台銀價差 0.5%/邊）\n\n")
        f.write(f"產生：{out['generated_at']}｜資料 `{out['range'][0]}` ~ `{out['range'][1]}`"
                f"（GC=F × USDTWD 換算台幣/克）  \n")
        f.write(f"袖口預算 {INITIAL/1e4:.0f} 萬；分批每筆 {TRANCHE_FRAC:.0%}"
                "（對齊現行 grade_buy_policy 黃金 24萬/60萬）。  \n")
        f.write("目的：拆解黃金擇時輸 B&H 的原因——是「評等進場」的錯，還是「站回50MA出場」的錯。  \n\n")
        for wname, w in out["windows"].items():
            f.write(f"## {wname}（{w['start']} ~ {w['end']}）\n\n")
            f.write("| 策略 | 終值 | CAGR | MDD | CP | 買次 | 平均投入% |\n")
            f.write("| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
            ranked = sorted(w["results"].items(), key=lambda kv: kv[1]["final"], reverse=True)
            for k, m in ranked:
                f.write(f"| {NAMES[k]} | {m['final']/1e4:.1f}萬 | {m['cagr']:+.2f}% "
                        f"| {m['mdd']:.1f}% | {m['cp']:.2f} | {m['buys']} "
                        f"| {m['avg_invested_pct']} |\n")
            f.write("\n")
        f.write("## 判讀\n\n")
        f.write("- C vs D 的差距＝**出場規則（站回50MA）**造成的損失。  \n")
        f.write("- D vs E 的差距＝**評等進場**相對無腦逢低的增量。  \n")
        f.write("- B/D/E vs A 的差距＝分批（持有現金期）的機會成本；黃金多頭中通常 A 最高，"
                "但 MDD 與心理成本不同。  \n")
        f.write("- 現金閒置以 0% 計；若計入活存/美金利息，分批策略會略好一點。  \n")
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
