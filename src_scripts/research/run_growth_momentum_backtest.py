# -*- coding: utf-8 -*-
"""
成長袖相對動量：QQQ（台幣計價）vs 00631L 正2，每 21 日持 12 月動量較強者。

前提規則（與現行政策一致）：
  正2 閘門＝大盤>200MA；QQQ 閘門＝>200MA 或 12月動量>0（G複合）。
  相對動量持強者，但強者閘門 OFF 則看次者；兩者皆 OFF → 現金。
對照：純正2(L1)、純QQQ(G閘門)、50/50 月再平衡。
成本：台股 ETF 買0.1925%/賣0.2925%；美股 0.07%/邊。EOD 訊號隔日執行。
窗：2004~（受 USDTWD 資料限制）；OOS 2016~。
"""
from __future__ import annotations

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
from run_trend_exit_backtest import fetch_yahoo_adj  # noqa: E402

CACHE = os.path.join(WORKSPACE, "market_crawled_cache")
TW_BUY, TW_SELL = 0.001925, 0.002925
US_BUY, US_SELL = 0.0007, 0.0007
CHECK = 21
MOM = 252


def load() -> pd.DataFrame:
    lev, _ = build_dataset()
    qqq = fetch_yahoo_adj("QQQ").rename(columns={"close": "qqq_usd"})
    fx = pd.read_csv(os.path.join(CACHE, "USDTWD_full_history.csv")).rename(
        columns={"close": "fx"}
    )
    fx = fx[(fx["fx"] > 20) & (fx["fx"] < 45)]
    df = lev[["date", "twii_close", "ma200", "lev_open", "lev_close"]].merge(
        qqq, on="date", how="left").merge(fx, on="date", how="left")
    df["qqq_usd"] = df["qqq_usd"].ffill()
    df["fx"] = df["fx"].ffill()
    df["qqq_twd"] = df["qqq_usd"] * df["fx"]
    return df.dropna(subset=["qqq_twd", "lev_close"]).reset_index(drop=True)


def sim(df, mode: str, start=None) -> dict:
    """mode: lev_only | qqq_only | half | rel_mom"""
    idx = list(df.index if start is None else df.index[df["date"] >= start])
    twii = df["twii_close"].to_numpy(float)
    ma200 = df["ma200"].to_numpy(float)
    lev = df["lev_close"].to_numpy(float)
    lev_o = df["lev_open"].to_numpy(float)
    qqq = df["qqq_twd"].to_numpy(float)
    qma200 = pd.Series(qqq).rolling(200).mean().to_numpy()

    cash = INITIAL_CASH
    pos = {"lev": 0.0, "qqq": 0.0}  # units
    px_now = {"lev": lev, "qqq": qqq}
    exec_px = {"lev": lev_o, "qqq": qqq}  # qqq 無開盤價，用收盤近似
    buy_c = {"lev": TW_BUY, "qqq": US_BUY}
    sell_c = {"lev": TW_SELL, "qqq": US_SELL}

    pending_target = None  # dict asset->weight
    equity, trades = [], 0

    for k, i in enumerate(idx):
        if pending_target is not None:
            total = cash + sum(pos[a] * exec_px[a][i] for a in pos)
            for a in pos:  # sells first
                want = pending_target.get(a, 0.0) * total
                have = pos[a] * exec_px[a][i]
                if have - want > total * 0.005:
                    sell_val = have - want
                    cash += sell_val * (1 - sell_c[a])
                    pos[a] -= sell_val / exec_px[a][i]
                    trades += 1
            for a in pos:  # buys
                want = pending_target.get(a, 0.0) * total
                have = pos[a] * exec_px[a][i]
                if want - have > total * 0.005 and cash > 0:
                    spend = min(want - have, cash)
                    pos[a] += spend / (exec_px[a][i] * (1 + buy_c[a]))
                    cash -= spend
                    trades += 1
            pending_target = None

        equity.append(cash + sum(pos[a] * px_now[a][i] for a in pos))
        if k >= len(idx) - 1 or k % CHECK != 0:
            continue

        gate_lev = twii[i] > ma200[i]
        mom_q = i >= MOM and qqq[i] > qqq[i - MOM]
        gate_qqq = (not math.isnan(qma200[i]) and qqq[i] > qma200[i]) or mom_q

        if mode == "lev_only":
            tgt = {"lev": 1.0} if gate_lev else {}
        elif mode == "qqq_only":
            tgt = {"qqq": 1.0} if gate_qqq else {}
        elif mode == "half":
            tgt = {}
            if gate_lev:
                tgt["lev"] = 0.5
            if gate_qqq:
                tgt["qqq"] = 0.5
        else:  # rel_mom
            m_lev = lev[i] / lev[i - MOM] - 1 if i >= MOM else -9
            m_qqq = qqq[i] / qqq[i - MOM] - 1 if i >= MOM else -9
            order = ["lev", "qqq"] if m_lev >= m_qqq else ["qqq", "lev"]
            gates = {"lev": gate_lev, "qqq": gate_qqq}
            tgt = {}
            for a in order:
                if gates[a]:
                    tgt = {a: 1.0}
                    break
        pending_target = tgt

    return {"m": metrics(pd.Series(equity), trades)}


def main():
    print("=== 成長袖相對動量（QQQ vs 正2）===")
    df = load()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]
    print(f"窗：{d0} ~ {d1}")

    modes = {
        "純正2（年線開關）": "lev_only",
        "純QQQ（G複合閘門）": "qqq_only",
        "50/50（各自閘門）": "half",
        "相對動量持強者": "rel_mom",
    }
    out_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    md = os.path.join(out_dir, "growth_momentum_backtest.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# 成長袖相對動量回測（QQQ台幣 vs 00631L）\n\n")
        f.write(f"產生：{datetime.now().isoformat(timespec='seconds')}｜窗 `{d0}` ~ `{d1}`  \n")
        f.write("每21日檢：12月動量持強者（各自趨勢閘門為前提，皆OFF→現金）。含成本。  \n\n")
        f.write("| 策略 | 全期CAGR | 全期MDD | 全期CP | OOS(2016~)CAGR | OOS MDD | OOS CP | 交易/年 |\n")
        f.write("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for name, mode in modes.items():
            r = sim(df, mode)["m"]
            o = sim(df, mode, start="2016-01-01")["m"]
            f.write(f"| {name} | {r['cagr']:+.2f}% | {r['mdd']:.1f}% | {r['cp']:.2f} "
                    f"| {o['cagr']:+.2f}% | {o['mdd']:.1f}% | {o['cp']:.2f} "
                    f"| {r['trades']/max(r['years'],0.1):.1f} |\n")
            print(f"  {name}: 全期 {r['cagr']:+.2f}%/{r['mdd']:.1f}%/CP{r['cp']:.2f} | "
                  f"OOS {o['cagr']:+.2f}%/{o['mdd']:.1f}%/CP{o['cp']:.2f}")
        f.write("\n- QQQ 台幣計價含匯率效果；QQQ 執行價用收盤近似（無開盤序列）。  \n")
        f.write("- 正2 用合成+實際 2x；相對動量的選擇偏誤請以 OOS 與單持基準對照判讀。  \n")
    print(f"報告：{md}")


if __name__ == "__main__":
    main()
