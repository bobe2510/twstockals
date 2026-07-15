# -*- coding: utf-8 -*-
"""Load per-product buy_min_grade / suggest amounts from grade_buy_policy.json.

Also tracks deploy ladder progress (enter vs A/S add-on) in
reports/latest/deploy_ladder_state.json.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
POLICY_PATH = os.path.join(WORKSPACE, "config", "grade_buy_policy.json")
LADDER_STATE_PATH = os.path.join(
    WORKSPACE, "reports", "latest", "deploy_ladder_state.json"
)

from tw_time import taiwan_now  # noqa: E402

_DEFAULT_RANK = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4}
_DEFAULT_ROUTINE = ["GOLD", "0050", "00631L", "QQQ", "QQQM"]
_DEFAULT_OPPORTUNITY = ["USDTWD", "VOO", "VXUS"]


def load_grade_buy_policy() -> dict:
    if not os.path.exists(POLICY_PATH):
        return {"grade_rank": _DEFAULT_RANK, "products": {}}
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def grade_rank_map(policy: Optional[dict] = None) -> dict:
    p = policy or load_grade_buy_policy()
    return dict(p.get("grade_rank") or _DEFAULT_RANK)


def product_policy(code: str, policy: Optional[dict] = None) -> dict:
    p = policy or load_grade_buy_policy()
    return dict((p.get("products") or {}).get(str(code).upper()) or {})


def cash_pools_config(policy: Optional[dict] = None) -> dict:
    p = policy or load_grade_buy_policy()
    pools = dict(p.get("cash_pools") or {})
    deployable = int(
        pools.get("deployable_twd")
        or p.get("deployable_cash_twd")
        or 2_000_000
    )
    opp_share = float(pools.get("opportunity_share") or 0.25)
    opp_share = min(0.9, max(0.05, opp_share))
    routine = [str(x).upper() for x in (pools.get("routine_codes") or _DEFAULT_ROUTINE)]
    opportunity = [
        str(x).upper() for x in (pools.get("opportunity_codes") or _DEFAULT_OPPORTUNITY)
    ]
    return {
        "deployable_twd": deployable,
        "opportunity_share": opp_share,
        "opportunity_budget": int(round(deployable * opp_share)),
        "routine_budget": int(deployable - round(deployable * opp_share)),
        "routine_codes": routine,
        "opportunity_codes": opportunity,
    }


def pool_kind(code: str, policy: Optional[dict] = None) -> str:
    cfg = cash_pools_config(policy)
    c = str(code).upper()
    if c in cfg["opportunity_codes"]:
        return "opportunity"
    return "routine"


def _spent_for_codes(state: Optional[dict], codes: list[str]) -> int:
    st = state if state is not None else load_ladder_state()
    products = st.get("products") or {}
    total = 0
    for c in codes:
        raw = products.get(str(c).upper()) or {}
        total += int(raw.get("invested_twd") or 0)
    return total


def cash_pool_snapshot(
    state: Optional[dict] = None, policy: Optional[dict] = None
) -> dict[str, Any]:
    """常態／機會池預算與剩餘（依 deploy_ladder_state 已記投入）。"""
    cfg = cash_pools_config(policy)
    routine_spent = _spent_for_codes(state, cfg["routine_codes"])
    opp_spent = _spent_for_codes(state, cfg["opportunity_codes"])
    return {
        **cfg,
        "routine_spent": routine_spent,
        "opportunity_spent": opp_spent,
        "routine_remaining": max(0, cfg["routine_budget"] - routine_spent),
        "opportunity_remaining": max(0, cfg["opportunity_budget"] - opp_spent),
    }


def format_cash_pool_footer(
    code: str,
    *,
    state: Optional[dict] = None,
    policy: Optional[dict] = None,
    suggest_twd: int = 0,
) -> str:
    """推播／報告用：剩餘機會金＋本池剩餘。"""
    snap = cash_pool_snapshot(state, policy)
    kind = pool_kind(code, policy)
    opp_left = snap["opportunity_remaining"]
    if kind == "opportunity":
        after = max(0, opp_left - max(0, int(suggest_twd)))
        return (
            f"動用**機會準備金**｜本次後剩餘機會金約 **{after:,}** 元"
            f"（池 {snap['opportunity_budget']:,}／已用 {snap['opportunity_spent']:,}）"
        )
    rtn_left = snap["routine_remaining"]
    after = max(0, rtn_left - max(0, int(suggest_twd)))
    return (
        f"常態部署池剩餘約 **{after:,}** 元｜"
        f"**剩餘機會金 {opp_left:,}** 元（保留美金／VOO／VXUS）"
    )


def meets_buy_min(grade: str, code: str, policy: Optional[dict] = None) -> bool:
    pol = product_policy(code, policy)
    min_g = pol.get("buy_min_grade")
    if not min_g:
        return False
    ranks = grade_rank_map(policy)
    return ranks.get(str(grade).upper(), -1) >= ranks.get(str(min_g).upper(), 99)


def is_above_min(grade: str, code: str, policy: Optional[dict] = None) -> bool:
    """True when grade strictly higher than buy_min_grade (較推薦)."""
    pol = product_policy(code, policy)
    min_g = pol.get("buy_min_grade")
    if not min_g:
        return False
    ranks = grade_rank_map(policy)
    return ranks.get(str(grade).upper(), -1) > ranks.get(str(min_g).upper(), 99)


def suggest_for_grade(code: str, grade: str, policy: Optional[dict] = None) -> int:
    pol = product_policy(code, policy)
    amts = pol.get("suggest_twd") or {}
    try:
        return int(amts.get(str(grade).upper(), 0) or 0)
    except (TypeError, ValueError):
        return 0


def ladder_amount_for_grade(code: str, grade: str, policy: Optional[dict] = None) -> int:
    pol = product_policy(code, policy)
    if str(pol.get("sizing") or "flat").lower() == "ladder":
        amts = pol.get("ladder_twd") or {}
        try:
            v = int(amts.get(str(grade).upper(), 0) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return suggest_for_grade(code, grade, policy)


def buy_stance(grade: str, code: str, policy: Optional[dict] = None) -> Optional[str]:
    """
    Returns:
      None — below min, do not push buy
      'buy' — at min threshold → 請買進
      'prefer' — above min → 較推薦
    """
    if not meets_buy_min(grade, code, policy):
        return None
    if is_above_min(grade, code, policy):
        return "prefer"
    return "buy"


def load_ladder_state() -> dict:
    if not os.path.exists(LADDER_STATE_PATH):
        return {"version": 1, "products": {}, "updated_at": None}
    with open(LADDER_STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "products" not in data:
        data = {"version": 1, "products": data, "updated_at": None}
    return data


def save_ladder_state(state: dict) -> None:
    os.makedirs(os.path.dirname(LADDER_STATE_PATH), exist_ok=True)
    state = dict(state)
    state["updated_at"] = taiwan_now().replace(tzinfo=None).isoformat(timespec="seconds")
    state.setdefault("version", 1)
    state.setdefault("products", {})
    with open(LADDER_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def product_ladder_state(code: str, state: Optional[dict] = None) -> dict:
    st = state if state is not None else load_ladder_state()
    raw = (st.get("products") or {}).get(str(code).upper()) or {}
    return {
        "invested_twd": int(raw.get("invested_twd") or 0),
        "max_grade_filled": (raw.get("max_grade_filled") or None),
        "cycle_id": raw.get("cycle_id") or None,
        "last_action": raw.get("last_action"),
        "last_amount": raw.get("last_amount"),
        "updated_at": raw.get("updated_at"),
    }


def reset_ladder_cycle(
    code: str, state: Optional[dict] = None, *, save: bool = True
) -> dict:
    """出場後重置該商品階梯進度。"""
    st = state if state is not None else load_ladder_state()
    products = st.setdefault("products", {})
    products[str(code).upper()] = {
        "invested_twd": 0,
        "max_grade_filled": None,
        "cycle_id": None,
        "last_action": "reset",
        "last_amount": 0,
        "updated_at": taiwan_now().replace(tzinfo=None).isoformat(timespec="seconds"),
    }
    if save:
        save_ladder_state(st)
    return st


def record_ladder_fill(
    code: str,
    grade: str,
    amount: int,
    action: str,
    state: Optional[dict] = None,
    *,
    save: bool = True,
) -> dict:
    """記錄已推播／已執行的進場或加碼（可手動對帳覆寫）。"""
    st = state if state is not None else load_ladder_state()
    products = st.setdefault("products", {})
    key = str(code).upper()
    cur = product_ladder_state(key, st)
    ranks = grade_rank_map()
    g = str(grade).upper()
    max_g = cur.get("max_grade_filled")
    if max_g is None or ranks.get(g, -1) > ranks.get(str(max_g).upper(), -1):
        max_g = g
    cycle_id = cur.get("cycle_id") or taiwan_now().strftime("%Y%m%d%H%M%S")
    products[key] = {
        "invested_twd": int(cur.get("invested_twd") or 0) + max(0, int(amount)),
        "max_grade_filled": max_g,
        "cycle_id": cycle_id,
        "last_action": action,
        "last_amount": int(amount),
        "updated_at": taiwan_now().replace(tzinfo=None).isoformat(timespec="seconds"),
    }
    if save:
        save_ladder_state(st)
    return st


def next_ladder_action(
    grade: str,
    code: str,
    *,
    state: Optional[dict] = None,
    policy: Optional[dict] = None,
    room_twd: Optional[int] = None,
    pause_ib: bool = False,
) -> dict[str, Any]:
    """
    Decide enter / add / none for the current grade given deploy progress.

    Returns keys:
      action: 'enter' | 'add' | 'none'
      stance: 'buy' | 'prefer' | None
      suggest_twd: int
      sizing: 'ladder' | 'flat'
      max_grade_filled, invested_twd, min_grade, blocked, ...
    """
    pol = product_policy(code, policy)
    ranks = grade_rank_map(policy)
    g = str(grade).upper()
    min_g = str(pol.get("buy_min_grade") or "").upper() or None
    sizing = str(pol.get("sizing") or "flat").lower()
    if sizing not in ("ladder", "flat"):
        sizing = "flat"

    base = {
        "action": "none",
        "stance": None,
        "suggest_twd": 0,
        "sizing": sizing,
        "min_grade": min_g,
        "blocked": None,
        "max_grade_filled": None,
        "invested_twd": 0,
        "budget_twd": pol.get("budget_twd"),
        "sell_note": pol.get("sell_note"),
        "pool": pool_kind(code, policy),
        "opportunity_remaining": None,
        "routine_remaining": None,
    }

    if pol.get("require_ib") and pause_ib:
        base["blocked"] = "pause_us_ib"
        return base
    if pol.get("pause_add_default"):
        # BTC etc.: never suggest add amounts
        if suggest_for_grade(code, g, policy) <= 0 and ladder_amount_for_grade(
            code, g, policy
        ) <= 0:
            base["blocked"] = "pause_add"
            return base

    if not min_g or not meets_buy_min(g, code, policy):
        return base

    cur = product_ladder_state(code, state)
    filled = cur.get("max_grade_filled")
    invested = int(cur.get("invested_twd") or 0)
    snap = cash_pool_snapshot(state, policy)
    base["max_grade_filled"] = filled
    base["invested_twd"] = invested
    base["opportunity_remaining"] = snap["opportunity_remaining"]
    base["routine_remaining"] = snap["routine_remaining"]

    filled_rank = ranks.get(str(filled).upper(), -1) if filled else -1
    g_rank = ranks.get(g, -1)
    kind = base["pool"]

    def _cap(amt: int) -> int:
        a = max(0, int(amt))
        if room_twd is not None:
            a = min(a, max(0, int(room_twd)))
        budget = pol.get("budget_twd")
        if budget is not None:
            a = min(a, max(0, int(budget) - invested))
        pool_left = (
            snap["opportunity_remaining"]
            if kind == "opportunity"
            else snap["routine_remaining"]
        )
        a = min(a, max(0, int(pool_left)))
        return max(0, a)

    def _ok(action: str, stance: str, amt: int) -> dict:
        return {
            **base,
            "action": action,
            "stance": stance,
            "suggest_twd": amt,
            "cash_pool_note": format_cash_pool_footer(
                code, state=state, policy=policy, suggest_twd=amt
            ),
        }

    # 尚未進場：用當前評等階金額（直接跳 A/S 則用該階）
    if filled is None:
        amt = _cap(ladder_amount_for_grade(code, g, policy))
        if amt <= 0:
            # flat 後備：門檻階金額
            amt = _cap(suggest_for_grade(code, min_g, policy))
        if amt <= 0:
            base["blocked"] = "pool_empty" if (
                (kind == "opportunity" and snap["opportunity_remaining"] <= 0)
                or (kind == "routine" and snap["routine_remaining"] <= 0)
            ) else base.get("blocked")
            return base
        stance = "prefer" if is_above_min(g, code, policy) else "buy"
        return _ok("enter", stance, amt)

    # 同階或更低：不重複
    if g_rank <= filled_rank:
        return base

    # 評等升高
    if sizing == "ladder":
        amt = _cap(ladder_amount_for_grade(code, g, policy))
        if amt <= 0:
            return base
        return _ok("add", "prefer", amt)

    # flat：升級只改語氣、不加碼 → 不推金額
    return {
        **base,
        "action": "none",
        "stance": "prefer",
        "suggest_twd": 0,
        "blocked": "flat_no_add",
    }


def apply_policy_amount(
    code: str,
    grade: str,
    *,
    policy: Optional[dict] = None,
    room_twd: Optional[int] = None,
    pause_ib: bool = False,
    state: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Resolve push stance + capped suggest_twd for a product/grade.
    Prefer next_ladder_action (enter/add aware); falls back cleanly for flat.
    """
    return next_ladder_action(
        grade,
        code,
        state=state,
        policy=policy,
        room_twd=room_twd,
        pause_ib=pause_ib,
    )
