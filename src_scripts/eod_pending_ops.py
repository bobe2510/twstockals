# -*- coding: utf-8 -*-
"""Persist / reload EOD ops for next-morning 08:30 preopen reminder (0050 / 正2)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
PENDING_PATH = os.path.join(WORKSPACE, "reports", "latest", "eod_pending_ops.json")

# 持續操作核心 ETF
CORE_OPS_CODES = frozenset({"0050", "00631L"})

_ACTION_RE = re.compile(
    r"(減碼|空倉|加碼|小加|小減|請買進|請加碼|進場|達標停利|移動減|賣約|先賣|再賣|可小加|可小減)"
)
_HOLD_ONLY_RE = re.compile(r"(續抱|禁止加碼|不加碼|底倉續抱|僅深拉回|無急迫)")


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(PENDING_PATH), exist_ok=True)


def load_pending() -> dict:
    if not os.path.exists(PENDING_PATH):
        return {"as_of": None, "items": [], "reminded_at": None}
    with open(PENDING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pending(doc: dict) -> None:
    _ensure_dir()
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def is_actionable_text(text: str) -> bool:
    t = str(text or "")
    if not t.strip():
        return False
    if _ACTION_RE.search(t):
        return True
    # 純續抱／禁止加碼 → 不算「建議操作」
    if _HOLD_ONLY_RE.search(t) and not _ACTION_RE.search(t):
        return False
    return False


def extract_code(text: str) -> Optional[str]:
    for code in CORE_OPS_CODES:
        if code in text:
            return code
    return None


def filter_core_ops(actions: list[str]) -> list[dict[str, str]]:
    out = []
    for a in actions:
        code = extract_code(a)
        if not code:
            continue
        if not is_actionable_text(a):
            continue
        out.append({"code": code, "text": a, "source": "eod"})
    return out


def merge_pending_items(
    *,
    as_of: str,
    items: list[dict[str, str]],
    as_of_ts: Optional[str] = None,
    replace_same_day: bool = True,
) -> dict:
    """寫入／合併待提醒操作；同日可覆蓋或合併去重。"""
    cur = load_pending()
    if replace_same_day and cur.get("as_of") == as_of:
        existing = []
    elif cur.get("as_of") == as_of:
        existing = list(cur.get("items") or [])
    else:
        existing = []

    seen = {f"{x.get('code')}|{x.get('text')}" for x in existing}
    for it in items:
        key = f"{it.get('code')}|{it.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        existing.append(it)

    doc = {
        "as_of": as_of,
        "as_of_ts": as_of_ts or datetime.now().isoformat(timespec="seconds"),
        "items": existing,
        "reminded_at": None,
        "reminded_for_as_of": None,
    }
    save_pending(doc)
    return doc


def append_watch_ops(as_of: str, code: str, text: str, as_of_ts: Optional[str] = None) -> dict:
    if code not in CORE_OPS_CODES:
        return load_pending()
    if not any(k in text for k in ("買進", "加碼", "進場", "減碼", "賣")):
        return load_pending()
    cur = load_pending()
    items = list(cur.get("items") or []) if cur.get("as_of") == as_of else []
    item = {"code": code, "text": text, "source": "watch"}
    key = f"{code}|{text}"
    if key not in {f"{x.get('code')}|{x.get('text')}" for x in items}:
        items.append(item)
    doc = {
        "as_of": as_of,
        "as_of_ts": as_of_ts or datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "reminded_at": None,
        "reminded_for_as_of": None,
    }
    save_pending(doc)
    return doc


def previous_session_date(today: datetime) -> str:
    """前一交易日（略過六日）。"""
    d = today.date() - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5 Sun=6
        d -= timedelta(days=1)
    return d.isoformat()


def pending_for_preopen(now: datetime) -> dict[str, Any]:
    """
    若有「昨日（或上周五）EOD」未提醒的 0050／正2 操作，回傳 pending doc；否則空 items。
    """
    doc = load_pending()
    items = list(doc.get("items") or [])
    as_of = doc.get("as_of")
    if not items or not as_of:
        return {"as_of": as_of, "items": [], "reason": "empty"}
    expect = previous_session_date(now)
    today = now.date().isoformat()
    if as_of >= today:
        return {"as_of": as_of, "items": [], "reason": "same_day"}
    if as_of != expect:
        try:
            as_d = datetime.strptime(as_of, "%Y-%m-%d").date()
            if (now.date() - as_d).days > 4:
                return {"as_of": as_of, "items": [], "reason": "stale"}
        except ValueError:
            return {"as_of": as_of, "items": [], "reason": "bad_date"}
    if doc.get("reminded_for_as_of") == as_of:
        return {"as_of": as_of, "items": [], "reason": "already_reminded"}
    return doc


def mark_reminded(now: datetime) -> None:
    doc = load_pending()
    doc["reminded_at"] = now.isoformat(timespec="seconds")
    doc["reminded_for_as_of"] = doc.get("as_of")
    save_pending(doc)
