# -*- coding: utf-8 -*-
"""
絕對動量 lookback／OOS 穩健性 + 與現行評等混合回測。

對照：
  - B&H
  - 現行評等全日倉（B+ 或政策門檻 S／B+）+ 破 ma50 出
  - 純絕對動量（多 lookback）
  - 完整 GEM：VOO↔VXUS，雙弱→現金
  - 混合：動量決定袖口 on/off；評等只當「允許進場」濾網

穩健性：
  - lookback ∈ {126,189,210,252}（約 6/9/10/12 月）
  - 全樣本 CP + 近 2y OOS
  - IS 選最佳 lookback → 鎖參後只評 OOS（防偷看）

不寫入 live policy。
"""
from __future__ import annotations

import json
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
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


WORKSPACE = _find_workspace()
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from run_etf_backtest import get_metrics  # noqa: E402
from run_grade_threshold_backtest import (  # noqa: E402
    COMM_US,
    INITIAL,
    grade_growth_us_i,
    grade_pullback_core_i,
    meets_threshold,
    prepare_us,
    slice_with_warmup,
)

_OUT_DIR = os.path.join(WORKSPACE, "reports", "latest", "backtest")
os.makedirs(_OUT_DIR, exist_ok=True)
REPORT_MD = os.path.join(_OUT_DIR, "momentum_hybrid_backtest.md")
REPORT_JSON = os.path.join(_OUT_DIR, "momentum_hybrid_backtest.json")

LOOKBACKS = [126, 189, 210, 252]  # ~6/9/10/12m
OOS_BARS = 504
REBAL_EVERY = 21  # 月頻訊號（約）
POLICY_MODE = {"VOO": "S", "VXUS": "S", "QQQ": "B+"}


def mom(closes: np.ndarray, i: int, look: int) -> float:
    if i < look:
        return 0.0
    a = float(closes[i - look])
    if a <= 0:
        return 0.0
    return float(closes[i]) / a - 1.0


def grade_us(sym: str, closes: np.ndarray, i: int) -> str:
    if sym == "QQQ":
        return grade_growth_us_i(closes, i)
    return grade_pullback_core_i(closes, i, 1)


def _oos(equity: list[float], test_start: int, trade_idx: list[int], initial: float) -> dict | None:
    eq = pd.Series(equity[test_start:], dtype=float)
    if len(eq) < OOS_BARS + 20:
        return None
    eq_oos = eq.iloc[-OOS_BARS:] * (initial / float(eq.iloc[-OOS_BARS]))
    years = OOS_BARS / 252.0
    oos0 = test_start + len(eq) - OOS_BARS
    n_tr = sum(1 for t in trade_idx if t >= oos0)
    m = get_metrics(eq_oos, n_tr, years, initial)
    return {
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "cp": round(m["cp"], 2),
        "trades": n_tr,
        "final": round(m["final"], 0),
    }


def _pack(equity, closes, test_start, trades, buys, trade_idx, note, **extra) -> dict:
    eq = pd.Series(equity[test_start:], dtype=float)
    years = max(len(eq) / 252.0, 0.1)
    m = get_metrics(eq, trades, years, INITIAL)
    bh = closes[test_start:] / closes[test_start] * INITIAL
    mb = get_metrics(pd.Series(bh), 0, years, INITIAL)
    r = {
        "ok": True,
        "note": note,
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "sharpe": round(m["sharpe"], 3),
        "final": round(m["final"], 0),
        "cp": round(m["cp"], 2),
        "trades": trades,
        "buys": buys,
        "ops_yr": round(m["workday_ops_per_year"], 2),
        "years": round(years, 2),
        "bh_cagr": round(mb["cagr"], 2),
        "bh_mdd": round(mb["mdd"], 2),
        "bh_final": round(mb["final"], 0),
        "bh_cp": round(mb["cp"], 2),
        "beat_bh": m["final"] > mb["final"],
        "beat_bh_cp": m["cp"] > mb["cp"],
        "oos_2y": _oos(equity, test_start, trade_idx, INITIAL),
    }
    r.update(extra)
    return r


