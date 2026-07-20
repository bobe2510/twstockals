# -*- coding: utf-8 -*-
"""數量建議與 ActionIntent（Playbook 階段2）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
PLAYBOOK_PATH = os.path.join(WORKSPACE, "config", "position_playbook.json")
TRIM_STATE_PATH = os.path.join(WORKSPACE, "reports", "latest", "trim_ladder_state.json")
INTENTS_PATH = os.path.join(WORKSPACE, "reports", "latest", "action_intents.json")


def load_playbook() -> dict:
    with open(PLAYBOOK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def round_lot_shares(shares: float, lot: int = 1000) -> int:
    """台股整張；不足1張回傳0（呼叫端可改標餘額出清）。"""
    if shares is None or shares <= 0:
        return 0
    return int(shares // lot) * lot


def trim_shares(held: float, frac: float = 1.0 / 3.0, lot: int = 1000) -> tuple[int, str]:
    """回傳 (股數, 備註)。不足1張→建議餘額一次出清。"""
    held = float(held or 0)
    raw = held * float(frac)
    lots = round_lot_shares(raw, lot)
    if held > 0 and lots <= 0:
        return int(held), "餘額不足1張→建議一次出清"
    if lots >= held:
        return int(held), "出清剩餘"
    return lots, f"約持倉 {frac:.0%}"


def twd_to_grams(twd: float, price_per_g: float) -> float:
    if not price_per_g or price_per_g <= 0:
        return 0.0
    return round(float(twd) / float(price_per_g), 2)


def twd_to_usd(twd: float, rate: float) -> float:
    if not rate or rate <= 0:
        return 0.0
    return round(float(twd) / float(rate), 2)


def make_intent(
    *,
    code: str,
    venue: str,
    side: str,
    action: str,
    qty: float | int | None = None,
    unit: str = "",
    twd: float | None = None,
    limit_ref: str = "",
    urgency: str = "INFO",
    rationale: str = "",
    gate_type: str = "",
    reenable_when: str = "",
    exec_after: str = "13:40或次日開／避開09:00-09:30",
    priority: int = 50,
    source: str = "position_playbook",
) -> dict[str, Any]:
    return {
        "code": code,
        "venue": venue,
        "side": side,
        "action": action,
        "qty": qty,
        "unit": unit,
        "twd": None if twd is None else round(float(twd), 0),
        "limit_ref": limit_ref,
        "urgency": urgency,
        "rationale": rationale,
        "gate_type": gate_type,
        "reenable_when": reenable_when,
        "exec_after": exec_after,
        "priority": priority,
        "source": source,
    }


def load_trim_state() -> dict:
    if not os.path.exists(TRIM_STATE_PATH):
        return {"version": 1, "products": {}, "updated_at": None}
    with open(TRIM_STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_trim_state(state: dict) -> None:
    os.makedirs(os.path.dirname(TRIM_STATE_PATH), exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(TRIM_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def already_suggested_trim(code: str, trigger: str, state: Optional[dict] = None) -> bool:
    st = state or load_trim_state()
    rec = (st.get("products") or {}).get(str(code), {}).get(trigger) or {}
    return bool(rec.get("suggested_at") and not rec.get("filled_at"))


def mark_trim_suggested(code: str, trigger: str, qty: float, state: Optional[dict] = None) -> dict:
    st = state or load_trim_state()
    st.setdefault("products", {})
    st["products"].setdefault(str(code), {})
    st["products"][str(code)][trigger] = {
        "suggested_at": datetime.now().isoformat(timespec="seconds"),
        "qty": qty,
        "filled_at": None,
    }
    save_trim_state(st)
    return st


PRIORITY_RANK = {
    "sl": 10,
    "rebalance_trim": 20,
    "tp": 30,
    "add": 40,
    "enter": 50,
    "raise_deploy_budget": 60,
    "lower_deploy_budget": 60,
    "gate_blocked": 90,
    "hold": 100,
}


def pick_highest_priority(intents: list[dict], code: str) -> list[dict]:
    """同 code 只保留最高優先（數字越小越優先）。"""
    same = [i for i in intents if i.get("code") == code]
    others = [i for i in intents if i.get("code") != code]
    if not same:
        return intents
    best = min(same, key=lambda x: PRIORITY_RANK.get(x.get("action"), x.get("priority", 99)))
    return others + [best]


def suggest_deployable(
    *,
    total_liquid: float,
    deployable_now: float,
    macro_level: int,
    playbook: Optional[dict] = None,
) -> dict:
    """資金部署：建議增／減可再投入上限。"""
    pb = playbook or load_playbook()
    cd = pb.get("capital_deployment") or {}
    ratios = cd.get("deploy_ratio_by_level") or {"1": 0.4, "2": 0.3, "3": 0.15}
    floor_pct = float(cd.get("cash_floor_pct_of_liquid") or 0.5)
    step = float(cd.get("step_twd") or 100_000)
    level = str(int(macro_level))
    ratio = float(ratios.get(level, ratios.get("2", 0.3)))
    total = float(total_liquid or 0)
    floor = total * floor_pct
    target = min(total * ratio, max(0.0, total - floor))
    now = float(deployable_now or 0)
    delta = target - now
    action = None
    if delta >= step:
        action = "raise_deploy_budget"
    elif delta <= -step:
        action = "lower_deploy_budget"
    return {
        "action": action,
        "target_deployable": round(target, 0),
        "deployable_now": round(now, 0),
        "delta": round(delta, 0),
        "ratio": ratio,
        "cash_floor": round(floor, 0),
        "level": int(macro_level),
        "rationale": cd.get("rationale", ""),
        "reenable_when": cd.get("reenable_when", ""),
    }


def market_level(closes: list[float]) -> Optional[int]:
    """與 scan_watch_grades.macro_level 同公式：<20MA=3｜乖離≤1.5%=2｜否則=1。"""
    if not closes or len(closes) < 20:
        return None
    px = float(closes[-1])
    ma20 = sum(float(c) for c in closes[-20:]) / 20.0
    if ma20 <= 0:
        return None
    if px < ma20:
        return 3
    return 2 if (px - ma20) / ma20 * 100 <= 1.5 else 1


def suggest_deployable_by_sleeve(
    *,
    total_cash: float,
    gaps_twd: dict,
    levels: dict,
    playbook: Optional[dict] = None,
) -> dict:
    """
    各袖依自己市場的 Level 決定可投入額度（2026-07-20 deploy_gate_backtest 方案E）。

    gaps_twd: {sleeve_key: 距目標配置的缺口(元)}；levels: {'taiex': int, 'us': int}
    避險袖（gold_fx／crypto）依 sleeve_level_source 標為 ungated＝不受景氣閘門限制。
    回傳含各袖額度與合計；合計即新的 deployable_cash_twd。
    """
    pb = playbook or load_playbook()
    cd = pb.get("capital_deployment") or {}
    ratios = {int(k): float(v) for k, v in (cd.get("deploy_ratio_by_level") or
                                            {"1": 0.6, "2": 0.5, "3": 0.3}).items()}
    src = cd.get("sleeve_level_source") or {}
    floor_pct = float(cd.get("cash_floor_pct_of_liquid") or 0.5)

    cash = max(float(total_cash or 0), 0.0)
    positive = {k: max(float(v or 0), 0.0) for k, v in (gaps_twd or {}).items()}
    total_gap = sum(positive.values())
    if cash <= 0 or total_gap <= 0:
        return {"total": 0.0, "by_sleeve": {}, "ratios_used": {}, "total_gap": total_gap}

    by_sleeve, ratios_used = {}, {}
    for key, gap in positive.items():
        if gap <= 0:
            continue
        which = str(src.get(key) or "taiex")
        if which == "ungated":
            r = 1.0
        else:
            lv = levels.get(which)
            r = ratios.get(int(lv), ratios.get(2, 0.5)) if lv else ratios.get(2, 0.5)
        share = cash * (gap / total_gap)
        amt = min(share * r, gap)  # 不超過該袖缺口
        by_sleeve[key] = round(amt, 0)
        ratios_used[key] = r

    # 地板：總現金的 floor_pct 永不動用，各袖加總不得越過
    max_deployable = max(cash * (1.0 - floor_pct), 0.0)
    total = min(sum(by_sleeve.values()), max_deployable)
    if total < sum(by_sleeve.values()) and by_sleeve:
        scale = total / sum(by_sleeve.values())
        by_sleeve = {k: round(v * scale, 0) for k, v in by_sleeve.items()}
    return {
        "total": round(total, 0),
        "cash_floor": round(cash * floor_pct, 0),
        "by_sleeve": by_sleeve,
        "ratios_used": ratios_used,
        "levels": dict(levels),
        "total_gap": round(total_gap, 0),
    }


def write_intents(intents: list[dict], extra: Optional[dict] = None) -> str:
    os.makedirs(os.path.dirname(INTENTS_PATH), exist_ok=True)
    by_code: dict[str, dict] = {}
    cash_intents: list[dict] = []
    for i in intents:
        c = str(i.get("code") or "")
        if c == "CASH":
            cash_intents.append(i)
            continue
        if not c:
            continue
        cur = by_code.get(c)
        if cur is None or PRIORITY_RANK.get(i.get("action"), 99) < PRIORITY_RANK.get(
            cur.get("action"), 99
        ):
            by_code[c] = i
    final = list(by_code.values()) + cash_intents
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "推播≠已成交／已改設定；deployable 須人工確認後改 my_targets",
        "intents": final,
        "extra": extra or {},
    }
    with open(INTENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return INTENTS_PATH


def format_intent_line(i: dict) -> str:
    qty = i.get("qty")
    unit = i.get("unit") or ""
    twd = i.get("twd")
    qty_s = f"{qty}{unit}" if qty is not None else "—"
    twd_s = f"約 {twd:,.0f} 元" if twd else ""
    return (
        f"[{i.get('action')}] {i.get('code')} {i.get('side')} {qty_s} {twd_s}｜"
        f"{i.get('rationale', '')[:80]}"
    )
