# -*- coding: utf-8 -*-
"""
EOD position-level scanner: confirm stop / take-profit / timing / force-exit
after market close, then push one Telegram+Email summary (urgency=eod_action).
"""
from __future__ import annotations

import json
import os
import sys
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
from holding_rules import (  # noqa: E402
    REJECTED_BUY_CODES,
    core_etf_eod_actions,
    is_core_etf,
)
from trade_levels import holding_exit_plan  # noqa: E402
from tw_time import taiwan_now  # noqa: E402
from eod_pending_ops import filter_core_ops, merge_pending_items  # noqa: E402



def load_levels():
    if not os.path.exists(LEVELS_PATH):
        return None
    with open(LEVELS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_targets_meta():
    """即時持股／已出清／成本／剔除清單／policy。"""
    path = os.path.join(WORKSPACE, "config", "my_targets.json")
    if not os.path.exists(path):
        return set(), set(), {}, set(), {}
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
    costs = {}
    policies = {}
    for h in (data.get("portfolio") or []):
        c = str(h.get("code") or "")
        if c and h.get("cost") is not None:
            costs[c] = float(h["cost"])
        if c and h.get("policy"):
            policies[c] = str(h["policy"])
    rejected = {
        str(x)
        for x in ((data.get("approved_universe") or {}).get("rejected") or [])
        if x
    } | set(REJECTED_BUY_CODES)
    portfolio -= cleared
    return portfolio, cleared, costs, rejected, policies


def effective_roi(row, costs: dict) -> float | None:
    """優先 levels.roi_pct；否則用 cost（levels 或 my_targets）與收盤價估算。"""
    if row.get("roi_pct") is not None:
        return float(row["roi_pct"])
    code = str(row.get("code") or "")
    cost = row.get("cost")
    if cost is None and code:
        cost = costs.get(code)
    close = row.get("close")
    if cost is not None and close is not None and float(cost) > 0:
        return (float(close) / float(cost) - 1.0) * 100.0
    return None


def roi_for_code(levels_doc, code: str, costs: dict):
    for row in levels_doc.get("levels") or []:
        if str(row.get("code") or "") == code:
            return effective_roi(row, costs)
    return None


def in_profit(roi_pct) -> bool:
    """停利建議僅在帳面獲利時；套牢部位以停損／續抱為準。"""
    return roi_pct is not None and float(roi_pct) > 0


def near(price, level, tol_pct):
    if price is None or level is None or level == 0:
        return False
    return abs(price - level) / abs(level) * 100.0 <= tol_pct


def _fmt_opt(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def main():
    now = taiwan_now()
    force = "--force" in sys.argv
    # Default window: after TW close ~13:40, allow until evening; or --force
    if not force and not (13 <= now.hour <= 22):
        print(
            f"非收盤後掃描時段 (台北 13:00~22:00) 且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    levels_doc = load_levels()
    if not levels_doc:
        print(
            f"找不到 {LEVELS_PATH}，請先跑 "
            f"`python src_scripts/refresh_levels_live.py` 或 "
            f"`python src_scripts/sync_runtime_state.py`。"
        )
        sys.exit(1)

    live_portfolio, cleared_codes, portfolio_costs, rejected_codes, policies = (
        load_targets_meta()
    )
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
        # 核心 ETF／已剔除商品：改由下方具體建議重算，略過舊空泛句
        if mentioned and (
            is_core_etf(mentioned)
            or mentioned in rejected_codes
            or "正2袖口" in a
            or a.startswith("正2擇時")
            or a.startswith("債券配置")
            or a.startswith("0050底倉")
        ):
            continue
        if any(rc in a for rc in rejected_codes) and ("建倉" in a or "停利" in a or "00682U" in a):
            continue
        # 套牢股：舊「停利／停利檢視」一律丟棄，避免推播誤導砍虧
        if mentioned and ("停利" in a):
            if not in_profit(roi_for_code(levels_doc, mentioned, portfolio_costs)):
                continue
        actions.append(a)

    forced = {
        str(c)
        for c in (levels_doc.get("force_exit_codes") or [])
        if str(c) not in cleared_codes and (not live_portfolio or str(c) in live_portfolio)
    }
    macro = levels_doc.get("macro_level", 1)
    cp_name = levels_doc.get("cp_best_strategy") or "（尚未回測）"
    above_200 = None
    for row in levels_doc.get("levels") or []:
        if str(row.get("code")) == "TAIEX":
            above_200 = row.get("above_200ma")
            break

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

            if row.get("profit_rule") == "etf_core" or (
                is_core_etf(code, name) and code not in forced
            ):
                cost = row.get("cost")
                if cost is None:
                    cost = portfolio_costs.get(code)
                roi = effective_roi(row, portfolio_costs)
                actions.extend(
                    core_etf_eod_actions(
                        code,
                        name,
                        macro_level=int(macro),
                        above_200ma=above_200,
                        close=float(close) if close is not None else None,
                        cost=float(cost) if cost is not None else None,
                        roi_pct=roi,
                        ma5=row.get("ma5"),
                        ma10=row.get("ma10"),
                        ma20=row.get("ma20"),
                    )
                )
                continue

            stop = row.get("stop") or row.get("low_5d")
            profit = row.get("profit")
            add = row.get("add")
            roi = effective_roi(row, portfolio_costs)
            cost = row.get("cost")
            if cost is None:
                cost = portfolio_costs.get(code)

            # 個股：每次 EOD 都報停損／停利狀態（含成本）
            actions.extend(
                holding_exit_plan(
                    code=code,
                    name=name,
                    close=float(close) if close is not None else None,
                    cost=float(cost) if cost is not None else None,
                    roi_pct=roi,
                    stop=float(stop) if stop is not None else None,
                    profit=float(profit) if profit is not None else None,
                    ma5=row.get("ma5"),
                    ma10=row.get("ma10"),
                    is_etf_core=False,
                    policy=policies.get(code, ""),
                )
            )

            if stop is not None and close <= stop:
                # holding_exit_plan 已含觸發句；略過重複舊格式
                pass
            else:
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
            if add is not None and near(close, add, tol) and code not in forced:
                actions.append(
                    f"主力加碼帶：{code} {name} 接近 10MA {add:.2f}"
                    f"（成本 {cost if cost is not None else '—'}；勿對 force_exit 加碼）"
                )
            if code in forced:
                if stop and close >= stop * (1 + bounce / 100.0):
                    actions.append(f"出清窗：{code} {name} 相對防守點反彈，逢高分批出清")

        elif status == "watchlist":
            if code in rejected_codes:
                if code in ("00682U",) or "美元" in str(name):
                    actions.append(
                        "美元配置：不要買 00682U 美元指數 ETF；"
                        "若要避險／囤匯，改在台銀等直接買美金（對照匯率年均線，見多資產報表）"
                    )
                continue
            # 買點一律走 scan_watch_grades（grade_buy_policy 門檻）；
            # 此處不再推「回測 5MA 建倉」，避免繞過評等／階梯政策。

        elif status == "macro" and code == "TAIEX":
            above = row.get("above_200ma")
            ma200 = row.get("ma200")
            if ma200 is not None:
                if above:
                    actions.append(
                        f"大盤年線：{close:.2f} 仍在 200MA {ma200:.2f} 之上 → "
                        f"長線多頭未破；正2既有倉可續抱，但若 Level≥3 仍禁止加碼"
                    )
                else:
                    actions.append(
                        f"大盤年線：{close:.2f} 跌破 200MA {ma200:.2f} → "
                        f"正2建議減碼／空倉（EOD 確認後執行）"
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
    # 僅正式 EOD（≥14:00 或 --save-pending）寫入隔日 08:30 提醒；13:10 提早清單不覆蓋
    save_pending = "--save-pending" in sys.argv or now.hour >= 14
    if save_pending:
        core_items = filter_core_ops(actions)
        merge_pending_items(
            as_of=now.strftime("%Y-%m-%d"),
            items=core_items,
            as_of_ts=now.isoformat(timespec="seconds"),
            replace_same_day=True,
        )
        print(f"已寫 eod_pending_ops：0050／正2 操作 {len(core_items)} 項")
    print(f"EOD 清單已寫入 {EOD_REPORT_PATH}（{len(actions)} 項）")


if __name__ == "__main__":
    main()
