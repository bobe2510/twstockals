# -*- coding: utf-8 -*-
"""
規則健康檢查：比對「上線規則」與最新回測結果，劣化時經 event_bus 推播。

每季由 quarterly_research.sh 在重跑全部回測後呼叫；
檢查各上線規則當初的支撐證據在滾動視窗下是否仍成立。
"""
from __future__ import annotations

import json
import os
import sys

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from event_bus import apply_desired  # noqa: E402

BT = os.path.join(WORKSPACE, "reports", "latest", "backtest")


def _load(name):
    p = os.path.join(BT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return d if d is not None else default


def run_checks() -> tuple[list[str], list[str]]:
    """回傳 (failures, notes)。缺資料記 notes 不算失敗。"""
    fails, notes = [], []

    # 1. 正2：200MA 開關全期 CP 仍 > B&H CP（voltarget json）
    vt = _load("voltarget_00631L_backtest.json")
    if vt:
        cp_ma = _get(vt, "results", "00631L × 200MA 年線開關", "full", "cp")
        cp_bh = _get(vt, "results", "00631L 買入持有", "full", "cp")
        if cp_ma is not None and cp_bh is not None:
            if cp_ma <= cp_bh:
                fails.append(f"正2年線開關 CP({cp_ma:.1f}) 已不優於 B&H({cp_bh:.1f})")
        else:
            notes.append("voltarget: 缺 CP 欄位")
    else:
        notes.append("voltarget json 缺")

    # 2. 0050：長抱 CAGR 仍 > 10MA 出場（exit_rule json）
    er = _load("exit_rule_backtest.json")
    if er:
        hold = _get(er, "products", "0050", "B. 評等B+進場、永不出場", "full", "cagr")
        ma10 = _get(er, "products", "0050", "C. 現行：評等進場＋破10MA出場", "full", "cagr")
        if hold is not None and ma10 is not None and hold <= ma10:
            fails.append(f"0050 長抱({hold:.1f}%) 已不優於 10MA出場({ma10:.1f}%)")
        l1 = _get(er, "products", "00631L", "L1. 200MA開關（主規則）", "full", "cp")
        l2 = _get(er, "products", "00631L", "L2. 現行合併：200MA或10MA出場", "full", "cp")
        if l1 is not None and l2 is not None and l1 <= l2:
            fails.append(f"正2 純年線 CP({l1:.1f}) 已不優於 加10MA({l2:.1f})")
    else:
        notes.append("exit_rule json 缺")

    # 3. 黃金：進場後長抱終值仍 > 50MA出場（gold_sleeve json）
    gs = _load("gold_sleeve_backtest.json")
    if gs:
        hold = _get(gs, "windows", "全期", "results", "grade_hold", "final")
        ma50 = _get(gs, "windows", "全期", "results", "grade_ma50", "final")
        if hold is not None and ma50 is not None and hold <= ma50:
            fails.append(f"黃金長抱終值({hold:,.0f}) 已不優於 50MA出場({ma50:,.0f})")
    else:
        notes.append("gold_sleeve json 缺")

    # 4. 美股/幣：採用的趨勢規則 CP 仍 >= B&H（trend_exit json）
    te = _load("trend_exit_backtest.json")
    if te:
        checks = [
            ("SPY（VOO代理）", "G. 複合OR（200MA或動量）", "full", "VOO G複合"),
            ("EFA（VXUS代理）", "D. 200MA 趨勢開關", "full", "VXUS 200MA"),
            ("BTC", "G. 複合OR（200MA或動量）", "oos", "BTC G複合(OOS)"),
            ("ETH", "D. 200MA 趨勢開關", "full", "ETH 200MA"),
        ]
        for asset, strat, per, label in checks:
            cp_s = _get(te, "assets", asset, strat, per, "cp")
            cp_b = _get(te, "assets", asset, "A. 買入持有", per, "cp")
            if cp_s is None or cp_b is None:
                notes.append(f"trend_exit: {label} 缺資料")
            elif cp_s <= cp_b:
                fails.append(f"{label} CP({cp_s:.1f}) 已不優於 B&H({cp_b:.1f})")
    else:
        notes.append("trend_exit json 缺")

    return fails, notes


def main() -> int:
    fails, notes = run_checks()
    for n in notes:
        print(f"[health:note] {n}")
    for x in fails:
        print(f"[health:FAIL] {x}")
    if not fails and not notes:
        print("[health] all checks pass")

    apply_desired(
        "rule_health",
        bool(fails),
        title_on=f"⚠️ 規則健康檢查失敗 ×{len(fails)}",
        body_on=(
            "季度再驗證發現上線規則的回測支撐已劣化：\n"
            + "\n".join(f"• {x}" for x in fails)
            + "\n\n建議重新審視對應 sell_rule／閘門設定（見 reports/latest/backtest/）。"
        ),
        title_off="規則健康檢查恢復通過",
        body_off="全部上線規則的回測支撐恢復成立。",
        notify_clear=True,
        meta={"fails": fails[:6], "notes": notes[:6]},
        quiet=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