def sim_bh(closes: np.ndarray, test_start: int, note: str = "B&H") -> dict:
    n = len(closes)
    equity = [INITIAL * float(closes[i]) / float(closes[test_start]) for i in range(n)]
    # flat before test_start
    for i in range(test_start):
        equity[i] = INITIAL
    return _pack(equity, closes, test_start, 0, 0, [], note, id_suffix="bh")


def sim_single(
    closes: np.ndarray,
    *,
    test_start: int,
    sym: str,
    mode: str,
    look: int | None,
    strategy: str,
) -> dict:
    """
    strategy:
      grade_ma50  — 評等進、破 ma50 出（現行對照）
      abs_mom     — 純絕對動量（月頻）
      hybrid_gate — mom>0 才允許評等進場；mom<=0 強制出；持有中不因 ma50 出
      hybrid_both — mom>0 且評等達標才進；出：mom<=0 或 破 ma50
    """
    n = len(closes)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}
    need = look or 0
    cash, units = INITIAL, 0.0
    equity: list[float] = []
    trades = buys = 0
    trade_idx: list[int] = []
    last_rebal = -999
    target_on = False

    for i in range(n):
        px = float(closes[i])
        equity.append(cash + units * px)
        if i < test_start or i >= n - 1:
            continue
        if i < max(199, need):
            continue

        # monthly refresh for mom strategies
        if strategy in ("abs_mom", "hybrid_gate", "hybrid_both") and look:
            if i - last_rebal >= REBAL_EVERY or last_rebal < 0:
                target_on = mom(closes, i, look) > 0
                last_rebal = i

        g = grade_us(sym, closes, i)
        ma50 = float(np.mean(closes[i - 49 : i + 1]))
        below50 = px < ma50
        j = i + 1
        pxn = float(closes[j])

        want_buy = False
        want_sell = False

        if strategy == "grade_ma50":
            want_sell = units > 0 and below50
            want_buy = units == 0 and meets_threshold(g, mode)
        elif strategy == "abs_mom":
            want_sell = units > 0 and not target_on
            want_buy = units == 0 and target_on
        elif strategy == "hybrid_gate":
            want_sell = units > 0 and not target_on
            want_buy = units == 0 and target_on and meets_threshold(g, mode)
        elif strategy == "hybrid_both":
            want_sell = units > 0 and (not target_on or below50)
            want_buy = units == 0 and target_on and meets_threshold(g, mode)
        else:
            return {"ok": False, "reason": f"unknown {strategy}"}

        if want_sell and units > 0:
            cash += units * pxn * (1 - COMM_US)
            units = 0.0
            trades += 1
            trade_idx.append(i)
        if want_buy and units == 0 and cash > 0:
            units = cash / (pxn * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)

    note = f"{sym} {strategy} mode={mode}" + (f" L={look}" if look else "")
    return _pack(
        equity,
        closes,
        test_start,
        trades,
        buys,
        trade_idx,
        note,
        strategy=strategy,
        sym=sym,
        mode=mode,
        lookback=look,
    )


def sim_gem(
    voo: np.ndarray,
    vxus: np.ndarray,
    *,
    test_start: int,
    look: int,
) -> dict:
    """完整 GEM：相對強者且 abs>0，否則現金。月頻。"""
    n = len(voo)
    cash, u_v, u_x = INITIAL, 0.0, 0.0
    equity: list[float] = []
    trades = buys = 0
    trade_idx: list[int] = []
    last_rebal = -999
    target = "cash"  # cash|voo|vxus

    for i in range(n):
        equity.append(cash + u_v * voo[i] + u_x * vxus[i])
        if i < test_start or i >= n - 1 or i < look:
            continue
        if i - last_rebal >= REBAL_EVERY or last_rebal < 0:
            mv, mx = mom(voo, i, look), mom(vxus, i, look)
            if mv <= 0 and mx <= 0:
                target = "cash"
            else:
                target = "voo" if mv >= mx else "vxus"
            last_rebal = i

        j = i + 1
        if u_v > 0 and target != "voo":
            cash += u_v * voo[j] * (1 - COMM_US)
            u_v = 0.0
            trades += 1
            trade_idx.append(i)
        if u_x > 0 and target != "vxus":
            cash += u_x * vxus[j] * (1 - COMM_US)
            u_x = 0.0
            trades += 1
            trade_idx.append(i)
        if target == "voo" and u_v == 0 and cash > 0:
            u_v = cash / (voo[j] * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)
        elif target == "vxus" and u_x == 0 and cash > 0:
            u_x = cash / (vxus[j] * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)

    # BH 對照用 VOO
    r = _pack(equity, voo, test_start, trades, buys, trade_idx, f"GEM full L={look}", strategy="gem_full", lookback=look)
    r["sym"] = "VOO+VXUS"
    return r


