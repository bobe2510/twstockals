# -*- coding: utf-8 -*-
"""
約 13:10：只推「台股出清監控」持股的停損／停利／操作狀況。

涵蓋：
  - policy=gradual_exit／force_exit／exit_only（如 00687B）
  - force_exit_codes／force_exit 標記
  - 台股個股殘倉（四碼股票；0050／正2 等長抱核心排除）

不推：0050、00631L、美股 ETF、已出清標的。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "exit_watch_1310.md")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from holding_rules import (  # noqa: E402
    core_etf_eod_actions,
    is_core_etf,
    is_tw_exit_watch,
)
from market_data import fetch_daily  # noqa: E402
from notify import load_alert_rules, notify  # noqa: E402
from trade_levels import holding_exit_plan  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _live_close(code: str) -> Optional[float]:
    try:
        rows = fetch_daily(code, prefer="tw")
        if rows:
            return float(rows[-1]["close"])
    except Exception as e:
        print(f"報價失敗 {code}: {e}")
    return None


def _level_row(levels_doc: dict, code: str) -> dict:
    for row in levels_doc.get("levels") or []:
        if str(row.get("code") or "") == code:
            return row
    return {}


def main() -> None:
    now = taiwan_now()
    force = "--force" in sys.argv
    hhmm = now.strftime("%H%M")
    rules = load_alert_rules()
    cc = rules.get("close_confirm") or {}
    start = str(cc.get("start_hhmm") or "1305")
    end = str(cc.get("end_hhmm") or "1325")
    # 允許收盤確認窗；或 --force（雲端 close_confirm 一律帶 --force）
    if not force and not (start <= hhmm <= end):
        print(
            f"非出清倉 13:10 視窗（台北 {start}~{end}）且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    targets = load_json(TARGETS_PATH, {})
    levels_doc = load_json(LEVELS_PATH, {})
    cleared = {
        str(x.get("code"))
        for x in (targets.get("cleared_positions") or [])
        if x.get("code")
    }
    force_exit_codes = {
        str(c) for c in (targets.get("force_exit_codes") or []) if c
    } | {
        str(c) for c in (levels_doc.get("force_exit_codes") or []) if c
    }

    portfolio = []
    for h in targets.get("portfolio") or []:
        code = str(h.get("code") or "")
        if not code or code in cleared:
            continue
        if h.get("force_exit"):
            force_exit_codes.add(code)
        if is_tw_exit_watch(
            code,
            h.get("name") or "",
            policy=str(h.get("policy") or ""),
            force_exit=bool(h.get("force_exit")),
            force_exit_codes=force_exit_codes,
        ):
            portfolio.append(h)

    lines = [
        "# 台股出清倉｜13:10 停損停利狀況\n\n",
        f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n",
        "> 只列打算出清的台股個股／ETF；不含 0050／正2 長抱與美股。  \n\n",
    ]
    actions: list[str] = []

    if not portfolio:
        lines.append("目前無台股出清監控持股。\n")
    else:
        macro = int(levels_doc.get("macro_level") or 1)
        above_200 = None
        for row in levels_doc.get("levels") or []:
            if str(row.get("code")) == "TAIEX":
                above_200 = row.get("above_200ma")
                break

        for h in portfolio:
            code = str(h["code"])
            name = str(h.get("name") or "")
            cost = h.get("cost")
            policy = str(h.get("policy") or "")
            row = _level_row(levels_doc, code)
            live = _live_close(code)
            close = live if live is not None else row.get("close")
            stop = row.get("stop") or row.get("low_5d")
            profit = row.get("profit")
            ma5 = row.get("ma5")
            ma10 = row.get("ma10")
            roi = None
            if cost is not None and close is not None and float(cost) > 0:
                roi = (float(close) / float(cost) - 1.0) * 100.0
            elif row.get("roi_pct") is not None:
                roi = float(row["roi_pct"])

            tag = policy or ("force_exit" if code in force_exit_codes else "個股殘倉")
            lines.append(f"## {code} {name}\n\n")
            lines.append(f"* 標記：**{tag}**  \n")
            if close is not None:
                lines.append(
                    f"* 現價：**{float(close):.2f}**"
                    f"{'（即時）' if live is not None else '（levels）'}  \n"
                )
            if cost is not None:
                if roi is not None:
                    lines.append(
                        f"* 成本：{float(cost):.2f}｜報酬 {roi:+.1f}%  \n"
                    )
                else:
                    lines.append(f"* 成本：{float(cost):.2f}  \n")
            if stop is not None:
                lines.append(f"* 停損參考：{float(stop):.2f}  \n")
            if profit is not None:
                lines.append(f"* 停利參考：{float(profit):.2f}  \n")
            lines.append("\n")

            # 美債／出清 ETF：用核心 ETF 出清文案
            if policy == "gradual_exit" or code == "00687B" or "債" in name:
                bits = core_etf_eod_actions(
                    code,
                    name,
                    macro_level=macro,
                    above_200ma=above_200,
                    close=float(close) if close is not None else None,
                    cost=float(cost) if cost is not None else None,
                    roi_pct=roi,
                    ma5=ma5,
                    ma10=ma10,
                    ma20=row.get("ma20"),
                )
                for b in bits:
                    actions.append(b)
                    lines.append(f"* {b}  \n")
            else:
                bits = holding_exit_plan(
                    code=code,
                    name=name,
                    close=float(close) if close is not None else None,
                    cost=float(cost) if cost is not None else None,
                    roi_pct=roi,
                    stop=float(stop) if stop is not None else None,
                    profit=float(profit) if profit is not None else None,
                    ma5=ma5,
                    ma10=ma10,
                    is_etf_core=False,
                    policy=policy,
                )
                for b in bits:
                    actions.append(b)
                    lines.append(f"* {b}  \n")
            lines.append("\n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    if not portfolio:
        print(f"無出清監控持股；報告已寫 {REPORT_PATH}")
        sys.exit(0)

    if not actions:
        print(f"出清倉無具體動作；報告已寫 {REPORT_PATH}（不推播）")
        sys.exit(0)

    body = [
        f"時間：{now.strftime('%Y-%m-%d %H:%M')}（台北）",
        f"出清監控 {len(portfolio)} 檔（僅台股）",
        "",
    ]
    body += [f"• {a}" for a in actions[:25]]
    if len(actions) > 25:
        body.append(f"...另有 {len(actions) - 25} 項，見 exit_watch_1310.md")
    body.append("")
    body.append("執行：收盤確認後／隔日開盤；開盤 09:00~09:30 不殺。")

    notify(
        title=f"出清倉停損停利 {now.strftime('%m/%d %H:%M')}（{len(actions)} 項）",
        body="\n".join(body),
        symbol="EXIT_WATCH",
        rule_id="exit_watch_1310",
        urgency="eod_action",
        force=("--force-notify" in sys.argv),
    )
    print(f"出清倉通知已推：{len(actions)} 項／{len(portfolio)} 檔｜{REPORT_PATH}")


if __name__ == "__main__":
    main()
