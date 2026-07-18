# -*- coding: utf-8 -*-
"""
0050／00631L 出場規則拆解回測（27 年 TWII 長歷史＋真實成本）。

黃金袖回測證實「站回50MA出場」毀滅價值後，用同方法檢驗台股兩袖的出場規則：

0050（以 TWII 1x 代理，持有期間另加估計股息）：
  A. 買入持有
  B. 評等B+進場、永不出場（評等只管進場節奏）
  C. 現行：評等B+進場 ＋ 破10MA出場
  D. 200MA 開關（無評等）
  E. 評等B+進場 ＋ 只破200MA出場（砍10MA、留崩盤保險）

00631L（合成+實際 2x，沿用 run_voltarget_backtest 資料）：
  L1. 200MA 開關（主規則，已驗證）
  L2. 現行合併：破200MA「或」破10MA出場、站回年線且評等允許再進

成本：台股 ETF 買 0.1925%（手續費+滑價）／賣 0.2925%（另加 0.1% 稅）。
訊號 EOD 收盤 → 隔日開盤執行。CP = CAGR − 0.25×|MDD| − 1.5×Ops。
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

from run_voltarget_backtest import build_dataset, metrics, INITIAL_CASH  # noqa: E402
from run_grade_threshold_backtest import (  # noqa: E402
    grade_pullback_core_i,
    macro_level_from,
)

BUY_C = 0.001925    # 手續費 0.1425% + 滑價 0.05%
SELL_C = 0.002925   # + ETF 稅 0.1%
DIV_YIELD_DAILY = 0.035 / 252.0  # 0050 估計年股息 3.5%（TWII 為價格指數，持有時補回）

CRISIS = [
    ("2000 網路泡沫", "2000-02-01", "2001-10-31"),
    ("2008 金融海嘯", "2007-10-01", "2008-12-31"),
    ("2020 COVID", "2020-01-01", "2020-04-30"),
    ("2022 升息年", "2022-01-01", "2022-11-30"),
    ("2025-26 回檔", "2025-01-01", "2099-12-31"),
]


def sim(df, *, asset: str, entry: str, exit_rule: str, start=None) -> dict:
    """
    asset: '1x'（TWII＋股息）| 'lev'（正2序列）
    entry: 'always' | 'grade'（B+）| 'ma200'
    exit_rule: 'none' | 'ma10' | 'ma200' | 'ma200_or_ma10'
    """
    idx = list(df.index if start is None else df.index[df["date"] >= start])
    twii = df["twii_close"].to_numpy(float)
    ma200 = df["ma200"].to_numpy(float)
    if asset == "lev":
        px_open = df["lev_open"].to_numpy(float)
        px_close = df["lev_close"].to_numpy(float)
    else:
        px_open = df["twii_open"].to_numpy(float)
        px_close = twii

    ma10 = pd.Series(px_close).rolling(10).mean().to_numpy()

    cash, shares = INITIAL_CASH, 0.0
    pending = None  # 'buy' | 'sell'
    equity, dates = [], []
    trades = 0

    for k, i in enumerate(idx):
        o = px_open[i]
        if pending == "buy" and shares == 0.0 and o > 0:
            shares = cash / (o * (1 + BUY_C))
            cash = 0.0
            trades += 1
        elif pending == "sell" and shares > 0.0 and o > 0:
            cash = shares * o * (1 - SELL_C)
            shares = 0.0
            trades += 1
        pending = None

        # 1x 持有時補股息（現金再投入近似：直接增值）
        if asset == "1x" and shares > 0:
            shares *= 1.0 + DIV_YIELD_DAILY

        c = px_close[i]
        equity.append(cash + shares * c)
        dates.append(df.at[i, "date"])
        if k >= len(idx) - 1:
            continue

        # —— EOD 訊號
        want_sell = False
        if shares > 0:
            below200 = twii[i] < ma200[i]
            below10 = not math.isnan(ma10[i]) and c < ma10[i]
            if exit_rule == "ma10":
                want_sell = below10
            elif exit_rule == "ma200":
                want_sell = below200
            elif exit_rule == "ma200_or_ma10":
                want_sell = below200 or below10
        if want_sell:
            pending = "sell"
            continue

        if shares == 0.0:
            if entry == "always":
                pending = "buy"
            elif entry == "ma200":
                if twii[i] > ma200[i]:
                    pending = "buy"
            elif entry == "grade":
                level = macro_level_from(twii, i)
                g = grade_pullback_core_i(twii, i, level)
                if g in ("B", "A", "S"):
                    pending = "buy"

    return {"m": metrics(pd.Series(equity), trades), "eq": pd.Series(equity), "dt": dates}


def crisis_dd(eq: pd.Series, dates, w0, w1) -> float:
    s = pd.Series(eq.values, index=pd.to_datetime(dates))
    s = s[(s.index >= w0) & (s.index <= w1)]
    if len(s) < 2:
        return float("nan")
    return float(((s - s.cummax()) / s.cummax() * 100).min())


def main():
    print("=== 0050／00631L 出場規則拆解回測 ===")
    df, calib = build_dataset()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]
    print(f"區間 {d0} ~ {d1}（{len(df)} 日）")

    runs = {
        "0050": {
            "A. 買入持有（含息）": dict(asset="1x", entry="always", exit_rule="none"),
            "B. 評等B+進場、永不出場": dict(asset="1x", entry="grade", exit_rule="none"),
            "C. 現行：評等進場＋破10MA出場": dict(asset="1x", entry="grade", exit_rule="ma10"),
            "D. 200MA開關（無評等）": dict(asset="1x", entry="ma200", exit_rule="ma200"),
            "E. 評等進場＋只破200MA出場": dict(asset="1x", entry="grade", exit_rule="ma200"),
        },
        "00631L": {
            "L1. 200MA開關（主規則）": dict(asset="lev", entry="ma200", exit_rule="ma200"),
            "L2. 現行合併：200MA或10MA出場": dict(asset="lev", entry="ma200", exit_rule="ma200_or_ma10"),
        },
    }

    results = {}
    for prod, strategies in runs.items():
        results[prod] = {}
        print(f"\n--- {prod} ---")
        for name, kw in strategies.items():
            full = sim(df, **kw)
            oos = sim(df, **kw, start="2016-01-01")
            results[prod][name] = {"full": full, "oos": oos}
            mf, mo = full["m"], oos["m"]
            print(f"  {name}: 全期 CAGR {mf['cagr']:+6.2f}% MDD {mf['mdd']:6.1f}% CP {mf['cp']:6.2f} "
                  f"| OOS CAGR {mo['cagr']:+6.2f}% MDD {mo['mdd']:6.1f}% CP {mo['cp']:6.2f}")

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    md = os.path.join(out_dir, "exit_rule_backtest.md")
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "range": [d0, d1], "costs": {"buy": BUY_C, "sell": SELL_C},
               "div_yield_assumed": 0.035, "products": {}}
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 0050／00631L 出場規則拆解回測（27年長歷史＋真實成本）\n\n")
        f.write(f"產生：{payload['generated_at']}｜區間 `{d0}` ~ `{d1}`  \n")
        f.write("0050 以 TWII 1x 代理，持有期間補估計股息 3.5%/年；正2 用合成+實際 2x 序列。  \n")
        f.write(f"成本：買 {BUY_C:.4%}／賣 {SELL_C:.4%}（含 ETF 稅 0.1%）。EOD 訊號隔日開盤執行。  \n\n")
        for prod, res in results.items():
            f.write(f"## {prod}\n\n")
            f.write("| 策略 | 全期CAGR | 全期MDD | 全期CP | OOS(2016~)CAGR | OOS MDD | OOS CP | 交易/年 |\n")
            f.write("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
            payload["products"][prod] = {}
            for name, r in res.items():
                mf, mo = r["full"]["m"], r["oos"]["m"]
                f.write(f"| {name} | {mf['cagr']:+.2f}% | {mf['mdd']:.1f}% | {mf['cp']:.2f} "
                        f"| {mo['cagr']:+.2f}% | {mo['mdd']:.1f}% | {mo['cp']:.2f} "
                        f"| {mf['trades']/max(mf['years'],0.1):.1f} |\n")
                payload["products"][prod][name] = {
                    "full": {k: round(v, 3) for k, v in mf.items()},
                    "oos": {k: round(v, 3) for k, v in mo.items()},
                }
            f.write("\n### 危機窗 MDD\n\n")
            names = list(res.keys())
            f.write("| 危機窗 | " + " | ".join(names) + " |\n")
            f.write("| :--- |" + " ---: |" * len(names) + "\n")
            for label, w0, w1 in CRISIS:
                cells = []
                for name in names:
                    v = crisis_dd(res[name]["full"]["eq"], res[name]["full"]["dt"], w0, w1)
                    cells.append("—" if math.isnan(v) else f"{v:.1f}%")
                f.write(f"| {label} | " + " | ".join(cells) + " |\n")
            f.write("\n")
        f.write("## 判讀\n\n")
        f.write("- 0050：B vs C 差距＝10MA出場的代價；B vs E＝加年線保險的代價；A vs B＝評等進場節奏的增量。  \n")
        f.write("- 00631L：L1 vs L2 差距＝10MA輔助出場是幫忙還是扣分。  \n")
        f.write("- TWII 為價格指數；1x 股息以固定 3.5%/年近似，實際隨年度變動。  \n")
    with open(os.path.join(out_dir, "exit_rule_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=float)
    print(f"\n報告：{md}")


if __name__ == "__main__":
    main()