def sim_gem_hybrid(
    voo: np.ndarray,
    vxus: np.ndarray,
    *,
    test_start: int,
    look: int,
    mode_v: str = "S",
    mode_x: str = "S",
) -> dict:
    """
    GEM 選標的／現金；若選中該標的，還需該標的評等達門檻才進場。
    已持有則持有到 GEM 換標或轉現金（不因 ma50 出）。
    """
    n = len(voo)
    cash, u_v, u_x = INITIAL, 0.0, 0.0
    equity: list[float] = []
    trades = buys = 0
    trade_idx: list[int] = []
    last_rebal = -999
    gem_tgt = "cash"

    for i in range(n):
        equity.append(cash + u_v * voo[i] + u_x * vxus[i])
        if i < test_start or i >= n - 1 or i < max(look, 199):
            continue
        if i - last_rebal >= REBAL_EVERY or last_rebal < 0:
            mv, mx = mom(voo, i, look), mom(vxus, i, look)
            if mv <= 0 and mx <= 0:
                gem_tgt = "cash"
            else:
                gem_tgt = "voo" if mv >= mx else "vxus"
            last_rebal = i

        j = i + 1
        gv = grade_us("VOO", voo, i)
        gx = grade_us("VXUS", vxus, i)

        # exits on gem change
        if u_v > 0 and gem_tgt != "voo":
            cash += u_v * voo[j] * (1 - COMM_US)
            u_v = 0.0
            trades += 1
            trade_idx.append(i)
        if u_x > 0 and gem_tgt != "vxus":
            cash += u_x * vxus[j] * (1 - COMM_US)
            u_x = 0.0
            trades += 1
            trade_idx.append(i)

        if gem_tgt == "voo" and u_v == 0 and cash > 0 and meets_threshold(gv, mode_v):
            u_v = cash / (voo[j] * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)
        elif gem_tgt == "vxus" and u_x == 0 and cash > 0 and meets_threshold(gx, mode_x):
            u_x = cash / (vxus[j] * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)

    r = _pack(
        equity,
        voo,
        test_start,
        trades,
        buys,
        trade_idx,
        f"GEM×grade({mode_v}/{mode_x}) L={look}",
        strategy="gem_hybrid",
        lookback=look,
    )
    r["sym"] = "VOO+VXUS"
    return r


