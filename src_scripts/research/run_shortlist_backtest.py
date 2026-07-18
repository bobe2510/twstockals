# -*- coding: utf-8 -*-
"""
策略方法目錄 §5.1 短名單回測（vs 現行乖離評等門檻）。

1. 階層濾網：200DMA 多頭 ∩ grade ≥ B+
2. Dual / 絕對動量：VOO／VXUS（±QQQ）
3. Hurst regime：GOLD 切換拉回評等 vs 趨勢
4. USDTWD 動態賣出閾值 vs 固定 +1.5%
5. 黃金長均空倉濾網 + B 袖口 vs 基準

CP = CAGR − 0.25|MDD| − 1.5×年化操作（沿用 get_metrics）。
Walk-forward：全樣本 + 近 2 年 OOS（終值正規化後算 CAGR/MDD）。
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
    GOLD_BUDGET,
    GOLD_LIVE_TRANCHE,
    INITIAL,
    OZ_TO_GRAM,
    align_on_date,
    grade_gold_i,
    grade_growth_us_i,
    grade_pullback_core_i,
    grade_usd_i,
    meets_threshold,
    prepare_us,
    prepare_yahoo_or_daily,
    slice_with_warmup,
)

_OUT_DIR = os.path.join(WORKSPACE, "reports", "latest", "backtest")
os.makedirs(_OUT_DIR, exist_ok=True)
REPORT_MD = os.path.join(_OUT_DIR, "shortlist_backtest.md")
REPORT_JSON = os.path.join(_OUT_DIR, "shortlist_backtest.json")
OOS_BARS = 504  # ~2y


def _pack(m: dict, trades: int, buys: int, years: float, bh: dict | None = None, **extra) -> dict:
    out = {
        "ok": True,
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "sharpe": round(m["sharpe"], 3),
        "final": round(m["final"], 0),
        "cp": round(m["cp"], 2),
        "trades": int(trades),
        "buys": int(buys),
        "ops_yr": round(m["workday_ops_per_year"], 2),
        "years": round(years, 2),
    }
    if bh:
        out["bh_cagr"] = round(bh["cagr"], 2)
        out["bh_mdd"] = round(bh["mdd"], 2)
        out["beat_bh"] = m["final"] > bh["final"]
    out.update(extra)
    return out


def _oos_metrics(equity: list[float], test_start: int, trade_idx: list[int], initial: float) -> dict | None:
    eq = pd.Series(equity[test_start:], dtype=float)
    if len(eq) < OOS_BARS + 20:
        return None
    eq_oos = eq.iloc[-OOS_BARS:].copy()
    scale = initial / float(eq_oos.iloc[0])
    eq_oos = eq_oos * scale
    years = OOS_BARS / 252.0
    # trades whose signal day falls in OOS window (approx by equity index)
    oos_start_i = test_start + len(eq) - OOS_BARS
    n_tr = sum(1 for t in trade_idx if t >= oos_start_i)
    m = get_metrics(eq_oos, n_tr, years, initial)
    return {
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "cp": round(m["cp"], 2),
        "trades": n_tr,
        "years": round(years, 2),
    }


def _finish(equity, trade_closes, test_start, trades, buys, trade_idx, initial=INITIAL, note=""):
    eq = pd.Series(equity[test_start:], dtype=float)
    years = max(len(eq) / 252.0, 0.1)
    m = get_metrics(eq, trades, years, initial)
    bh_s = trade_closes[test_start:] / trade_closes[test_start] * initial
    m_bh = get_metrics(pd.Series(bh_s), 0, years, initial)
    r = _pack(m, trades, buys, years, m_bh, note=note)
    r["oos_2y"] = _oos_metrics(equity, test_start, trade_idx, initial)
    return r


# ── shared all-in loop helpers ──────────────────────────────────────────────


def sim_all_in(
    trade_closes: np.ndarray,
    *,
    test_start: int,
    buy_fn,
    sell_fn,
    initial: float = INITIAL,
    note: str = "",
) -> dict:
    """buy_fn(i)->bool when flat; sell_fn(i)->bool when long. EOD→next close."""
    n = len(trade_closes)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}
    cash, units = initial, 0.0
    equity, trades, buys = [], 0, 0
    trade_idx: list[int] = []
    for i in range(n):
        px = float(trade_closes[i])
        equity.append(cash + units * px)
        if i < test_start or i >= n - 1 or i < 199:
            continue
        j = i + 1
        px_next = float(trade_closes[j])
        if units > 0 and sell_fn(i):
            cash += units * px_next * (1 - COMM_US)
            units = 0.0
            trades += 1
            trade_idx.append(i)
        if units == 0 and buy_fn(i):
            units = cash / (px_next * (1 + COMM_US))
            cash = 0.0
            trades += 1
            buys += 1
            trade_idx.append(i)
    return _finish(equity, trade_closes, test_start, trades, buys, trade_idx, initial, note)


def sim_gold_tranche(
    bot: np.ndarray,
    gold_usd: np.ndarray,
    fx: np.ndarray,
    *,
    test_start: int,
    buy_ok_fn,
    sell_fn,
    tranche_map: dict | None = None,
    budget: float = GOLD_BUDGET,
    note: str = "",
) -> dict:
    """分批加碼；cash 池 = INITIAL，投入上限 budget。"""
    n = len(bot)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}
    tmap = tranche_map or GOLD_LIVE_TRANCHE
    cash, units, invested = INITIAL, 0.0, 0.0
    equity, trades, buys = [], 0, 0
    trade_idx: list[int] = []
    last_buy = -999
    for i in range(n):
        px = float(bot[i])
        equity.append(cash + units * px)
        if i < test_start or i >= n - 1:
            continue
        j = i + 1
        px_next = float(bot[j])
        g = grade_gold_i(gold_usd, fx, i)
        if units > 0 and sell_fn(i):
            cash += units * px_next * (1 - COMM_US)
            units = 0.0
            invested = 0.0
            trades += 1
            trade_idx.append(i)
        if not buy_ok_fn(i, g):
            continue
        room = budget - invested
        suggest = float(tmap.get(g, 0.0) or 0.0)
        if suggest <= 0 or room < 10_000 or cash < 10_000:
            continue
        if i - last_buy < 5 and units > 0:
            continue
        spend = min(suggest, room, cash)
        if spend < 10_000:
            continue
        units += spend / (px_next * (1 + COMM_US))
        cash -= spend
        invested += spend
        trades += 1
        buys += 1
        last_buy = i
        trade_idx.append(i)
    return _finish(equity, bot, test_start, trades, buys, trade_idx, INITIAL, note)


def hurst_rs(x: np.ndarray) -> float:
    """簡化 lagged-std 擬合；~0.5 隨機、>0.55 趨勢、<0.45 均值回歸傾向。"""
    if len(x) < 50:
        return 0.5
    x = np.asarray(x, dtype=float)
    lags, tau = [], []
    for lag in range(2, min(20, len(x) // 4)):
        d = x[lag:] - x[:-lag]
        s = float(np.std(d))
        if s > 1e-12:
            lags.append(lag)
            tau.append(s)
    if len(lags) < 5:
        return 0.5
    return float(np.polyfit(np.log(lags), np.log(tau), 1)[0])


def mom_12m(closes: np.ndarray, i: int) -> float:
    look = 252
    if i < look:
        return 0.0
    a, b = float(closes[i - look]), float(closes[i])
    if a <= 0:
        return 0.0
    return b / a - 1.0


# ── shortlist models ────────────────────────────────────────────────────────


def run_us_hierarchical_and_momentum(prepared: dict[str, tuple[pd.DataFrame, int]]) -> list[dict]:
    rows = []
    for sym, (df, ts) in prepared.items():
        closes = df["close"].astype(float).values
        grade_fn = grade_growth_us_i if sym == "QQQ" else (lambda c, i: grade_pullback_core_i(c, i, 1))

        def make_grade(c=closes, gf=grade_fn):
            return lambda i: meets_threshold(gf(c, i), "B+")

        def sell_ma50(i, c=closes):
            return float(c[i]) < float(np.mean(c[i - 49 : i + 1]))

        b = sim_all_in(closes, test_start=ts, buy_fn=make_grade(), sell_fn=sell_ma50, note=f"{sym} baseline B+")
        b["id"] = f"1_{sym}_baseline_B+"
        rows.append(b)

        h = sim_all_in(
            closes,
            test_start=ts,
            buy_fn=lambda i, c=closes, gf=grade_fn: (
                float(c[i]) > float(np.mean(c[i - 199 : i + 1])) and meets_threshold(gf(c, i), "B+")
            ),
            sell_fn=sell_ma50,
            note=f"{sym} 200DMA∩B+",
        )
        h["id"] = f"1_{sym}_hier_200_B+"
        rows.append(h)

        # absolute momentum 12m
        abs_m = sim_all_in(
            closes,
            test_start=ts,
            buy_fn=lambda i, c=closes: mom_12m(c, i) > 0,
            sell_fn=lambda i, c=closes: mom_12m(c, i) <= 0,
            note=f"{sym} abs mom 12m",
        )
        abs_m["id"] = f"2_{sym}_abs_mom_12m"
        rows.append(abs_m)

    # Dual momentum VOO vs VXUS
    if "VOO" in prepared and "VXUS" in prepared:
        df_v, ts_v = prepared["VOO"]
        df_x, _ = prepared["VXUS"]
        m = df_v.merge(df_x.rename(columns={"close": "vxus", "open": "vxus_o"}), on="date", how="inner")
        m = m.sort_values("date").reset_index(drop=True)
        # reuse VOO test_start proportional
        _, ts = slice_with_warmup(m, 5)
        voo = m["close"].astype(float).values
        vxus = m["vxus"].astype(float).values
        n = len(voo)
        cash, units_v, units_x = INITIAL, 0.0, 0.0
        equity, trades, buys = [], 0, 0
        trade_idx: list[int] = []
        for i in range(n):
            equity.append(cash + units_v * voo[i] + units_x * vxus[i])
            if i < ts or i >= n - 1:
                continue
            j = i + 1
            mv = mom_12m(voo, i)
            mx = mom_12m(vxus, i)
            target = None  # 'voo' | 'vxus' | None
            if mv > 0 or mx > 0:
                target = "voo" if mv >= mx else "vxus"
            # exit wrong sleeve
            if units_v > 0 and target != "voo":
                cash += units_v * voo[j] * (1 - COMM_US)
                units_v = 0.0
                trades += 1
                trade_idx.append(i)
            if units_x > 0 and target != "vxus":
                cash += units_x * vxus[j] * (1 - COMM_US)
                units_x = 0.0
                trades += 1
                trade_idx.append(i)
            if target == "voo" and units_v == 0 and cash > 0:
                units_v = cash / (voo[j] * (1 + COMM_US))
                cash = 0.0
                trades += 1
                buys += 1
                trade_idx.append(i)
            elif target == "vxus" and units_x == 0 and cash > 0:
                units_x = cash / (vxus[j] * (1 + COMM_US))
                cash = 0.0
                trades += 1
                buys += 1
                trade_idx.append(i)
        # synthetic trade series for BH = VOO
        r = _finish(equity, voo, ts, trades, buys, trade_idx, INITIAL, "Dual mom VOO↔VXUS")
        r["id"] = "2_dual_mom_VOO_VXUS"
        rows.append(r)
    return rows


def run_hurst_gold(bot, gold_usd, fx, ts) -> list[dict]:
    """§5.1-3：Hurst regime on GOLD。"""
    H_WIN = 100
    h_cache = {}

    def H(i):
        if i in h_cache:
            return h_cache[i]
        if i < H_WIN:
            h_cache[i] = 0.5
        else:
            h_cache[i] = hurst_rs(gold_usd[i - H_WIN + 1 : i + 1])
        return h_cache[i]

    def sell_ma50(i):
        return float(gold_usd[i]) > float(np.mean(gold_usd[i - 49 : i + 1]))

    def buy_regime(i):
        h = H(i)
        g = grade_gold_i(gold_usd, fx, i)
        ma50 = float(np.mean(gold_usd[i - 49 : i + 1]))
        px = float(gold_usd[i])
        if h < 0.45:
            return meets_threshold(g, "B+")
        if h > 0.55:
            return px > ma50
        return False  # mid: no new buys

    def sell_regime(i):
        h = H(i)
        ma50 = float(np.mean(gold_usd[i - 49 : i + 1]))
        px = float(gold_usd[i])
        if h < 0.45:
            return sell_ma50(i)
        if h > 0.55:
            return px < ma50
        return sell_ma50(i)  # mid: keep baseline exit

    base = sim_all_in(
        bot,
        test_start=ts,
        buy_fn=lambda i: meets_threshold(grade_gold_i(gold_usd, fx, i), "B+"),
        sell_fn=sell_ma50,
        note="GOLD baseline B+ (hurst ctrl)",
    )
    base["id"] = "3_gold_baseline_B+"
    reg = sim_all_in(bot, test_start=ts, buy_fn=buy_regime, sell_fn=sell_regime, note="GOLD Hurst regime")
    reg["id"] = "3_gold_hurst_regime"
    return [base, reg]


def run_usd_dynamic(fx_c: np.ndarray, ts: int) -> list[dict]:
    """§5.1-4：固定 +1.5% vs σ／分位／袖口。"""
    rows = []

    def bias(i):
        ma = float(np.mean(fx_c[i - 199 : i + 1]))
        return (float(fx_c[i]) - ma) / ma * 100

    def buy_b(i):
        return meets_threshold(grade_usd_i(fx_c, i), "B+")

    # 1) full exit @ +1.5%
    r1 = sim_all_in(
        fx_c,
        test_start=ts,
        buy_fn=buy_b,
        sell_fn=lambda i: bias(i) >= 1.5,
        note="USD sell fixed +1.5%",
    )
    r1["id"] = "4_usd_sell_fixed_1p5"
    rows.append(r1)

    # 2) sigma threshold floor 1.5
    def sell_sigma(i):
        if i < 60:
            return bias(i) >= 1.5
        bs = np.array([bias(k) for k in range(i - 59, i + 1)])
        thr = max(1.5, float(np.mean(bs) + 1.0 * np.std(bs)))
        return bias(i) >= thr

    r2 = sim_all_in(fx_c, test_start=ts, buy_fn=buy_b, sell_fn=sell_sigma, note="USD sell μ+1σ (floor 1.5)")
    r2["id"] = "4_usd_sell_sigma"
    rows.append(r2)

    # 3) percentile of last 252 bias
    def sell_pct(i):
        if i < 252:
            return bias(i) >= 1.5
        bs = np.array([bias(k) for k in range(i - 251, i + 1)])
        thr = max(1.5, float(np.percentile(bs, 75)))
        return bias(i) >= thr

    r3 = sim_all_in(fx_c, test_start=ts, buy_fn=buy_b, sell_fn=sell_pct, note="USD sell P75 bias (floor 1.5)")
    r3["id"] = "4_usd_sell_p75"
    rows.append(r3)

    # 4) sleeve: 50% @1.5, rest @3.0
    n = len(fx_c)
    cash, units = INITIAL, 0.0
    equity, trades, buys = [], 0, 0
    trade_idx: list[int] = []
    sold_half = False
    for i in range(n):
        px = float(fx_c[i])
        equity.append(cash + units * px)
        if i < ts or i >= n - 1:
            continue
        j = i + 1
        px_next = float(fx_c[j])
        b = bias(i)
        if units > 0:
            if b >= 3.0:
                cash += units * px_next * (1 - COMM_US)
                units = 0.0
                sold_half = False
                trades += 1
                trade_idx.append(i)
            elif b >= 1.5 and not sold_half:
                half = units * 0.5
                cash += half * px_next * (1 - COMM_US)
                units -= half
                sold_half = True
                trades += 1
                trade_idx.append(i)
            elif b < 1.5:
                sold_half = False
        if units == 0 and buy_b(i):
            units = cash / (px_next * (1 + COMM_US))
            cash = 0.0
            sold_half = False
            trades += 1
            buys += 1
            trade_idx.append(i)
    r4 = _finish(equity, fx_c, ts, trades, buys, trade_idx, INITIAL, "USD sleeve 50%@1.5 / 100%@3.0")
    r4["id"] = "4_usd_sell_sleeve"
    rows.append(r4)
    return rows


def run_gold_long_ma_filter(bot, gold_usd, fx, ts) -> list[dict]:
    """§5.1-5：僅在長均多頭允許買；跌破 200 或破 50MA 賣。"""
    rows = []

    def above200(i):
        return float(gold_usd[i]) > float(np.mean(gold_usd[i - 199 : i + 1]))

    def sell_base(i):
        return float(gold_usd[i]) > float(np.mean(gold_usd[i - 49 : i + 1]))

    def sell_or_200(i):
        return sell_base(i) or (not above200(i))

    # all-in baseline
    a = sim_all_in(
        bot,
        test_start=ts,
        buy_fn=lambda i: meets_threshold(grade_gold_i(gold_usd, fx, i), "B+"),
        sell_fn=sell_base,
        note="GOLD all-in B+",
    )
    a["id"] = "5_gold_allin_B+"
    rows.append(a)

    b = sim_all_in(
        bot,
        test_start=ts,
        buy_fn=lambda i: above200(i) and meets_threshold(grade_gold_i(gold_usd, fx, i), "B+"),
        sell_fn=sell_or_200,
        note="GOLD longMA filter all-in B+",
    )
    b["id"] = "5_gold_longMA_allin_B+"
    rows.append(b)

    # tranche baseline vs longMA
    t0 = sim_gold_tranche(
        bot,
        gold_usd,
        fx,
        test_start=ts,
        buy_ok_fn=lambda i, g: meets_threshold(g, "B+"),
        sell_fn=sell_base,
        note="GOLD tranche B+ live map",
    )
    t0["id"] = "5_gold_tranche_B+"
    rows.append(t0)

    t1 = sim_gold_tranche(
        bot,
        gold_usd,
        fx,
        test_start=ts,
        buy_ok_fn=lambda i, g: above200(i) and meets_threshold(g, "B+"),
        sell_fn=sell_or_200,
        note="GOLD longMA + tranche B+",
    )
    t1["id"] = "5_gold_longMA_tranche_B+"
    rows.append(t1)
    return rows


def fmt_row(r: dict) -> str:
    if not r.get("ok"):
        return f"| `{r.get('id','?')}` | FAIL | — | — | — | — | — |"
    oos = r.get("oos_2y") or {}
    oos_s = f"{oos.get('cagr', '—'):+}|{oos.get('mdd', '—')}|{oos.get('cp', '—')}" if oos else "—"
    beat = "Y" if r.get("beat_bh") else "N"
    return (
        f"| `{r['id']}` | {r.get('note','')} | {r['cagr']:+.1f} | {r['mdd']:.1f} | "
        f"{r['cp']:+.1f} | {r['buys']} | {r['final']/1e4:.1f} | {beat} | {oos_s} |"
    )


def write_reports(all_rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 短名單回測（策略目錄 §5.1）",
        "",
        f"- 產生時間：{now}",
        f"- 起始資金：{INITIAL:,.0f}（黃金分批投入上限 {GOLD_BUDGET:,.0f}）",
        f"- CP：`CAGR − 0.25|MDD| − 1.5×年化操作`；OOS ≈ 近 {OOS_BARS} 根（~2y）",
        f"- 執行：`python src_scripts/run_shortlist_backtest.py`",
        "",
        "## 結果總表",
        "",
        "| id | 說明 | CAGR% | MDD% | CP | 買入次 | 終值(萬) | 勝B&H | OOS CAGR\\|MDD\\|CP |",
        "|----|------|------:|-----:|---:|------:|--------:|:-----:|-------------------|",
    ]
    for r in all_rows:
        lines.append(fmt_row(r))

    # per-group winners by CP
    lines += ["", "## 分組冠軍（全樣本 CP）", ""]
    groups = {
        "1 階層濾網": [r for r in all_rows if r.get("id", "").startswith("1_")],
        "2 動量": [r for r in all_rows if r.get("id", "").startswith("2_")],
        "3 Hurst": [r for r in all_rows if r.get("id", "").startswith("3_")],
        "4 美金賣出": [r for r in all_rows if r.get("id", "").startswith("4_")],
        "5 黃金長均": [r for r in all_rows if r.get("id", "").startswith("5_")],
    }
    for title, rs in groups.items():
        ok = [r for r in rs if r.get("ok")]
        if not ok:
            lines.append(f"- **{title}**：無有效結果")
            continue
        best = max(ok, key=lambda x: x.get("cp", -1e9))
        lines.append(
            f"- **{title}**：`{best['id']}` — CP {best['cp']:+.1f}｜"
            f"CAGR {best['cagr']:+.1f}%｜MDD {best['mdd']:.1f}%｜{best.get('note','')}"
        )

    lines += [
        "",
        "## 解讀注意",
        "",
        "- 未寫入 live policy；僅研究對照。",
        "- Hurst 為簡化估計，對窗長敏感；OOS 若翻負號則勿上線。",
        "- 美金袖口模型的「操作次數」偏高（半倉也算一筆），CP 會懲罰。",
        "- Dual Momentum 的 B&H 對照為同期 VOO。",
        "",
    ]
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({"generated": now, "rows": all_rows}, f, ensure_ascii=False, indent=2)
    print(f"Wrote {REPORT_MD}")
    print(f"Wrote {REPORT_JSON}")


def main():
    print("=== 短名單回測 §5.1 ===\n")
    all_rows: list[dict] = []

    df_gold = prepare_yahoo_or_daily("GC=F")
    df_fx = prepare_yahoo_or_daily("USDTWD=X")
    if df_gold.empty or df_fx.empty:
        print("黃金/匯率資料不足")
        return 1

    aligned = align_on_date(
        df_gold.rename(columns={"close": "gold", "open": "gold_o"}),
        df_fx[["date", "close"]],
        "fx",
    )
    aligned, ts_g = slice_with_warmup(aligned, 5)
    gold_usd = aligned["gold"].astype(float).values
    fx = aligned["fx"].astype(float).values
    bot = gold_usd * fx / OZ_TO_GRAM
    print(f"GOLD aligned {len(aligned)} rows, test_start={ts_g}")

    # 1 gold hierarchical
    def sell_g(i):
        return float(gold_usd[i]) > float(np.mean(gold_usd[i - 49 : i + 1]))

    r = sim_all_in(
        bot,
        test_start=ts_g,
        buy_fn=lambda i: meets_threshold(grade_gold_i(gold_usd, fx, i), "B+"),
        sell_fn=sell_g,
        note="GOLD baseline B+",
    )
    r["id"] = "1_gold_baseline_B+"
    all_rows.append(r)
    r = sim_all_in(
        bot,
        test_start=ts_g,
        buy_fn=lambda i: (
            float(gold_usd[i]) > float(np.mean(gold_usd[i - 199 : i + 1]))
            and meets_threshold(grade_gold_i(gold_usd, fx, i), "B+")
        ),
        sell_fn=sell_g,
        note="GOLD 200DMA∩B+",
    )
    r["id"] = "1_gold_hier_200_B+"
    all_rows.append(r)

    # US symbols for 1+2
    prepared = {}
    for sym in ("VOO", "VXUS", "QQQ"):
        df = prepare_us(sym)
        if df.empty:
            print(f"{sym}: empty")
            continue
        df, start = slice_with_warmup(df, 5)
        prepared[sym] = (df, start)
        print(f"{sym}: {len(df)} rows, test_start={start}")

    all_rows.extend(run_us_hierarchical_and_momentum(prepared))
    all_rows.extend(run_hurst_gold(bot, gold_usd, fx, ts_g))

    fx_df, ts_fx = slice_with_warmup(df_fx, 5)
    fx_c = fx_df["close"].astype(float).values
    print(f"USDTWD: {len(fx_df)} rows, test_start={ts_fx}")
    all_rows.extend(run_usd_dynamic(fx_c, ts_fx))
    all_rows.extend(run_gold_long_ma_filter(bot, gold_usd, fx, ts_g))

    # print summary
    for r in all_rows:
        if not r.get("ok"):
            print(f"  FAIL {r}")
            continue
        oos = r.get("oos_2y")
        oos_s = f"OOS CP {oos['cp']:+.1f}" if oos else "OOS n/a"
        print(
            f"  {r['id']:32s} CP {r['cp']:+7.1f}  CAGR {r['cagr']:+6.1f}%  "
            f"MDD {r['mdd']:6.1f}%  buys {r['buys']:3d}  {oos_s}"
        )

    write_reports(all_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
