# -*- coding: utf-8 -*-
"""
EOD position-level scanner: confirm stop / take-profit / timing / force-exit
after market close, then push one Telegram+Email summary (urgency=eod_action).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
ALERT_RULES_PATH = os.path.join(WORKSPACE, "config", "alert_rules.json")
EOD_REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "eod_action_list.md")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from notify import notify, load_alert_rules  # noqa: E402


def load_levels():
    if not os.path.exists(LEVELS_PATH):
        return None
    with open(LEVELS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_live_holdings():
    """即時持股／已出清集合，避免過期 levels.json 對已賣光標的再推播。"""
    path = os.path.join(WORKSPACE, "config", "my_targets.json")
    if not os.path.exists(path):
        return set(), set()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    portfolio = {
        str(h.get("code"))
        for h in (data.get("portfolio") or [])
        if h.get("code")
    }
    cleared = {
        str(x.get("code"))
        for x in (data.get("cleared_positions") or [])
        if x.get("code")
    }
    # cleared 優先：同時出現時視為已出清
    portfolio -= cleared
    return portfolio, cleared


def near(price, level, tol_pct):
    if price is None or level is None or level == 0:
        return False
    return abs(price - level) / abs(level) * 100.0 <= tol_pct


def main():
    now = datetime.now()
    force = "--force" in sys.argv
    # Default window: after TW close ~13:40, allow until evening; or --force
    if not force and not (13 <= now.hour <= 22):
        print("非收盤後掃描時段 (13:00~22:00) 且無 --force，退出。")
        sys.exit(0)

    levels_doc = load_levels()
    if not levels_doc:
        print(f"找不到 {LEVELS_PATH}，請先跑 analyze_portfolio_deep / market_screener。")
        sys.exit(1)

    live_portfolio, cleared_codes = load_live_holdings()
    rules = load_alert_rules()
    tol = float(rules.get("ma_touch_tolerance_pct", 0.8))
    bounce = float(rules.get("exit_priority_bounce_pct", 3.0))

    # 過濾過期 eod_actions：只保留仍持有／非 cleared 的個股相關列（保留大盤／年線等）
    raw_actions = list(levels_doc.get("eod_actions") or [])
    actions = []
    for a in raw_actions:
        skip = False
        for z in cleared_codes:
            if z and z in a:
                skip = True
                break
        if skip:
            continue
        # 若動作提到具體持股代號且不在活持股，略過（保留無代號的總經句）
        mentioned = None
        for row in levels_doc.get("levels") or []:
            c = str(row.get("code") or "")
            if c and c in a and row.get("status") == "portfolio":
                mentioned = c
                break
        if mentioned and live_portfolio and mentioned not in live_portfolio:
            continue
        actions.append(a)

    forced = {
        str(c)
        for c in (levels_doc.get("force_exit_codes") or [])
        if str(c) not in cleared_codes and (not live_portfolio or str(c) in live_portfolio)
    }
    macro = levels_doc.get("macro_level", 1)
    cp_name = levels_doc.get("cp_best_strategy") or "（尚未回測）"

    for row in levels_doc.get("levels") or []:
        code = str(row.get("code") or "")
        name = row.get("name", "")
        status = row.get("status")
        close = row.get("close")
        if close is None:
            continue

        if status == "portfolio":
            if code in cleared_codes:
                continue
            if code not in live_portfolio:
                continue
            stop = row.get("stop") or row.get("low_5d")
            profit = row.get("profit")
            add = row.get("add")
            if stop is not None and close <= stop:
                actions.append(f"停損（砍虧）：{code} {name} 收盤 {close:.2f} ≤ 停損 {stop:.2f}")
            else:
                roi = row.get("roi_pct")
                if row.get("allow_roi_tp") and roi is not None:
                    roi1 = float((rules.get("thresholds") or {}).get("take_profit_roi_1", 12.0))
                    roi2 = float((rules.get("thresholds") or {}).get("take_profit_roi_2", 25.0))
                    frac1 = float((rules.get("thresholds") or {}).get("take_profit_roi_1_frac", 0.33))
                    frac2 = float((rules.get("thresholds") or {}).get("take_profit_roi_2_frac", 0.33))
                    if roi >= roi2:
                        actions.append(
                            f"達標停利②（鎖定獲利）：{code} {name} 報酬 {roi:+.1f}% → 再賣約 {frac2:.0%}"
                        )
                    elif roi >= roi1:
                        actions.append(
                            f"達標停利①（鎖定獲利）：{code} {name} 報酬 {roi:+.1f}% → 先賣約 {frac1:.0%}"
                        )
                if profit is not None and close < profit and code not in forced:
                    actions.append(
                        f"移動停利（鎖定漲幅）：{code} {name} 收盤 {close:.2f} < 停利線 {profit:.2f}"
                    )
            if add is not None and near(close, add, tol) and code not in forced:
                actions.append(f"主力加碼帶：{code} {name} 接近 10MA {add:.2f}（勿對 force_exit 加碼）")
            if code in forced:
                # bounce window heuristic: if close above stop by bounce%
                if stop and close >= stop * (1 + bounce / 100.0):
                    actions.append(f"出清窗：{code} {name} 相對防守點反彈，逢高分批出清")

        elif status == "watchlist":
            entry = row.get("entry")
            if entry is not None and near(close, entry, tol):
                actions.append(f"建倉提醒：{code} {name} 回測 5MA {entry:.2f}（EOD 確認後再下單）")

        elif status == "macro" and code == "TAIEX":
            above = row.get("above_200ma")
            ma200 = row.get("ma200")
            if ma200 is not None:
                actions.append(
                    f"年線狀態：大盤 {close:.2f} / 200MA {ma200:.2f} → "
                    f"{'多頭持有正2袖口' if above else '空頭：正2空倉／現金'}"
                )

    # de-dupe preserve order
    seen = set()
    uniq = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    actions = uniq

    os.makedirs(os.path.dirname(EOD_REPORT_PATH), exist_ok=True)
    with open(EOD_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# 📋 收盤後執行清單 (EOD Action List)\n\n")
        f.write(f"產生時間：{now.strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"大盤濾網 Level：**{macro}**｜CP 最優策略：**{cp_name}**  \n\n")
        f.write("> 建議於 **13:40 後預掛／隔日開盤** 執行；平日上班時段不盯盤。  \n\n")
        if actions:
            for i, a in enumerate(actions, 1):
                f.write(f"{i}. {a}\n")
        else:
            f.write("今日無強制動作，維持持倉與監控即可。\n")

    body_lines = [
        f"時間：{now.strftime('%Y-%m-%d %H:%M')}",
        f"Level：{macro}",
        f"CP 策略：{cp_name}",
        "",
    ]
    if actions:
        body_lines += [f"{i}. {a}" for i, a in enumerate(actions[:20], 1)]
        if len(actions) > 20:
            body_lines.append(f"...另有 {len(actions) - 20} 項，見 eod_action_list.md")
    else:
        body_lines.append("今日無強制收盤動作。")

    notify(
        title=f"收盤執行清單 {now.strftime('%m/%d')}（{len(actions)} 項）",
        body="\n".join(body_lines),
        symbol="EOD",
        rule_id="eod_digest",
        urgency="eod_action",
        force=("--force-notify" in sys.argv),
    )
    print(f"EOD 清單已寫入 {EOD_REPORT_PATH}（{len(actions)} 項）")


if __name__ == "__main__":
    main()