def lock_lookback_oos(
    closes: np.ndarray,
    test_start: int,
    sym: str,
    mode: str,
    strategy: str,
) -> dict:
    """IS（OOS 之前）用 CP 選 lookback，再只在 OOS 窗評測鎖參模型。"""
    n = len(closes)
    oos0 = n - OOS_BARS
    if oos0 <= test_start + 50:
        return {"ok": False, "reason": "OOS 窗不足"}

    best_l, best_cp = None, -1e18
    is_rows = []
    for L in LOOKBACKS:
        # simulate full then slice IS metrics manually
        full = sim_single(closes, test_start=test_start, sym=sym, mode=mode, look=L, strategy=strategy)
        if not full.get("ok"):
            continue
        # rebuild IS-only CP from equity in full run — re-sim with eval end at oos0
        cash, units = INITIAL, 0.0
        equity = []
        trades = buys = 0
        trade_idx = []
        last_rebal = -999
        target_on = False
        for i in range(oos0):  # stop before OOS
            px = float(closes[i])
            equity.append(cash + units * px)
            if i < test_start or i >= oos0 - 1 or i < max(199, L):
                continue
            if i - last_rebal >= REBAL_EVERY or last_rebal < 0:
                target_on = mom(closes, i, L) > 0
                last_rebal = i
            g = grade_us(sym, closes, i)
            ma50 = float(np.mean(closes[i - 49 : i + 1]))
            below50 = px < ma50
            j = i + 1
            pxn = float(closes[j])
            want_buy = want_sell = False
            if strategy == "abs_mom":
                want_sell = units > 0 and not target_on
                want_buy = units == 0 and target_on
            elif strategy == "hybrid_gate":
                want_sell = units > 0 and not target_on
                want_buy = units == 0 and target_on and meets_threshold(g, mode)
            elif strategy == "hybrid_both":
                want_sell = units > 0 and (not target_on or below50)
                want_buy = units == 0 and target_on and meets_threshold(g, mode)
            if want_sell and units > 0:
                cash += units * pxn * (1 - COMM_US)
                units = 0.0
                trades += 1
            if want_buy and units == 0 and cash > 0:
                units = cash / (pxn * (1 + COMM_US))
                cash = 0.0
                trades += 1
                buys += 1
        eq = pd.Series(equity[test_start:], dtype=float)
        if len(eq) < 50:
            continue
        years = max(len(eq) / 252.0, 0.1)
        m = get_metrics(eq, trades, years, INITIAL)
        is_rows.append({"L": L, "cp": round(m["cp"], 2), "cagr": round(m["cagr"], 2)})
        if m["cp"] > best_cp:
            best_cp = m["cp"]
            best_l = L

    if best_l is None:
        return {"ok": False, "reason": "IS 無解"}

    # OOS with locked L: start OOS flat at INITIAL, apply locked strategy
    cash, units = INITIAL, 0.0
    equity_oos = []
    trades = buys = 0
    trade_idx = []
    last_rebal = -999
    target_on = False
    # warm mom/grade using history before oos0; start trading at oos0
    for i in range(oos0, n):
        px = float(closes[i])
        equity_oos.append(cash + units * px)
        if i >= n - 1 or i < max(199, best_l):
            continue
        if i - last_rebal >= REBAL_EVERY or last_rebal < 0:
            target_on = mom(closes, i, best_l) > 0
            last_rebal = i
        g = grade_us(sym, closes, i)
        ma50 = float(np.mean(closes[i - 49 : i + 1]))
        below50 = px < ma50
        j = i + 1
        pxn = float(closes[j])
        want_buy = want_sell = False
        if strategy == "abs_mom":
            want_sell = units > 0 and not target_on
            want_buy = units == 0 and target_on
        elif strategy == "hybrid_gate":
            want_sell = units > 0 and not target_on
            want_buy = units == 0 and target_on and meets_threshold(g, mode)
        elif strategy == "hybrid_both":
            want_sell = units > 0 and (not target_on or below50)
            want_buy = units == 0 and target_on and meets_threshold(g, mode)
        if want_sell and units > 0:
            cash += units * pxn * (1 - COMM_US)
            units = 0.0
            trades += 1
            trade_idx.append(i)
        if want_buy and units == 0 and cash > 0:
            units = cash / (pxn * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)

    eq = pd.Series(equity_oos, dtype=float)
    years = OOS_BARS / 252.0
    m = get_metrics(eq, trades, years, INITIAL)
    bh = closes[oos0:] / closes[oos0] * INITIAL
    mb = get_metrics(pd.Series(bh), 0, years, INITIAL)
    return {
        "ok": True,
        "sym": sym,
        "strategy": strategy,
        "mode": mode,
        "locked_lookback": best_l,
        "is_candidates": is_rows,
        "oos_cagr": round(m["cagr"], 2),
        "oos_mdd": round(m["mdd"], 2),
        "oos_cp": round(m["cp"], 2),
        "oos_final": round(m["final"], 0),
        "oos_buys": buys,
        "bh_oos_cagr": round(mb["cagr"], 2),
        "bh_oos_cp": round(mb["cp"], 2),
        "beat_bh_oos": m["final"] > mb["final"],
        "beat_bh_cp_oos": m["cp"] > mb["cp"],
        "note": f"{sym} {strategy} lock L={best_l} → OOS",
    }


def fmt(r: dict) -> str:
    if not r.get("ok"):
        return f"| — | {r.get('note', r.get('reason'))} | FAIL | | | | | |"
    o = r.get("oos_2y") or {}
    os_ = f"{o.get('cp', '—')}" if o else "—"
    return (
        f"| `{r.get('strategy', '')}` | {r.get('note', '')} | "
        f"{r['cagr']:+.1f} | {r['mdd']:.1f} | {r['cp']:+.1f} | "
        f"{r.get('bh_cp', 0):+.1f} | {'Y' if r.get('beat_bh_cp') else 'N'} | "
        f"{r['buys']} | {os_} |"
    )


