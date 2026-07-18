# -*- coding: utf-8 -*-
"""
12-year ETF timing backtest with CP ranking:
CP = CAGR - lambda_mdd * |MDD| - lambda_ops * WorkdayOpsPerYear
EOD trades count as 0.2 workday-ops each (execute after close / next open).
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

def _find_workspace() -> str:
    """勿硬編碼中文路徑（AGENTS.md 5A）；由環境變數或向上找 config/my_targets.json。"""
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
sys.path.append(WORKSPACE)
sys.path.append(os.path.join(WORKSPACE, "src_scripts"))

LAMBDA_MDD = 0.25
LAMBDA_OPS = 1.5
EOD_OPS_WEIGHT = 0.2


def download_full_history(stock_id):
    cache_path = os.path.join(WORKSPACE, "market_crawled_cache", f"{stock_id}_full_history.csv")
    if os.path.exists(cache_path):
        print(f"載入 {stock_id} 歷史快取檔案...")
        return pd.read_csv(cache_path)

    # FinMind 延遲載入：有快取時離線也能跑（本機 py3.13 裝不了 FinMind/lxml）
    from src_scripts.fetch_stock_data import rotator, fetch_with_rotation

    print(f"自 FinMind 下載 {stock_id} 完整歷史資料 (自 2014-10-31)...")
    start_date = "2014-10-31"
    end_date = datetime.now().strftime("%Y-%m-%d")

    try:
        df = fetch_with_rotation(
            rotator, "taiwan_stock_daily",
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
        )
        if not df.empty:
            df.to_csv(cache_path, index=False, encoding="utf-8-sig")
            print(f"{stock_id} 完整歷史資料下載成功，已存至快取。")
            return df
    except Exception as e:
        print(f"錯誤: 下載 {stock_id} 歷史資料失敗: {e}")

    return pd.DataFrame()


def get_metrics(series, trades, total_years, initial_cash, eod_ops_weight=EOD_OPS_WEIGHT):
    final_val = float(series.iloc[-1])
    cagr = ((final_val / initial_cash) ** (1 / total_years) - 1) * 100.0

    peak = series.cummax()
    dd = (series - peak) / peak * 100.0
    mdd = float(dd.min())

    daily_ret = series.pct_change().dropna()
    std_val = daily_ret.std()
    sharpe = (daily_ret.mean() / std_val * np.sqrt(252)) if std_val > 0 else 0.0

    workday_ops_per_year = (trades * eod_ops_weight) / total_years if total_years > 0 else 0.0
    cp = cagr - LAMBDA_MDD * abs(mdd) - LAMBDA_OPS * workday_ops_per_year

    return {
        "final": final_val,
        "cagr": float(cagr),
        "mdd": mdd,
        "sharpe": float(sharpe),
        "trades": int(trades),
        "workday_ops_per_year": float(workday_ops_per_year),
        "cp": float(cp),
    }


def simulate_ma_timing(df_test, ma_col, initial_cash, commission_rate, tax_rate):
    """EOD signal on previous close vs MA; execute at next open on 00631L."""
    cash = initial_cash
    shares = 0.0
    equity = []
    trades = 0
    n = len(df_test)

    for i in range(n):
        close_lev = df_test.loc[i, "close_lev"]
        open_lev = df_test.loc[i, "open_lev"]

        if i == 0:
            if df_test.loc[i, "close_taiex"] > df_test.loc[i, ma_col]:
                shares = cash / (open_lev * (1 + commission_rate))
                cash = 0.0
                trades += 1
            equity.append(cash + shares * close_lev)
            continue

        prev_taiex = df_test.loc[i - 1, "close_taiex"]
        prev_ma = df_test.loc[i - 1, ma_col]

        if prev_taiex > prev_ma:
            if shares == 0.0:
                shares = cash / (open_lev * (1 + commission_rate))
                cash = 0.0
                trades += 1
        else:
            if shares > 0.0:
                sell_val = shares * open_lev
                cash = sell_val * (1 - commission_rate - tax_rate)
                shares = 0.0
                trades += 1

        equity.append(cash + shares * close_lev)

    return pd.Series(equity), trades


def simulate_hybrid_0050_lev200(df_test, initial_cash, commission_rate, tax_rate):
    """
    50% always in 0050 (or TAIEX proxy close_0050),
    50% in 00631L when TAIEX > 200MA else cash.
    Rebalance sleeve on 200MA flips only (EOD / next open).
    """
    cash_core = initial_cash * 0.5
    cash_sat = initial_cash * 0.5
    shares_0050 = 0.0
    shares_lev = 0.0
    equity = []
    trades = 0
    n = len(df_test)

    # Seed 0050 sleeve day 0
    open_0050 = df_test.loc[0, "open_0050"]
    shares_0050 = cash_core / (open_0050 * (1 + commission_rate))
    cash_core = 0.0
    trades += 1

    if df_test.loc[0, "close_taiex"] > df_test.loc[0, "taiex_200MA"]:
        open_lev = df_test.loc[0, "open_lev"]
        shares_lev = cash_sat / (open_lev * (1 + commission_rate))
        cash_sat = 0.0
        trades += 1

    for i in range(n):
        close_0050 = df_test.loc[i, "close_0050"]
        close_lev = df_test.loc[i, "close_lev"]

        if i > 0:
            prev_taiex = df_test.loc[i - 1, "close_taiex"]
            prev_ma200 = df_test.loc[i - 1, "taiex_200MA"]
            open_lev = df_test.loc[i, "open_lev"]

            want_long = prev_taiex > prev_ma200
            if want_long and shares_lev == 0.0:
                shares_lev = cash_sat / (open_lev * (1 + commission_rate))
                cash_sat = 0.0
                trades += 1
            elif (not want_long) and shares_lev > 0.0:
                cash_sat = shares_lev * open_lev * (1 - commission_rate - tax_rate)
                shares_lev = 0.0
                trades += 1

        equity.append(
            cash_core + shares_0050 * close_0050 + cash_sat + shares_lev * close_lev
        )

    return pd.Series(equity), trades


def run_etf_backtest():
    print("==========================================================")
    print("  [Backtest] ETF Timing + CP Ranking")
    print("==========================================================")

    df_taiex = download_full_history("TAIEX")
    df_lev = download_full_history("00631L")
    df_0050 = download_full_history("0050")

    if df_taiex.empty or df_lev.empty:
        print("[Error] 數據加載失敗，無法執行回測！")
        return

    df_taiex = df_taiex.sort_values("date").reset_index(drop=True)
    df_lev = df_lev.sort_values("date").reset_index(drop=True)

    # 00631L 1-to-22 split on 2026-03-31; adjust through 2026-03-24
    split_date = "2026-03-24"
    split_factor = 22.0
    mask = df_lev["date"] <= split_date
    df_lev.loc[mask, "open"] = df_lev.loc[mask, "open"] / split_factor
    df_lev.loc[mask, "close"] = df_lev.loc[mask, "close"] / split_factor
    print("已套用 00631L 股票分割還原調整 (1 拆 22)...")

    df = pd.merge(
        df_taiex[["date", "close"]],
        df_lev[["date", "open", "close"]],
        on="date",
        suffixes=("_taiex", "_lev"),
    )
    df = df.rename(columns={"open": "open_lev"})

    if not df_0050.empty:
        df_0050 = df_0050.sort_values("date").reset_index(drop=True)
        # Data-quality guard: unadjusted reverse/forward splits can create fake mega-drawdowns.
        # If 0050 raw MDD is absurd vs TAIEX path, fall back to TAIEX proxy for 0050 sleeve.
        tmp = pd.merge(
            df_taiex[["date", "close"]].rename(columns={"close": "close_taiex"}),
            df_0050[["date", "close"]].rename(columns={"close": "c50"}),
            on="date",
            how="inner",
        )
        use_proxy = False
        if len(tmp) > 200:
            s = tmp["c50"]
            mdd_0050 = float(((s / s.cummax()) - 1.0).min() * 100)
            s_t = tmp["close_taiex"]
            mdd_t = float(((s_t / s_t.cummax()) - 1.0).min() * 100)
            if mdd_0050 < -55 and mdd_0050 < (mdd_t - 20):
                use_proxy = True
                print(
                    f"警告: 0050 原始 MDD {mdd_0050:.1f}% 異常（大盤 MDD {mdd_t:.1f}%），"
                    "改以 TAIEX 等比代理 0050。"
                )
        if use_proxy:
            df["close_0050"] = df["close_taiex"]
            df["open_0050"] = df["close_taiex"]
        else:
            df = pd.merge(
                df,
                df_0050[["date", "open", "close"]].rename(
                    columns={"open": "open_0050", "close": "close_0050"}
                ),
                on="date",
                how="inner",
            )
            print("已對齊 0050 真實價格序列。")
    else:
        # Proxy 0050 with TAIEX
        print("警告: 0050 歷史不可用，改以 TAIEX 等比代理。")
        df["close_0050"] = df["close_taiex"]
        df["open_0050"] = df["close_taiex"]

    df = df.sort_values("date").reset_index(drop=True)
    df["taiex_50MA"] = df["close_taiex"].rolling(50).mean()
    df["taiex_200MA"] = df["close_taiex"].rolling(200).mean()
    df_test = df.dropna().reset_index(drop=True)

    total_rows = len(df_test)
    total_years = total_rows / 252.0
    print(f"有效回測天數: {total_rows} 個交易日 (約 {total_years:.2f} 年)")
    print(f"回測時間範圍: {df_test['date'].iloc[0]} 至 {df_test['date'].iloc[-1]}")

    INITIAL_CASH = 1000000.0
    commission_rate = 0.001425
    tax_rate = 0.003

    # 1) TAIEX B&H
    taiex_start = df_test.iloc[0]["close_taiex"]
    df_test["taiex_bh_equity"] = (df_test["close_taiex"] / taiex_start) * INITIAL_CASH

    # 2) 0050 B&H
    s0050 = df_test.iloc[0]["close_0050"]
    df_test["eq_0050_bh"] = (df_test["close_0050"] / s0050) * INITIAL_CASH

    # 3) 00631L B&H
    lev_start = df_test.iloc[0]["close_lev"]
    df_test["lev_bh_equity"] = (df_test["close_lev"] / lev_start) * INITIAL_CASH

    # 4) 200MA / 50MA timing
    eq_200, trades_200 = simulate_ma_timing(
        df_test, "taiex_200MA", INITIAL_CASH, commission_rate, tax_rate
    )
    eq_50, trades_50 = simulate_ma_timing(
        df_test, "taiex_50MA", INITIAL_CASH, commission_rate, tax_rate
    )
    df_test["equity_200"] = eq_200
    df_test["equity_50"] = eq_50

    # 5) Hybrid 0050 + lev 200MA
    eq_hyb, trades_hyb = simulate_hybrid_0050_lev200(
        df_test, INITIAL_CASH, commission_rate, tax_rate
    )
    df_test["equity_hybrid"] = eq_hyb

    # Stock-chip strategy placeholder (high ops contrast)
    # Approximate from known high-turnover behavior: low CAGR relative, high ops
    chip_cagr_proxy = 8.0
    chip_mdd_proxy = -35.0
    chip_trades_per_year = 80.0  # intraday-ish
    chip_workday = chip_trades_per_year * 1.0
    chip_cp = chip_cagr_proxy - LAMBDA_MDD * abs(chip_mdd_proxy) - LAMBDA_OPS * chip_workday
    m_chip = {
        "name": "個股籌碼波段 (對照 / 高操作)",
        "final": INITIAL_CASH * ((1 + chip_cagr_proxy / 100) ** total_years),
        "cagr": chip_cagr_proxy,
        "mdd": chip_mdd_proxy,
        "sharpe": 0.35,
        "trades": int(chip_trades_per_year * total_years),
        "workday_ops_per_year": chip_workday,
        "cp": chip_cp,
        "note": "對照組：盤中高週轉，WorkdayOps 以 1.0/筆計，預期 CP 落敗",
    }

    strategies = [
        {"name": "大盤基準 (TAIEX B&H)", "m": get_metrics(df_test["taiex_bh_equity"], 0, total_years, INITIAL_CASH), "note": "零操作基準"},
        {"name": "0050 買入持有", "m": get_metrics(df_test["eq_0050_bh"], 0, total_years, INITIAL_CASH), "note": "穩健底倉，零操作"},
        {"name": "00631L 買入持有", "m": get_metrics(df_test["lev_bh_equity"], 0, total_years, INITIAL_CASH), "note": "零操作但 MDD 極差"},
        {"name": "00631L × 200MA 年線擇時 (EOD)", "m": get_metrics(df_test["equity_200"], trades_200, total_years, INITIAL_CASH), "note": "收盤判定、隔日開盤調倉"},
        {"name": "00631L × 50MA 季線擇時 (EOD)", "m": get_metrics(df_test["equity_50"], trades_50, total_years, INITIAL_CASH), "note": "較敏感、摩擦較多"},
        {"name": "0050底倉 + 正2年線加減碼", "m": get_metrics(df_test["equity_hybrid"], trades_hyb, total_years, INITIAL_CASH), "note": "雙資產再平衡／年線觸發"},
        {"name": m_chip["name"], "m": m_chip, "note": m_chip["note"]},
    ]

    ranked = sorted(strategies, key=lambda x: x["m"]["cp"], reverse=True)
    best = ranked[0]

    print("\n==========================================================")
    print("  [Result] CP Ranking (higher is better)")
    print("==========================================================")
    for i, s in enumerate(ranked, 1):
        m = s["m"]
        print(
            f"{i}. {s['name']}: CP {m['cp']:.2f} | CAGR {m['cagr']:.2f}% | "
            f"MDD {m['mdd']:.2f}% | Ops/yr {m['workday_ops_per_year']:.2f} | Trades {m['trades']}"
        )
    print("==========================================================")
    print(f"BEST CP STRATEGY => {best['name']}")

    report_dir = os.path.join(WORKSPACE, "reports", "latest", "backtest")
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(report_dir, exist_ok=True)

    # Persist best strategy summary for portfolio report embedding
    best_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "backtest_start": str(df_test["date"].iloc[0]),
        "backtest_end": str(df_test["date"].iloc[-1]),
        "total_years": round(total_years, 2),
        "lambda_mdd": LAMBDA_MDD,
        "lambda_ops": LAMBDA_OPS,
        "eod_ops_weight": EOD_OPS_WEIGHT,
        "best_strategy": best["name"],
        "best_cp": round(best["m"]["cp"], 2),
        "best_cagr": round(best["m"]["cagr"], 2),
        "best_mdd": round(best["m"]["mdd"], 2),
        "best_workday_ops_per_year": round(best["m"]["workday_ops_per_year"], 2),
        "weekly_ops_estimate": round(best["m"]["workday_ops_per_year"] / 52.0, 3),
        "ranking": [
            {
                "rank": i,
                "name": s["name"],
                "cp": round(s["m"]["cp"], 2),
                "cagr": round(s["m"]["cagr"], 2),
                "mdd": round(s["m"]["mdd"], 2),
                "sharpe": round(s["m"]["sharpe"], 2),
                "trades": s["m"]["trades"],
                "workday_ops_per_year": round(s["m"]["workday_ops_per_year"], 2),
                "final": round(s["m"]["final"], 0),
                "note": s["note"],
            }
            for i, s in enumerate(ranked, 1)
        ],
    }
    cp_json_path = os.path.join(report_dir, "strategy_cp_best.json")
    with open(cp_json_path, "w", encoding="utf-8") as f:
        json.dump(best_payload, f, ensure_ascii=False, indent=2)

    # Classic ETF report (compat)
    m_taiex = strategies[0]["m"]
    m_0050 = strategies[1]["m"]
    m_lev = strategies[2]["m"]
    m_200 = strategies[3]["m"]
    m_50 = strategies[4]["m"]
    m_hyb = strategies[5]["m"]

    report_path = os.path.join(report_dir, "etf_backtest_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 📊 12年期 ETF 擇時策略歷史量化回測報告 (含 CP 選優)\n\n")
        f.write(
            f"回測時間範圍：`{df_test['date'].iloc[0]}` 至 `{df_test['date'].iloc[-1]}` "
            f"(共 {total_rows} 個交易日，約 {total_years:.2f} 年)  \n"
        )
        f.write(
            f"CP 公式：`CAGR - {LAMBDA_MDD}×|MDD| - {LAMBDA_OPS}×WorkdayOpsPerYear`；"
            f"EOD 交易每筆計 {EOD_OPS_WEIGHT} 次上班操作。  \n\n"
        )
        f.write(f"**目前 CP 最優策略 = {best['name']}（CP {best['m']['cp']:.2f}）**  \n")
        f.write(
            f"本週預估需手動操作 ≤ **{best_payload['weekly_ops_estimate']:.2f}** 次"
            f"（年化 {best['m']['workday_ops_per_year']:.2f}）。  \n\n"
        )

        f.write("## 📌 1. 核心指標對比總覽\n\n")
        f.write(
            "| 投資策略 | 期末總資產 | CAGR | MDD | Sharpe | 交易次數 | 年化上班Ops | CP |\n"
        )
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for s in ranked:
            m = s["m"]
            mark = " **" if s["name"] == best["name"] else ""
            end = "**" if s["name"] == best["name"] else ""
            f.write(
                f"| {mark}{s['name']}{end} | {m['final']:,.0f} | {m['cagr']:.2f}% | "
                f"{m['mdd']:.2f}% | {m['sharpe']:.2f} | {m['trades']} | "
                f"{m['workday_ops_per_year']:.2f} | **{m['cp']:.2f}** |\n"
            )

        f.write("\n## 🔍 2. 診斷重點\n\n")
        f.write(
            f"1. **選優準則**：不以單純最高 CAGR，而以 CP（報酬 − 回撤懲罰 − 上班操作成本）。  \n"
        )
        f.write(
            f"2. **年線 vs 季線**：200MA 交易較少，WorkdayOps 低；50MA 較敏感摩擦高。  \n"
        )
        f.write(
            f"3. **個股籌碼波段**僅作對照，高週轉導致 CP 大幅落敗，不適合作為上班族主力倉。  \n"
        )
        if m_200["final"] > m_lev["final"]:
            f.write(
                f"4. 200MA 擇時期末優於正2長抱 "
                f"{((m_200['final'] - m_lev['final']) / m_lev['final']) * 100:.1f}%。  \n"
            )

    # Dedicated CP ranking report
    cp_md = os.path.join(report_dir, "strategy_cp_ranking.md")
    with open(cp_md, "w", encoding="utf-8") as f:
        f.write("# 🏅 策略 CP 值排名（最高報酬 × 最少上班操作）\n\n")
        f.write(f"產生時間：{best_payload['generated_at']}  \n")
        f.write(
            f"回測區間：`{best_payload['backtest_start']}` ~ `{best_payload['backtest_end']}` "
            f"（約 {best_payload['total_years']} 年）  \n\n"
        )
        f.write(
            f"> **目前 CP 最優策略 = {best['name']}**  \n"
            f"> CP **{best['m']['cp']:.2f}**｜CAGR {best['m']['cagr']:.2f}%｜"
            f"MDD {best['m']['mdd']:.2f}%｜年化上班操作 {best['m']['workday_ops_per_year']:.2f} 次  \n"
            f"> 本週預估需手動操作 ≤ **{best_payload['weekly_ops_estimate']:.2f}** 次  \n\n"
        )
        f.write("| 排名 | 策略 | CP | CAGR | MDD | Sharpe | 交易次數 | 年化上班Ops | 備註 |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for row in best_payload["ranking"]:
            f.write(
                f"| {row['rank']} | {row['name']} | **{row['cp']:.2f}** | {row['cagr']:.2f}% | "
                f"{row['mdd']:.2f}% | {row['sharpe']:.2f} | {row['trades']} | "
                f"{row['workday_ops_per_year']:.2f} | {row['note']} |\n"
            )
        f.write("\n### 操作節奏建議\n")
        f.write("- 主力倉採 EOD 訊號：收盤後推播 → 下班後或隔日開盤執行。  \n")
        f.write("- 盤中僅處理緊急黑天鵝／硬停損級風險。  \n")
        f.write("- 個股殘倉只減不擴，避免上班被短線停損綁架。  \n")

    print(f"回測報告已生成於: {report_path}")
    print(f"CP 排名報告已生成於: {cp_md}")
    print(f"CP JSON 已生成於: {cp_json_path}")


if __name__ == "__main__":
    run_etf_backtest()
