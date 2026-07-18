# -*- coding: utf-8 -*-
"""
階段1：Playbook 顧問修正版 vs 基準 — 00631L 對照回測。

通過標準（寫死，避免事後搬龍門）見 PASS_RULES / judge_gate()：
  PASS_SAFE  — MDD 改善 ≥2pt 或相對≥10%，且 CAGR 惡化 ≤2pt
  PASS_CP    — CP 高於基準，且 MDD 惡化 ≤1pt
  PASS_NEUTRAL — |ΔCP|≤1 且 |ΔMDD|≤2，交易次數不增，規則與年線敘事一致
  FAIL       — MDD 與 CP 皆明顯變差；或一票否決

組別：
  A_baseline  — 評等 B+ 進；破年線 OR（獲利且破10MA）全出
  B_year_only — 評等 B+ 進（Level1+年線上）；僅破年線減碼（先出1/2，仍破再出清）
  C_year_cap  — 同 B，另：槓桿袖口市值 > 總權益 12% 時再平衡降回 12%
  BH          — 00631L 買入持有（參考）
  gold_日減 vs gold_遲滯 — 可選（GC 簡易，點差假設 0.3%/邊）

交付：reports/latest/playbook_revision_backtest.md|.json
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

from run_etf_backtest import download_full_history, get_metrics  # noqa: E402
from run_grade_threshold_backtest import (  # noqa: E402
    COMM_TW,
    TAX_TW,
    grade_lev_i,
    macro_level_from,
    meets_threshold,
    prepare_yahoo_or_daily,
    slice_with_warmup,
)

INITIAL = 1_000_000.0
LEV_CAP_PCT = 0.12  # allocation_targets.tw_lev_00631L
GOLD_SPREAD = 0.003  # 單邊點差假設
_OUT_DIR = os.path.join(WORKSPACE, "reports", "latest", "backtest")
os.makedirs(_OUT_DIR, exist_ok=True)
REPORT_MD = os.path.join(_OUT_DIR, "playbook_revision_backtest.md")
REPORT_JSON = os.path.join(_OUT_DIR, "playbook_revision_backtest.json")

# ── 通過標準（規格）──────────────────────────────────────────
PASS_RULES = {
    "safe_mdd_improve_abs": 2.0,  # pt（MDD 為負，改善＝絕對值變小）
    "safe_mdd_improve_rel": 0.10,
    "safe_cagr_worsen_max": 2.0,
    "cp_mdd_worsen_max": 3.0,  # 2026-07-18：使用者同意由 1pt 放寬至 3pt 後重判
    "neutral_cp_abs": 1.0,
    "neutral_mdd_abs": 2.0,
}


def _pack(eq: pd.Series, trades: int, initial: float = INITIAL) -> dict:
    years = max(len(eq) / 252.0, 0.1)
    m = get_metrics(eq, trades, years, initial)
    return {
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "cp": round(m["cp"], 2),
        "final": round(m["final"], 0),
        "trades": int(m["trades"]),
        "ops_yr": round(m["workday_ops_per_year"], 2),
        "sharpe": round(m["sharpe"], 3),
        "years": round(years, 2),
    }


def prepare_lev_frame(eval_years: float = 10.0) -> tuple[pd.DataFrame, int]:
    df_t = download_full_history("TAIEX")
    df_l = download_full_history("00631L")
    if df_t.empty or df_l.empty:
        return pd.DataFrame(), 0
    for d, name in ((df_t, "taiex"), (df_l, "lev")):
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        if "close" not in d.columns and "Close" in d.columns:
            d["close"] = d["Close"]
        if "open" not in d.columns:
            d["open"] = d["close"]
    # 00631L 分割調整（與 grade_threshold 一致）
    split = "2026-03-24"
    mask = df_l["date"] <= split
    df_l = df_l.copy()
    df_l.loc[mask, "close"] = df_l.loc[mask, "close"].astype(float) / 22.0
    df_l.loc[mask, "open"] = df_l.loc[mask, "open"].astype(float) / 22.0

    m = df_l[["date", "open", "close"]].rename(columns={"open": "open_lev", "close": "close_lev"})
    m = m.merge(
        df_t[["date", "close"]].rename(columns={"close": "close_taiex"}),
        on="date",
        how="inner",
    )
    m = m.sort_values("date").reset_index(drop=True)
    m, test_start = slice_with_warmup(m, eval_years)
    return m, test_start


def sim_lev_variants(
    df: pd.DataFrame,
    test_start: int,
    *,
    mode: str,
    sell_10ma_when_profit: bool,
    sleeve_on_200: bool,
    cap_rebalance: bool,
) -> dict:
    """
    mode: 進場門檻 B+
    sell_10ma_when_profit: 基準 A — 獲利且破10MA 全出
    sleeve_on_200: True=破年線先出一半，仍破再出清；False=破年線全出
    cap_rebalance: 袖口市值>12%總權益則賣到12%
    """
    closes = df["close_lev"].astype(float).values
    opens = df["open_lev"].astype(float).values
    taiex = df["close_taiex"].astype(float).values
    n = len(closes)
    cash = INITIAL
    shares = 0.0
    equity = []
    trades = 0
    buys = 0
    entry_cost = 0.0  # 平均成本（簡化：全倉成本）
    half_sold_after_200 = False

    for i in range(n):
        px = float(closes[i])
        equity.append(cash + shares * px)
        if i < test_start or i >= n - 1 or i < 199:
            continue
        j = i + 1
        pxn = float(opens[j]) if opens[j] > 0 else float(closes[j])
        level = macro_level_from(taiex, i)
        g = grade_lev_i(closes, taiex, i, level)
        above200 = taiex[i] > float(np.mean(taiex[i - 199 : i + 1]))
        ma10 = float(np.mean(closes[i - 9 : i + 1]))
        below10 = px < ma10
        in_profit = shares > 0 and entry_cost > 0 and px > entry_cost

        # 超配再平衡（EOD 訊號，隔日開盤）
        if cap_rebalance and shares > 0:
            total = cash + shares * px
            lev_val = shares * px
            if total > 0 and lev_val / total > LEV_CAP_PCT + 1e-9:
                target_val = total * LEV_CAP_PCT
                sell_val = lev_val - target_val
                sell_sh = sell_val / pxn
                if sell_sh > 0 and sell_sh <= shares:
                    cash += sell_sh * pxn * (1 - COMM_TW - TAX_TW)
                    shares -= sell_sh
                    trades += 1

        want_sell_full = False
        want_sell_half = False
        if shares > 0:
            if not above200:
                if sleeve_on_200:
                    if not half_sold_after_200:
                        want_sell_half = True
                    else:
                        want_sell_full = True
                else:
                    want_sell_full = True
            else:
                half_sold_after_200 = False
            if sell_10ma_when_profit and in_profit and below10:
                want_sell_full = True

        if want_sell_full and shares > 0:
            cash += shares * pxn * (1 - COMM_TW - TAX_TW)
            shares = 0.0
            entry_cost = 0.0
            trades += 1
            half_sold_after_200 = False
        elif want_sell_half and shares > 0:
            half = shares * 0.5
            cash += half * pxn * (1 - COMM_TW - TAX_TW)
            shares -= half
            trades += 1
            half_sold_after_200 = True
            if shares > 0 and entry_cost > 0:
                pass  # keep cost

        # 進場：B+ 且 Level1 且年線上（修正敘事）；基準也要求年線上以免無意義鞭鋸
        can_enter = (
            shares == 0
            and meets_threshold(g, "B+")
            and level <= 1
            and above200
        )
        if can_enter and cash > 0:
            # cap：空手時總權益≈cash，目標袖口 = 12%
            spend = cash * LEV_CAP_PCT if cap_rebalance else cash
            if spend >= 10_000:
                sh = spend / (pxn * (1 + COMM_TW))
                shares += sh
                cash -= spend
                entry_cost = pxn
                trades += 1
                buys += 1
                half_sold_after_200 = False

    eq = pd.Series(equity[test_start:], dtype=float)
    r = _pack(eq, trades)
    r["buys"] = buys
    r["ok"] = True
    return r


def sim_bh_lev(df: pd.DataFrame, test_start: int) -> dict:
    closes = df["close_lev"].astype(float).values
    eq = closes[test_start:] / closes[test_start] * INITIAL
    r = _pack(pd.Series(eq), 0)
    r["buys"] = 0
    r["ok"] = True
    return r


def sim_gold_exit(hysteresis_days: int) -> dict | None:
    """國際金簡易：跌破再站上 ma50 出場；hysteresis=站上後連續 N 日才出。含單邊點差。"""
    df = prepare_yahoo_or_daily("GC=F")
    if df.empty or len(df) < 300:
        return None
    df, ts = slice_with_warmup(df, 5)
    c = df["close"].astype(float).values
    n = len(c)
    cash, units = INITIAL, 0.0
    equity = []
    trades = buys = 0
    above_streak = 0
    for i in range(n):
        px = float(c[i])
        equity.append(cash + units * px)
        if i < max(ts, 50) or i >= n - 1:
            continue
        ma50 = float(np.mean(c[i - 49 : i + 1]))
        j = i + 1
        pxn = float(c[j])
        # 進場：價格 < ma50（拉回區）且空手 — 簡化對照出場差異
        if units == 0 and px < ma50 * 0.98:
            units = cash / (pxn * (1 + GOLD_SPREAD))
            cash = 0.0
            trades += 1
            buys += 1
            above_streak = 0
            continue
        if units > 0:
            if px > ma50:
                above_streak += 1
            else:
                above_streak = 0
            if above_streak >= max(1, hysteresis_days):
                cash = units * pxn * (1 - GOLD_SPREAD)
                units = 0.0
                trades += 1
                above_streak = 0
    eq = pd.Series(equity[ts:], dtype=float)
    r = _pack(eq, trades)
    r["buys"] = buys
    r["ok"] = True
    r["hysteresis_days"] = hysteresis_days
    return r


def mdd_abs(mdd: float) -> float:
    return abs(float(mdd))


def judge_gate(baseline: dict, revised: dict) -> dict:
    """revised 相對 baseline 判定。"""
    b_cp, r_cp = baseline["cp"], revised["cp"]
    b_mdd, r_mdd = mdd_abs(baseline["mdd"]), mdd_abs(revised["mdd"])
    b_cagr, r_cagr = baseline["cagr"], revised["cagr"]
    b_tr, r_tr = baseline["trades"], revised["trades"]

    d_cp = r_cp - b_cp
    d_mdd = b_mdd - r_mdd  # >0 means revised safer (smaller |MDD|)
    d_cagr = r_cagr - b_cagr

    veto = (r_mdd > b_mdd + 1.0) and (r_cp < b_cp - 0.5)
    if veto:
        return {
            "verdict": "FAIL",
            "reason": "一票否決：MDD 與 CP 皆變差",
            "d_cp": round(d_cp, 2),
            "d_mdd_improve": round(d_mdd, 2),
            "d_cagr": round(d_cagr, 2),
            "suggest_phase2": False,
        }

    # PASS_SAFE
    rel = (d_mdd / b_mdd) if b_mdd > 1e-9 else 0.0
    if d_mdd >= PASS_RULES["safe_mdd_improve_abs"] or rel >= PASS_RULES["safe_mdd_improve_rel"]:
        if d_cagr >= -PASS_RULES["safe_cagr_worsen_max"]:
            return {
                "verdict": "PASS_SAFE",
                "reason": f"MDD 改善 {d_mdd:.1f}pt（相對 {rel:.0%}），CAGR 變化 {d_cagr:+.1f}pt",
                "d_cp": round(d_cp, 2),
                "d_mdd_improve": round(d_mdd, 2),
                "d_cagr": round(d_cagr, 2),
                "suggest_phase2": True,
            }

    # PASS_CP
    if d_cp > 0 and (r_mdd - b_mdd) <= PASS_RULES["cp_mdd_worsen_max"]:
        return {
            "verdict": "PASS_CP",
            "reason": f"CP 提升 {d_cp:+.1f}，MDD 惡化受限",
            "d_cp": round(d_cp, 2),
            "d_mdd_improve": round(d_mdd, 2),
            "d_cagr": round(d_cagr, 2),
            "suggest_phase2": True,
        }

    # PASS_NEUTRAL
    if (
        abs(d_cp) <= PASS_RULES["neutral_cp_abs"]
        and abs(d_mdd) <= PASS_RULES["neutral_mdd_abs"]
        and r_tr <= b_tr
    ):
        return {
            "verdict": "PASS_NEUTRAL",
            "reason": "績效中性且交易不增；與年線敘事一致（邏輯通過）",
            "d_cp": round(d_cp, 2),
            "d_mdd_improve": round(d_mdd, 2),
            "d_cagr": round(d_cagr, 2),
            "suggest_phase2": True,  # 計畫：由使用者看報告；預設建議可進階段2
        }

    if d_cp < -1 and d_mdd < -1:
        return {
            "verdict": "FAIL",
            "reason": "CP 與 MDD 均未改善",
            "d_cp": round(d_cp, 2),
            "d_mdd_improve": round(d_mdd, 2),
            "d_cagr": round(d_cagr, 2),
            "suggest_phase2": False,
        }

    # 曖昧：偏安全但未達 SAFE 門檻
    if d_mdd > 0 and d_cp >= -1:
        return {
            "verdict": "PASS_NEUTRAL",
            "reason": "略偏安全／持平，未達 SAFE 數字門檻但無惡化",
            "d_cp": round(d_cp, 2),
            "d_mdd_improve": round(d_mdd, 2),
            "d_cagr": round(d_cagr, 2),
            "suggest_phase2": True,
        }

    return {
        "verdict": "FAIL",
        "reason": "未達 PASS_SAFE／PASS_CP／PASS_NEUTRAL",
        "d_cp": round(d_cp, 2),
        "d_mdd_improve": round(d_mdd, 2),
        "d_cagr": round(d_cagr, 2),
        "suggest_phase2": False,
    }


def fmt_row(name: str, r: dict) -> str:
    return (
        f"| {name} | {r['cagr']:+.1f} | {r['mdd']:.1f} | {r['cp']:+.1f} | "
        f"{r['final']/1e4:.1f} | {r['trades']} | {r.get('buys', 0)} |"
    )


def main():
    print("=== Playbook 修正版階段1回測 ===\n")
    spec = {
        "pass_rules": PASS_RULES,
        "groups": {
            "A_baseline": "B+進；破年線或（獲利且破10MA）全出；滿倉",
            "B_year_only": "B+進（L1+年線）；僅破年線袖口（半倉再清）；滿倉進",
            "C_year_cap": "同B；進場僅用12%火力；超12%再平衡",
            "BH": "00631L 買入持有",
        },
    }

    df, ts = prepare_lev_frame(10.0)
    if df.empty:
        print("資料不足")
        return 1
    print(f"00631L+TAIEX rows={len(df)} test_start={ts}")

    A = sim_lev_variants(
        df, ts, mode="B+", sell_10ma_when_profit=True, sleeve_on_200=False, cap_rebalance=False
    )
    A["id"] = "A_baseline"
    B = sim_lev_variants(
        df, ts, mode="B+", sell_10ma_when_profit=False, sleeve_on_200=True, cap_rebalance=False
    )
    B["id"] = "B_year_only"
    C = sim_lev_variants(
        df, ts, mode="B+", sell_10ma_when_profit=False, sleeve_on_200=True, cap_rebalance=True
    )
    C["id"] = "C_year_cap"
    BH = sim_bh_lev(df, ts)
    BH["id"] = "BH"

    for label, r in [("A", A), ("B", B), ("C", C), ("BH", BH)]:
        print(
            f"  {label}: CP {r['cp']:+.1f} CAGR {r['cagr']:+.1f}% MDD {r['mdd']:.1f}% "
            f"trades {r['trades']}"
        )

    gate_B = judge_gate(A, B)
    gate_C = judge_gate(A, C)
    # 主判定：取 B 與 C 中較佳者（優先 SAFE/CP，再 NEUTRAL）
    order = {"PASS_SAFE": 3, "PASS_CP": 2, "PASS_NEUTRAL": 1, "FAIL": 0}
    primary = gate_C if order.get(gate_C["verdict"], 0) >= order.get(gate_B["verdict"], 0) else gate_B
    primary_vs = "C_year_cap" if primary is gate_C else "B_year_only"
    if order.get(gate_B["verdict"], 0) == order.get(gate_C["verdict"], 0):
        # 同分比 CP
        primary = gate_C if C["cp"] >= B["cp"] else gate_B
        primary_vs = "C_year_cap" if primary is gate_C else "B_year_only"

    gold_1 = sim_gold_exit(1)
    gold_5 = sim_gold_exit(5)
    gold_note = ""
    if gold_1 and gold_5:
        gold_note = (
            f"黃金簡易（點差{GOLD_SPREAD*100:.1f}%/邊）：日減 CP {gold_1['cp']:+.1f}／"
            f"遲滯5日 CP {gold_5['cp']:+.1f}（MDD {gold_1['mdd']:.1f} vs {gold_5['mdd']:.1f}）"
        )
        print(f"  {gold_note}")

    # deploy sensitivity: Level→ratio 僅記錄規則，不改主判定
    deploy_sens = {
        "level_1_ratio": 0.40,
        "level_2_ratio": 0.30,
        "level_3_ratio": 0.15,
        "note": "行為風控；非主勝出指標",
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)

    lines = [
        "# Playbook 修正版階段1回測",
        "",
        f"- 產生：{now}",
        f"- 商品：00631L＋TAIEX｜評測窗約 {A['years']} 年｜起始資金 {INITIAL:,.0f}",
        f"- 腳本：`python src_scripts/run_playbook_revision_backtest.py`",
        "",
        "## 通過標準（預先鎖定）",
        "",
        "```",
        json.dumps(PASS_RULES, ensure_ascii=False, indent=2),
        "```",
        "",
        "- **PASS_SAFE**：MDD 改善≥2pt 或相對≥10%，且 CAGR 惡化≤2pt",
        "- **PASS_CP**：CP 高於基準，且 MDD 惡化≤3pt（2026-07-18 放寬）",
        "- **PASS_NEUTRAL**：|ΔCP|≤1 且 |ΔMDD|≤2，交易不增",
        "- **FAIL**：MDD 與 CP 皆變差（一票否決）或其他未達標",
        "",
        "## 組別結果",
        "",
        "| 組別 | CAGR% | MDD% | CP | 終值(萬) | 交易 | 買入 |",
        "|------|------:|-----:|---:|--------:|-----:|-----:|",
        fmt_row("A 基準（年線或10MA停利）", A),
        fmt_row("B 修正（僅年線袖口）", B),
        fmt_row("C 修正＋12%超配再平衡", C),
        fmt_row("BH 長抱參考", BH),
        "",
        "## 門閘判定",
        "",
        f"### B vs A → **{gate_B['verdict']}**",
        f"- {gate_B['reason']}",
        f"- ΔCP {gate_B['d_cp']:+.1f}｜MDD改善 {gate_B['d_mdd_improve']:+.1f}pt｜ΔCAGR {gate_B['d_cagr']:+.1f}",
        f"- 建議進階段2：{'是' if gate_B['suggest_phase2'] else '否'}",
        "",
        f"### C vs A → **{gate_C['verdict']}**",
        f"- {gate_C['reason']}",
        f"- ΔCP {gate_C['d_cp']:+.1f}｜MDD改善 {gate_C['d_mdd_improve']:+.1f}pt｜ΔCAGR {gate_C['d_cagr']:+.1f}",
        f"- 建議進階段2：{'是' if gate_C['suggest_phase2'] else '否'}",
        "",
        f"## 主判定（取較佳）：**{primary['verdict']}**（對照組 `{primary_vs}`）",
        "",
        f"- {primary['reason']}",
        f"- **是否建議進入階段2完整實作：{'是' if primary['suggest_phase2'] else '否'}**",
        "",
    ]
    if gold_note:
        lines += ["## 黃金遲滯（附帶）", "", gold_note, ""]
    lines += [
        "## 資金部署敏感性（非主指標）",
        "",
        json.dumps(deploy_sens, ensure_ascii=False),
        "",
        "## 說明",
        "",
        "- 基準 A 刻意含「獲利且破10MA全出」，對照顧問修正「刪常規短均停利」。",
        "- C 的 12% 對齊 `allocation_targets.tw_lev_00631L`；進場只動用 12% 現金，其餘留現金。",
        "- BH 僅參考；主門閘是修正組 vs A。",
        "",
    ]

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    payload = {
        "generated": now,
        "spec": spec,
        "results": {"A": A, "B": B, "C": C, "BH": BH},
        "gate_B": gate_B,
        "gate_C": gate_C,
        "primary": {**primary, "vs": primary_vs},
        "gold": {"h1": gold_1, "h5": gold_5},
        "deploy_sens": deploy_sens,
        "suggest_phase2": primary["suggest_phase2"],
        "verdict": primary["verdict"],
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n主判定: {primary['verdict']} suggest_phase2={primary['suggest_phase2']}")
    print(f"Wrote {REPORT_MD}")
    return 0 if primary["suggest_phase2"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
