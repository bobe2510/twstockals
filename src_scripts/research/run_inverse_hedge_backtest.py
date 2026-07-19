# -*- coding: utf-8 -*-
"""
正2 年線開關的空手期：持現金 vs 持反1（00632R 型）對比。

反1 合成：日報酬 = −1×TAIEX日報酬 − 1.1%/年損耗（內扣+期貨轉倉；日重設）。
切換成本：賣正2＋買反1 = 兩筆（台股 ETF 費率），空手只有一筆。
資料沿用 run_voltarget_backtest.build_dataset（1998~，合成+實際 2x）。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

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

BUY_C = 0.001925
SELL_C = 0.002925
INV_DRAG_DAILY = 0.011 / 252.0  # 反1 內扣+轉倉損耗

CRISIS = [
    ("2000 網路泡沫", "2000-02-01", "2001-10-31"),
    ("2008 金融海嘯", "2007-10-01", "2008-12-31"),
    ("2020 COVID", "2020-01-01", "2020-04-30"),
    ("2022 升息年", "2022-01-01", "2022-11-30"),
    ("2025-26 回檔", "2025-01-01", "2099-12-31"),
]


def sim(df, *, bear_asset: str, start=None) -> dict:
    """年線上持正2；年線下持 bear_asset ∈ {'cash','inverse'}。EOD訊號隔日開盤執行。"""
    idx = list(df.index if start is None else df.index[df["date"] >= start])
    twii = df["twii_close"].to_numpy(float)
    ma200 = df["ma200"].to_numpy(float)
    lev_o = df["lev_open"].to_numpy(float)
    lev_c = df["lev_close"].to_numpy(float)
    ret = df["ret"].to_numpy(float)

    cash = INITIAL_CASH
    lev_sh = 0.0
    inv_val = 0.0  # 反1 部位市值（用日報酬滾動）
    pending = None
    equity, dates = [], []
    trades = 0

    for k, i in enumerate(idx):
        # 反1 部位每日滾動（含當日報酬與損耗）
        if inv_val > 0 and not math.isnan(ret[i]):
            inv_val *= 1.0 - ret[i] - INV_DRAG_DAILY

        if pending == "to_lev":
            if inv_val > 0:
                cash += inv_val * (1 - SELL_C)
                inv_val = 0.0
                trades += 1
            lev_sh = cash / (lev_o[i] * (1 + BUY_C))
            cash = 0.0
            trades += 1
        elif pending == "to_bear":
            cash = lev_sh * lev_o[i] * (1 - SELL_C)
            lev_sh = 0.0
            trades += 1
            if bear_asset == "inverse":
                inv_val = cash * (1 - BUY_C)
                cash = 0.0
                trades += 1
        pending = None

        equity.append(cash + lev_sh * lev_c[i] + inv_val)
        dates.append(df.at[i, "date"])
        if k >= len(idx) - 1:
            continue

        want_lev = twii[i] > ma200[i]
        if want_lev and lev_sh == 0.0:
            pending = "to_lev"
        elif not want_lev and lev_sh > 0.0:
            pending = "to_bear"

    return {"m": metrics(pd.Series(equity), trades), "eq": pd.Series(equity), "dt": dates}


def crisis_dd(eq, dts, w0, w1):
    s = pd.Series(eq.values, index=pd.to_datetime(dts))
    s = s[(s.index >= w0) & (s.index <= w1)]
    if len(s) < 2:
        return float("nan")
    return float(((s - s.cummax()) / s.cummax() * 100).min())


def crisis_ret(eq, dts, w0, w1):
    s = pd.Series(eq.values, index=pd.to_datetime(dts))
    s = s[(s.index >= w0) & (s.index <= w1)]
    if len(s) < 2:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[0] - 1) * 100)


def main():
    print("=== 年線下：空手 vs 持反1 ===")
    df, _ = build_dataset()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]

    res = {
        "空手（現行 L1）": sim(df, bear_asset="cash"),
        "持反1（-1x, 損耗1.1%/年）": sim(df, bear_asset="inverse"),
    }
    oos = {
        "空手（現行 L1）": sim(df, bear_asset="cash", start="2016-01-01"),
        "持反1（-1x, 損耗1.1%/年）": sim(df, bear_asset="inverse", start="2016-01-01"),
    }

    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    md = os.path.join(out_dir, "inverse_hedge_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 年線下空手 vs 持反1（27年含成本）\n\n")
        f.write(f"產生：{datetime.now().isoformat(timespec='seconds')}｜區間 `{d0}` ~ `{d1}`  \n")
        f.write("年線上持正2 相同；差別僅年線下的防禦資產。反1 損耗 1.1%/年（日重設）。  \n\n")
        f.write("| 策略 | 全期CAGR | 全期MDD | 全期CP | OOS(2016~)CAGR | OOS MDD | 交易/年 |\n")
        f.write("| :--- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for name, r in res.items():
            m, mo = r["m"], oos[name]["m"]
            f.write(f"| {name} | {m['cagr']:+.2f}% | {m['mdd']:.1f}% | {m['cp']:.2f} "
                    f"| {mo['cagr']:+.2f}% | {mo['mdd']:.1f}% "
                    f"| {m['trades']/max(m['years'],0.1):.1f} |\n")
            print(f"{name}: 全期 {m['cagr']:+.2f}%/{m['mdd']:.1f}%/CP{m['cp']:.2f} "
                  f"trades/yr {m['trades']/max(m['years'],0.1):.1f}")
        f.write("\n## 危機窗（該窗內策略報酬％｜MDD％）\n\n")
        f.write("| 危機窗 | 空手 | 持反1 |\n| :--- | ---: | ---: |\n")
        for label, w0, w1 in CRISIS:
            cells = []
            for name in res:
                rr = crisis_ret(res[name]["eq"], res[name]["dt"], w0, w1)
                dd = crisis_dd(res[name]["eq"], res[name]["dt"], w0, w1)
                cells.append(f"{rr:+.1f}%｜{dd:.1f}%" if not math.isnan(rr) else "—")
            f.write(f"| {label} | {cells[0]} | {cells[1]} |\n")
        f.write("\n- 反1 在崩盤「窗內」可能賺，但整體差異看全期：熊市反彈鋸齒＋損耗＋雙倍交易的代價。  \n")
    print(f"報告：{md}")


if __name__ == "__main__":
    main()