def main():
    print("=== 動量 lookback／混合／GEM 穩健性回測 ===\n")
    prepared = {}
    for sym in ("VOO", "VXUS", "QQQ"):
        df = prepare_us(sym)
        if df.empty:
            print(f"{sym}: empty")
            continue
        df, start = slice_with_warmup(df, 5)
        prepared[sym] = (df["close"].astype(float).values, start, df)
        print(f"{sym}: n={len(df)} test_start={start}")

    all_rows: list[dict] = []
    lock_rows: list[dict] = []

    for sym, (closes, ts, _) in prepared.items():
        mode = POLICY_MODE[sym]
        # baselines
        bh = sim_bh(closes, ts, f"{sym} B&H")
        bh["strategy"] = "bh"
        bh["sym"] = sym
        all_rows.append(bh)

        g = sim_single(closes, test_start=ts, sym=sym, mode=mode, look=None, strategy="grade_ma50")
        g["id"] = f"{sym}_grade_{mode}"
        all_rows.append(g)

        g_b = sim_single(closes, test_start=ts, sym=sym, mode="B+", look=None, strategy="grade_ma50")
        g_b["id"] = f"{sym}_grade_B+"
        all_rows.append(g_b)

        for L in LOOKBACKS:
            for strat in ("abs_mom", "hybrid_gate", "hybrid_both"):
                r = sim_single(closes, test_start=ts, sym=sym, mode=mode, look=L, strategy=strat)
                r["id"] = f"{sym}_{strat}_L{L}"
                all_rows.append(r)

        for strat in ("abs_mom", "hybrid_gate"):
            lk = lock_lookback_oos(closes, ts, sym, mode, strat)
            if lk.get("ok"):
                lock_rows.append(lk)
                print(
                    f"  LOCK {sym} {strat}: IS→L={lk['locked_lookback']}  "
                    f"OOS CP {lk['oos_cp']:+.1f} vs BH_CP {lk['bh_oos_cp']:+.1f}  "
                    f"{'勝CP' if lk['beat_bh_cp_oos'] else '輸CP'}"
                )

    # GEM on aligned VOO/VXUS
    if "VOO" in prepared and "VXUS" in prepared:
        df_v = prepared["VOO"][2]
        df_x = prepared["VXUS"][2]
        m = df_v.merge(
            df_x.rename(columns={"close": "vxus", "open": "vxus_o"}),
            on="date",
            how="inner",
        ).sort_values("date").reset_index(drop=True)
        m2, ts = slice_with_warmup(m, 5)
        voo = m2["close"].astype(float).values
        vxus = m2["vxus"].astype(float).values
        print(f"GEM align n={len(m2)} test_start={ts}")
        for L in LOOKBACKS:
            r = sim_gem(voo, vxus, test_start=ts, look=L)
            r["id"] = f"GEM_L{L}"
            all_rows.append(r)
            rh = sim_gem_hybrid(voo, vxus, test_start=ts, look=L)
            rh["id"] = f"GEM_hybrid_L{L}"
            all_rows.append(rh)

    # print top by CP per sym
    print("\n--- 全樣本 CP 摘要（各策略最佳 lookback）---")
    summary_best = []
    for sym in list(prepared.keys()) + ["VOO+VXUS"]:
        rs = [r for r in all_rows if r.get("ok") and r.get("sym") == sym]
        if not rs:
            continue
        best = max(rs, key=lambda x: x.get("cp", -1e9))
        base = next((r for r in rs if r.get("strategy") == "grade_ma50" and r.get("mode") == POLICY_MODE.get(sym, "S")), None)
        if sym == "VOO+VXUS":
            base = next((r for r in rs if r.get("strategy") == "gem_full" and r.get("lookback") == 252), None)
        bh = next((r for r in rs if r.get("strategy") == "bh"), None)
        summary_best.append({"sym": sym, "best": best, "grade_base": base, "bh": bh})
        bcp = base["cp"] if base else None
        print(
            f"  {sym:10s} best={best.get('strategy')} L={best.get('lookback')} "
            f"CP {best['cp']:+.1f} | grade/base {bcp} | BH_CP {bh['bh_cp'] if bh else bh and bh.get('cp')}"
        )

    # write report
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 絕對動量 lookback／OOS／混合／GEM 回測",
        "",
        f"- 產生：{now}",
        f"- Lookbacks：{LOOKBACKS}（約 6/9/10/12 月）｜訊號月頻 ≈{REBAL_EVERY} 日",
        f"- 政策門檻：{POLICY_MODE}；混合 = 動量 on/off × 評等允許進場",
        f"- 主指標：**CP**（並標是否勝過 B&H 的 CP）；終值勝 B&H 僅參考",
        f"- 腳本：`python src_scripts/run_momentum_hybrid_backtest.py`",
        "",
        "## 1. 相對「原本評等」有沒有勝過？",
        "",
    ]

    for item in summary_best:
        sym = item["sym"]
        best, base, bh = item["best"], item["grade_base"], item["bh"]
        if sym == "VOO+VXUS":
            lines.append(
                f"- **GEM 宇宙**：全樣本最佳 `{best.get('strategy')}` L={best.get('lookback')} "
                f"CP **{best['cp']:+.1f}**（CAGR {best['cagr']:+.1f}% MDD {best['mdd']:.1f}%）"
            )
            gem12 = next((r for r in all_rows if r.get("id") == "GEM_L252"), None)
            hyb12 = next((r for r in all_rows if r.get("id") == "GEM_hybrid_L252"), None)
            if gem12 and hyb12:
                lines.append(
                    f"  - 純 GEM L252 CP {gem12['cp']:+.1f} vs GEM×評等 L252 CP {hyb12['cp']:+.1f}"
                )
            continue
        g_policy = next(
            (
                r
                for r in all_rows
                if r.get("sym") == sym
                and r.get("strategy") == "grade_ma50"
                and r.get("mode") == POLICY_MODE[sym]
            ),
            None,
        )
        g_b = next(
            (
                r
                for r in all_rows
                if r.get("sym") == sym and r.get("strategy") == "grade_ma50" and r.get("mode") == "B+"
            ),
            None,
        )
        lines.append(f"### {sym}")
        lines.append("")
        lines.append(
            f"| 模型 | CAGR | MDD | CP | vs 政策評等ΔCP | 勝B&H_CP | 買入 | OOS_CP |"
        )
        lines.append("|------|-----:|----:|---:|---------------:|:--------:|-----:|-------:|")
        refs = [bh, g_policy, g_b, best]
        # also best abs and best hybrid
        abs_best = max(
            (r for r in all_rows if r.get("sym") == sym and r.get("strategy") == "abs_mom" and r.get("ok")),
            key=lambda x: x["cp"],
            default=None,
        )
        hy_best = max(
            (r for r in all_rows if r.get("sym") == sym and r.get("strategy") == "hybrid_gate" and r.get("ok")),
            key=lambda x: x["cp"],
            default=None,
        )
        for r in [bh, g_policy, g_b, abs_best, hy_best]:
            if not r:
                continue
            ref_cp = g_policy["cp"] if g_policy else 0
            d = r["cp"] - ref_cp
            o = r.get("oos_2y") or {}
            lines.append(
                f"| {r.get('strategy')} {r.get('mode', '')} L={r.get('lookback', '—')} | "
                f"{r['cagr']:+.1f} | {r['mdd']:.1f} | **{r['cp']:+.1f}** | {d:+.1f} | "
                f"{'Y' if r.get('beat_bh_cp') else 'N'} | {r.get('buys', 0)} | {o.get('cp', '—')} |"
            )
        beat_grade = abs_best and g_policy and abs_best["cp"] > g_policy["cp"]
        beat_hy = hy_best and g_policy and hy_best["cp"] > g_policy["cp"]
        lines.append("")
        lines.append(
            f"- 純動量 vs 政策評等：{'**勝過**' if beat_grade else '未勝過'}；"
            f"混合 gate vs 政策評等：{'**勝過**' if beat_hy else '未勝過'}。"
        )
        if bh:
            lines.append(
                f"- B&H CP {bh['cp']:+.1f}（終值基準）；擇時要贏的是 **CP／MDD**，終值多頭窗常仍輸 B&H。"
            )
        lines.append("")

    lines += [
        "## 2. Lookback 穩健性（純 abs_mom）",
        "",
        "| 商品 | L126 | L189 | L210 | L252 | CP 全正？ | 最佳L |",
        "|------|-----:|-----:|-----:|-----:|:--------:|------:|",
    ]
    for sym in prepared:
        cps = []
        for L in LOOKBACKS:
            r = next(
                (
                    x
                    for x in all_rows
                    if x.get("sym") == sym and x.get("strategy") == "abs_mom" and x.get("lookback") == L
                ),
                None,
            )
            cps.append(r["cp"] if r else None)
        ok_all = all(c is not None and c > 0 for c in cps)
        best_i = int(np.nanargmax([c if c is not None else -1e9 for c in cps]))
        lines.append(
            f"| {sym} | {cps[0]:+.1f} | {cps[1]:+.1f} | {cps[2]:+.1f} | {cps[3]:+.1f} | "
            f"{'Y' if ok_all else 'N'} | {LOOKBACKS[best_i]} |"
        )

    lines += [
        "",
        "## 3. IS→鎖 lookback→OOS（防參數偷看）",
        "",
        "| 商品 | 策略 | 鎖L | OOS CAGR | OOS MDD | OOS CP | B&H OOS CP | 勝B&H_CP |",
        "|------|------|----:|---------:|--------:|-------:|-----------:|:--------:|",
    ]
    for lk in lock_rows:
        lines.append(
            f"| {lk['sym']} | {lk['strategy']} | {lk['locked_lookback']} | "
            f"{lk['oos_cagr']:+.1f} | {lk['oos_mdd']:.1f} | {lk['oos_cp']:+.1f} | "
            f"{lk['bh_oos_cp']:+.1f} | {'Y' if lk['beat_bh_cp_oos'] else 'N'} |"
        )

    lines += [
        "",
        "## 4. 結論（能否超過原本？）",
        "",
    ]

    # auto verdict
    verdicts = []
    for sym in prepared:
        g_policy = next(
            (
                r
                for r in all_rows
                if r.get("sym") == sym
                and r.get("strategy") == "grade_ma50"
                and r.get("mode") == POLICY_MODE[sym]
            ),
            None,
        )
        abs_best = max(
            (r for r in all_rows if r.get("sym") == sym and r.get("strategy") == "abs_mom"),
            key=lambda x: x["cp"],
            default=None,
        )
        hy_best = max(
            (r for r in all_rows if r.get("sym") == sym and r.get("strategy") == "hybrid_gate"),
            key=lambda x: x["cp"],
            default=None,
        )
        if g_policy and abs_best:
            d = abs_best["cp"] - g_policy["cp"]
            verdicts.append((sym, "abs_mom", d, abs_best, g_policy))
        if g_policy and hy_best:
            d = hy_best["cp"] - g_policy["cp"]
            verdicts.append((sym, "hybrid_gate", d, hy_best, g_policy))

    any_win = any(d > 1.0 for _, _, d, _, _ in verdicts)
    lines.append(
        "- **相對原本評等門檻回測：** "
        + ("動量／混合在多檔上 **CP 明顯優於** 評等+ma50。" if any_win else "未見穩定大幅超越。")
    )
    for sym, st, d, best, base in verdicts:
        lines.append(
            f"  - {sym} `{st}` L={best.get('lookback')}: ΔCP {d:+.1f} "
            f"（{best['cp']:+.1f} vs 評等 {base['cp']:+.1f}）"
        )

    lock_win = [lk for lk in lock_rows if lk.get("beat_bh_cp_oos")]
    lines.append(
        f"- **鎖參 OOS 勝 B&H_CP：** {len(lock_win)}/{len(lock_rows)} 組"
        + (" → 有穩健訊號" if lock_win else " → OOS 對 B&H_CP 仍難勝（多頭窗常見）")
    )
    lines.append(
        "- **上線建議：** 若 ΔCP 大且 lookback 全正／鎖參 OOS 不崩，可考慮 "
        "**V／X／Q 袖口用動量（或 GEM）作 on/off，評等只保留加碼語氣**；"
        "G／U／台股核心仍用現行。**暫不自動改 policy。**"
    )
    lines.append("")

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {"generated": now, "rows": all_rows, "locked_oos": lock_rows, "lookbacks": LOOKBACKS},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nWrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
