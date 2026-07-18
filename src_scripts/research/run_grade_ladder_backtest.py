# -*- coding: utf-8 -*-
"""
分階加碼回測：B 進場、A/S 加碼 vs 同額重推（flat）vs 單次進場。
固定各商品 buy_min_grade（來自 grade_buy_policy），搜尋階梯金額網格。
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta

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
    COMM_TW,
    COMM_US,
    GRADE_RANK,
    OZ_TO_GRAM,
    TAX_TW,
    align_on_date,
    grade_gold_i,
    grade_growth_us_i,
    grade_lev_i,
    grade_pullback_core_i,
    grade_usd_i,
    macro_level_from,
    prepare_tw,
    prepare_us,
    prepare_yahoo_or_daily,
    slice_with_warmup,
)
from grade_buy_policy import load_grade_buy_policy, product_policy  # noqa: E402

POLICY_PATH = os.path.join(WORKSPACE, "config", "grade_buy_policy.json")
_OUT_DIR = os.path.join(WORKSPACE, "reports", "latest", "backtest")
os.makedirs(_OUT_DIR, exist_ok=True)
OUT_MD = os.path.join(_OUT_DIR, "grade_ladder_backtest.md")
OUT_JSON = os.path.join(_OUT_DIR, "grade_ladder_best.json")

PRODUCTS_RUN = ["GOLD", "USDTWD", "0050", "00631L", "QQQ", "VOO", "VXUS"]


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def mode_for_min_grade(min_g: str) -> str:
    return {"S": "S", "A": "A+", "B": "B+", "C": "C+", "D": "D+"}.get(min_g, "B+")


def ladder_candidates(budget: float, min_g: str) -> list[tuple[str, dict]]:
    """金額單位：萬台幣整數再×10000。依 budget 縮放。"""
    b = max(int(budget), 100_000)
    scale = b / 600_000.0

    def z(wan: float) -> int:
        return max(0, int(round(wan * scale)) * 10_000)

    if min_g == "S":
        return [
            ("單次S進場", {"B": 0, "A": 0, "S": z(24), "C": 0, "D": 0}),
            ("單次S加大", {"B": 0, "A": 0, "S": z(30), "C": 0, "D": 0}),
        ]
    if min_g == "A":
        return [
            ("單次A無加碼", {"B": 0, "A": z(24), "S": 0, "C": 0, "D": 0}),
            ("同額A/S重推", {"B": 0, "A": z(24), "S": z(24), "C": 0, "D": 0}),
            ("階梯A24/S12", {"B": 0, "A": z(24), "S": z(12), "C": 0, "D": 0}),
            ("階梯A20/S20", {"B": 0, "A": z(20), "S": z(20), "C": 0, "D": 0}),
            ("階梯A16/S16", {"B": 0, "A": z(16), "S": z(16), "C": 0, "D": 0}),
            ("只S進場", {"B": 0, "A": 0, "S": z(30), "C": 0, "D": 0}),
        ]
    # min B
    return [
        ("單次進場無加碼", {"B": z(24), "A": 0, "S": 0, "C": 0, "D": 0}),
        ("同額重推24/24/24", {"B": z(24), "A": z(24), "S": z(24), "C": 0, "D": 0}),
        ("階梯24/12/12", {"B": z(24), "A": z(12), "S": z(12), "C": 0, "D": 0}),
        ("階梯24/18/18", {"B": z(24), "A": z(18), "S": z(18), "C": 0, "D": 0}),
        ("階梯16/16/16", {"B": z(16), "A": z(16), "S": z(16), "C": 0, "D": 0}),
        ("階梯20/20/20", {"B": z(20), "A": z(20), "S": z(20), "C": 0, "D": 0}),
        ("只A+進場30/30", {"B": 0, "A": z(30), "S": z(30), "C": 0, "D": 0}),
        ("階梯12/24/24", {"B": z(12), "A": z(24), "S": z(24), "C": 0, "D": 0}),
    ]


def simulate_ladder(
    *,
    kind: str,
    buy_min: str,
    ladder: dict,
    budget: float,
    trade_closes: np.ndarray,
    opens: np.ndarray | None = None,
    gold_usd: np.ndarray | None = None,
    fx_closes: np.ndarray | None = None,
    taiex: np.ndarray | None = None,
    is_tw: bool = False,
    test_start: int = 200,
    sleeve_initial: float | None = None,
) -> dict:
    """
    ladder[g] = 該階「進場或加碼」金額（首次用當日等級金額；升級用更高階金額）。
    """
    n = len(trade_closes)
    if n <= test_start + 20:
        return {"ok": False, "reason": "資料不足"}

    initial = float(sleeve_initial if sleeve_initial is not None else budget)
    cash = initial
    units = 0.0
    invested = 0.0
    max_filled = None  # grade letter
    equity = []
    trades = 0
    buys = 0
    buy_grades = []
    min_rank = GRADE_RANK.get(buy_min, 2)

    for i in range(n):
        px = float(trade_closes[i])
        equity.append(cash + units * px)
        if i < test_start or i >= n - 1:
            continue

        # grade
        if kind == "gold":
            g = grade_gold_i(gold_usd, fx_closes, i)
            should_sell = units > 0 and float(gold_usd[i]) > float(
                np.mean(gold_usd[i - 49 : i + 1])
            )
        elif kind == "usd":
            g = grade_usd_i(trade_closes, i)
            ma200 = float(np.mean(trade_closes[i - 199 : i + 1]))
            should_sell = units > 0 and px > ma200 * 1.015
        elif kind == "lev":
            level = macro_level_from(taiex, i)
            g = grade_lev_i(trade_closes, taiex, i, level)
            should_sell = False
            if units > 0:
                if taiex[i] < float(np.mean(taiex[i - 199 : i + 1])):
                    should_sell = True
                if px < float(np.mean(trade_closes[i - 9 : i + 1])):
                    should_sell = True
        elif kind == "us_growth":
            g = grade_growth_us_i(trade_closes, i)
            should_sell = units > 0 and px < float(np.mean(trade_closes[i - 49 : i + 1]))
        else:
            # core tw / us_core
            if is_tw and taiex is not None:
                level = macro_level_from(taiex, i)
            else:
                level = 1
            g = grade_pullback_core_i(trade_closes, i, level)
            if kind == "us_core":
                should_sell = units > 0 and px < float(
                    np.mean(trade_closes[i - 49 : i + 1])
                )
            else:
                should_sell = units > 0 and px < float(
                    np.mean(trade_closes[i - 9 : i + 1])
                )

        j = i + 1
        if opens is not None and float(opens[j]) > 0:
            px_next = float(opens[j])
        else:
            px_next = float(trade_closes[j])

        comm = COMM_TW + TAX_TW if is_tw else COMM_US

        if should_sell and units > 0:
            cash += units * px_next * (1 - comm)
            units = 0.0
            invested = 0.0
            max_filled = None
            trades += 1

        if GRADE_RANK.get(g, 0) < min_rank:
            continue

        # 決定本次動作
        action_amt = 0.0
        if max_filled is None:
            # 進場：用當日等級金額；若該階為 0 則找 ≥min 且有額的最高可用
            action_amt = float(ladder.get(g, 0) or 0)
            if action_amt <= 0:
                for gg in ("B", "A", "S"):
                    if GRADE_RANK[gg] >= min_rank and float(ladder.get(gg, 0) or 0) > 0:
                        if GRADE_RANK[gg] <= GRADE_RANK.get(g, 0):
                            action_amt = float(ladder[gg])
                # 直接跳到高於有額階：用當日能用的最高 ≤g 的非零
                if action_amt <= 0:
                    for gg in ("S", "A", "B"):
                        if GRADE_RANK[gg] <= GRADE_RANK.get(g, 0) and float(
                            ladder.get(gg, 0) or 0
                        ) > 0:
                            action_amt = float(ladder[gg])
                            break
            fill_to = g
        elif GRADE_RANK.get(g, 0) > GRADE_RANK.get(max_filled, 0):
            action_amt = float(ladder.get(g, 0) or 0)
            fill_to = g
        else:
            continue

        if action_amt <= 0:
            continue
        room = budget - invested
        spend = min(action_amt, room, cash)
        if spend < 10_000:
            continue

        add_u = spend / (px_next * (1 + (COMM_TW if is_tw else COMM_US)))
        units += add_u
        cash -= spend
        invested += spend
        max_filled = fill_to if max_filled is None else (
            fill_to
            if GRADE_RANK.get(fill_to, 0) >= GRADE_RANK.get(max_filled, 0)
            else max_filled
        )
        trades += 1
        buys += 1
        buy_grades.append(g)

    eq = pd.Series(equity[test_start:], dtype=float)
    years = max(len(eq) / 252.0, 0.1)
    m = get_metrics(eq, trades, years, initial)
    bh = trade_closes[test_start:] / trade_closes[test_start] * initial
    m_bh = get_metrics(pd.Series(bh), 0, years, initial)
    return {
        "ok": True,
        "cagr": m["cagr"],
        "mdd": m["mdd"],
        "sharpe": m["sharpe"],
        "final": m["final"],
        "cp": m["cp"],
        "trades": m["trades"],
        "buys": buys,
        "buy_grades": dict(pd.Series(buy_grades).value_counts())
        if buy_grades
        else {},
        "years": round(years, 2),
        "bh_cagr": m_bh["cagr"],
        "bh_final": m_bh["final"],
        "beat_bh": m["final"] > m_bh["final"],
        "ladder": {k: int(v) for k, v in ladder.items() if v},
    }


def load_product_frames():
    frames = {}
    df_gold = prepare_yahoo_or_daily("GC=F")
    df_fx = prepare_yahoo_or_daily("USDTWD=X")
    if not df_gold.empty and not df_fx.empty:
        aligned = align_on_date(
            df_gold.rename(columns={"close": "gold", "open": "gold_o"}),
            df_fx[["date", "close"]],
            "fx",
        )
        aligned, ts = slice_with_warmup(aligned, 5)
        frames["GOLD"] = {
            "kind": "gold",
            "aligned": aligned,
            "test_start": ts,
            "is_tw": False,
        }
        fx_df, fx_ts = slice_with_warmup(df_fx, 5)
        frames["USDTWD"] = {
            "kind": "usd",
            "df": fx_df,
            "test_start": fx_ts,
            "is_tw": False,
        }

    df_taiex = prepare_tw("TAIEX")
    for code, kind, is_tw, prep in [
        ("0050", "core_tw", True, prepare_tw("0050")),
        ("00631L", "lev", True, prepare_tw("00631L")),
        ("QQQ", "us_growth", False, prepare_us("QQQ")),
        ("VOO", "us_core", False, prepare_us("VOO")),
        ("VXUS", "us_core", False, prepare_us("VXUS")),
    ]:
        df, ts = slice_with_warmup(prep, 5)
        if df.empty:
            continue
        t_closes = None
        if is_tw and not df_taiex.empty:
            taiex_s, _ = slice_with_warmup(df_taiex, 5)
            m = df.merge(
                taiex_s.rename(columns={"close": "taiex", "open": "taiex_o"}),
                on="date",
                how="inner",
            )
            if len(m) < ts + 20:
                continue
            end = pd.to_datetime(m["date"].iloc[-1])
            eval_s = (end - timedelta(days=int(365 * 5))).strftime("%Y-%m-%d")
            idxs = m.index[m["date"] >= eval_s]
            ts = max(int(idxs[0]) if len(idxs) else 200, 200)
            df = m[["date", "open", "close"]].reset_index(drop=True)
            t_closes = m["taiex"].astype(float).values
        frames[code] = {
            "kind": kind,
            "df": df,
            "test_start": ts,
            "is_tw": is_tw,
            "taiex": t_closes,
        }
    return frames


def run_one_product(code: str, frame: dict, policy: dict) -> dict:
    pol = product_policy(code, policy)
    buy_min = str(pol.get("buy_min_grade") or "B")
    budget = float(pol.get("budget_twd") or 0)
    if budget <= 0:
        # 袖口 ≈ 建議額 × 2.5
        sug = pol.get("suggest_twd") or {}
        base = max(int(sug.get("B") or sug.get("A") or sug.get("S") or 100_000), 80_000)
        budget = float(base * 2.5)

    print(f"\n=== {code} min={buy_min} budget={budget/1e4:.0f}萬 ===")
    cands = ladder_candidates(budget, buy_min)
    results = []
    best = None
    flat = None

    for label, ladder in cands:
        if frame["kind"] == "gold":
            al = frame["aligned"]
            gold_usd = al["gold"].astype(float).values
            fx = al["fx"].astype(float).values
            bot = gold_usd * fx / OZ_TO_GRAM
            r = simulate_ladder(
                kind="gold",
                buy_min=buy_min,
                ladder=ladder,
                budget=budget,
                trade_closes=bot,
                gold_usd=gold_usd,
                fx_closes=fx,
                test_start=frame["test_start"],
                sleeve_initial=budget,
            )
        elif frame["kind"] == "usd":
            df = frame["df"]
            r = simulate_ladder(
                kind="usd",
                buy_min=buy_min,
                ladder=ladder,
                budget=budget,
                trade_closes=df["close"].astype(float).values,
                test_start=frame["test_start"],
                sleeve_initial=budget,
            )
        else:
            df = frame["df"]
            r = simulate_ladder(
                kind=frame["kind"],
                buy_min=buy_min,
                ladder=ladder,
                budget=budget,
                trade_closes=df["close"].astype(float).values,
                opens=df["open"].astype(float).values,
                taiex=frame.get("taiex"),
                is_tw=frame["is_tw"],
                test_start=frame["test_start"],
                sleeve_initial=budget,
            )
        if not r.get("ok"):
            print(f"  {label}: fail {r.get('reason')}")
            continue
        item = {
            "label": label,
            "ladder_twd": r["ladder"],
            "cagr": r["cagr"],
            "mdd": r["mdd"],
            "final": r["final"],
            "cp": r["cp"],
            "buys": r["buys"],
            "buy_grades": r.get("buy_grades") or {},
        }
        results.append(item)
        print(
            f"  {label:16s} CAGR {r['cagr']:+5.1f}% MDD {r['mdd']:6.1f}% "
            f"終值 {r['final']/1e4:6.1f}萬 買{r['buys']:3d} CP {r['cp']:+.2f}"
        )
        if "同額重推" in label or label.startswith("同額"):
            flat = item
        if "單次進場無加碼" in label or label == "單次S進場":
            if flat is None:
                pass
            # keep once_entry separately
        key = (item["final"], item["cp"])
        if best is None or key > (best["final"], best["cp"]):
            best = item

    if flat is None:
        # 用同額結構近似：各階=進場額
        for it in results:
            if it["ladder_twd"].get("A") and it["ladder_twd"].get("A") == it[
                "ladder_twd"
            ].get("B"):
                flat = it
                break
        if flat is None and results:
            flat = results[0]

    once = next(
        (
            it
            for it in results
            if "無加碼" in it["label"] or it["label"] == "單次S進場"
        ),
        None,
    )

    use_ladder = False
    if best and flat:
        # 優勝且買次不過度（≤ flat×2.5 或 ≤80）
        buys_ok = best["buys"] <= max(80, int(flat["buys"] * 2.5) + 5)
        # 必須真的有加碼額（A 或 S > 0 且與「無加碼」不同）
        has_add = (best["ladder_twd"].get("A", 0) > 0) or (
            best["ladder_twd"].get("S", 0) > 0
            and best["ladder_twd"].get("B", 0) > 0
            and buy_min != "S"
        )
        if buy_min == "S":
            use_ladder = False  # 退化單次
        elif best["final"] >= flat["final"] * 0.995 and buys_ok and has_add:
            # 若冠軍就是同額重推，仍算 ladder（升級才加）但標記
            use_ladder = True
        elif once and best["final"] >= once["final"] and has_add and buys_ok:
            use_ladder = best["final"] >= (flat["final"] if flat else 0) * 0.99

    # 若冠軍是「無加碼」，強制 flat
    if best and ("無加碼" in best["label"] or best["label"] == "單次S進場"):
        use_ladder = False

    return {
        "code": code,
        "buy_min_grade": buy_min,
        "budget_twd": int(budget),
        "best": best,
        "flat_ref": flat,
        "once_ref": once,
        "use_ladder": use_ladder,
        "candidates": results,
    }


def apply_winners_to_policy(winners: list[dict]) -> dict:
    policy = load_grade_buy_policy()
    products = policy.setdefault("products", {})
    for w in winners:
        code = w["code"]
        if code not in products:
            continue
        best = w.get("best") or {}
        ladder = best.get("ladder_twd") or {}
        products[code]["sizing"] = "ladder" if w.get("use_ladder") else "flat"
        if w.get("use_ladder") and ladder:
            products[code]["ladder_twd"] = {
                "D": 0,
                "C": 0,
                "B": int(ladder.get("B", 0) or 0),
                "A": int(ladder.get("A", 0) or 0),
                "S": int(ladder.get("S", 0) or 0),
            }
            # suggest 後備：進場用 B（或門檻階）
            min_g = w["buy_min_grade"]
            enter = int(ladder.get(min_g) or ladder.get("B") or ladder.get("S") or 0)
            products[code]["suggest_twd"] = {
                "D": 0,
                "C": 0,
                "B": enter if min_g in ("B", "A", "S") and GRADE_RANK["B"] >= GRADE_RANK.get(min_g, 0) else int(ladder.get("B", 0) or 0),
                "A": enter if min_g == "A" else int(ladder.get("A", 0) or enter),
                "S": enter if min_g == "S" else int(ladder.get("S", 0) or enter),
            }
            # fix suggest properly
            st = {"D": 0, "C": 0, "B": 0, "A": 0, "S": 0}
            for gg in ("B", "A", "S"):
                if GRADE_RANK[gg] >= GRADE_RANK.get(min_g, 0):
                    st[gg] = int(ladder.get(gg, 0) or 0) or enter
            products[code]["suggest_twd"] = st
        else:
            products[code]["sizing"] = "flat"
            products[code].pop("ladder_twd", None)
            # flat 冠軍仍更新進場建議額（升級不加碼由 next_ladder_action 處理）
            if ladder:
                min_g = w["buy_min_grade"]
                enter = int(
                    ladder.get(min_g)
                    or ladder.get("B")
                    or ladder.get("A")
                    or ladder.get("S")
                    or 0
                )
                st = {"D": 0, "C": 0, "B": 0, "A": 0, "S": 0}
                for gg in ("B", "A", "S"):
                    if GRADE_RANK[gg] >= GRADE_RANK.get(min_g, 0):
                        # flat：各階顯示同進場額（語氣用），實盤加碼金額為 0
                        st[gg] = int(ladder.get(gg, 0) or 0) or enter
                if any(st.values()):
                    products[code]["suggest_twd"] = st
    # QQQM copy QQQ
    if "QQQ" in products and "QQQM" in products:
        products["QQQM"]["sizing"] = products["QQQ"].get("sizing", "flat")
        if products["QQQ"].get("ladder_twd"):
            products["QQQM"]["ladder_twd"] = dict(products["QQQ"]["ladder_twd"])
        products["QQQM"]["suggest_twd"] = dict(products["QQQ"].get("suggest_twd") or {})
    policy["version"] = int(policy.get("version") or 2) + 1
    policy["ladder_backtest_at"] = datetime.now().isoformat(timespec="seconds")
    with open(POLICY_PATH, "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)
    return policy


def main():
    print("=== 分階加碼回測 ===")
    policy = load_grade_buy_policy()
    frames = load_product_frames()
    winners = []
    for code in PRODUCTS_RUN:
        if code not in frames:
            print(f"略過 {code}：無資料")
            continue
        winners.append(run_one_product(code, frames[code], policy))

    # 寫報告
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    lines = []
    lines.append("# 分階加碼回測（B 進場／A·S 加碼）\n\n")
    lines.append(f"產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    lines.append(
        "同一持倉週期：首次達門檻進場；評等升高才加碼；出場後重置。  \n"
    )
    lines.append(
        "判定：ladder 終值 ≥ 同額重推（flat）且買次不過度 → `use_ladder=true`。  \n\n"
    )
    lines.append(
        "| 商品 | 門檻 | 冠軍方案 | B/A/S | CAGR | MDD | 終值 | vs flat | 採用 |\n"
    )
    lines.append("| :--- | :---: | :--- | :--- | ---: | ---: | ---: | ---: | :---: |\n")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "products": [],
    }
    for w in winners:
        best = w.get("best") or {}
        flat = w.get("flat_ref") or {}
        lt = best.get("ladder_twd") or {}
        bas = f"{lt.get('B', 0)//10000}/{lt.get('A', 0)//10000}/{lt.get('S', 0)//10000}"
        vs = "—"
        if flat.get("final") and best.get("final"):
            vs = f"{(best['final']/flat['final']-1)*100:+.1f}%"
        lines.append(
            f"| `{w['code']}` | {w['buy_min_grade']} | {best.get('label', '—')} | "
            f"{bas} | {best.get('cagr', 0):+.1f}% | {best.get('mdd', 0):.1f}% | "
            f"{best.get('final', 0)/1e4:.1f}萬 | {vs} | "
            f"{'**ladder**' if w.get('use_ladder') else 'flat'} |\n"
        )
        payload["products"].append(
            {
                "code": w["code"],
                "buy_min_grade": w["buy_min_grade"],
                "budget_twd": w["budget_twd"],
                "use_ladder": w.get("use_ladder"),
                "ladder_twd": lt,
                "best_label": best.get("label"),
                "cagr": best.get("cagr"),
                "mdd": best.get("mdd"),
                "final": best.get("final"),
                "flat_final": flat.get("final"),
                "candidates": w.get("candidates"),
            }
        )

    lines.append("\n## 解讀\n\n")
    lines.append(
        "- **ladder**：升級才加碼，推播應區分「進場」與「加碼」。  \n"
        "- **flat**：達門檻給建議額；升級只改語氣、不加碼金額。  \n"
        "- VOO／VXUS 門檻 S → 實務上只能單次進場。  \n"
    )

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, ensure_ascii=False, indent=2)

    apply_winners_to_policy(winners)
    print(f"\n報告：{OUT_MD}")
    print(f"JSON：{OUT_JSON}")
    print(f"已更新：{POLICY_PATH}")


if __name__ == "__main__":
    main()
