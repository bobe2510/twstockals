# -*- coding: utf-8 -*-
"""Persist / reload EOD ops（0050／正2 待辦）。

消費端＝隔日 07:30 digest_am（獨立 08:30 preopen 推播鏈已於 2026-07 移除）。
preopen_reminder.md 僅作 pending 的人讀快照。
"""
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
PREOPEN_REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "preopen_reminder.md")

# 持續操作核心 ETF
CORE_OPS_CODES = frozenset({"0050", "00631L"})

_ACTION_RE = re.compile(
    r"(減碼|空倉|加碼|小加|小減|請買進|請加碼|允許買進|建議買進|強烈建議|進場|達標停利|移動減|賣約|先賣|再賣|可小加|可小減)"
)
_HOLD_ONLY_RE = re.compile(r"(續抱|禁止加碼|不加碼|底倉續抱|僅深拉回|無急迫)")
# 與「年線上／續抱」矛盾的過期減碼句
_STALE_YEAR_BREAK_RE = re.compile(r"(大盤破年線|年線下|破年線)")


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


def clear_pending(*, reason: str = "cleared", as_of: Optional[str] = None) -> dict:
    """清空隔日提醒，避免舊減碼／破年線文案殘留。"""
    doc = {
        "as_of": as_of,
        "as_of_ts": datetime.now().isoformat(timespec="seconds"),
        "items": [],
        "reminded_at": None,
        "reminded_for_as_of": None,
        "cleared_reason": reason,
    }
    save_pending(doc)
    write_preopen_report(doc, note=reason)
    return doc


def is_actionable_text(text: str) -> bool:
    t = str(text or "")
    if not t.strip():
        return False
    # 純續抱／禁止加碼 → 不算「建議操作」
    if _HOLD_ONLY_RE.search(t) and not re.search(
        r"(【減碼|【空倉|【可小減|【減碼優先|【可移動減|請買進|請加碼|允許買進|建議買進|強烈建議|加碼（)",
        t,
    ):
        # 含「再考慮減」但主軸是續抱禁止加碼 → 不進 preopen
        if "續抱" in t or "禁止加碼" in t:
            return False
    if _ACTION_RE.search(t):
        return True
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
        # 文案自稱年線上卻又寫破年線 → 丟棄（防舊邏輯／截斷污染）
        if "年線上" in a and _STALE_YEAR_BREAK_RE.search(a):
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
    """寫入／合併待提醒操作。換日或同日 replace 時以本次為準；空清單＝清空舊項。"""
    cur = load_pending()
    if replace_same_day or cur.get("as_of") != as_of:
        existing: list[dict[str, str]] = []
    else:
        existing = list(cur.get("items") or [])

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
        "cleared_reason": None if existing else "eod_no_actionable_core_ops",
    }
    save_pending(doc)
    write_preopen_report(doc)
    return doc


def append_watch_ops(as_of: str, code: str, text: str, as_of_ts: Optional[str] = None) -> dict:
    if code not in CORE_OPS_CODES:
        return load_pending()
    if not any(k in text for k in ("買進", "加碼", "進場", "減碼", "賣", "允許", "建議", "強烈")):
        return load_pending()
    # 換日：只留當日；同日合併
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
        "cleared_reason": None,
    }
    save_pending(doc)
    write_preopen_report(doc)
    return doc


def previous_session_date(today: datetime) -> str:
    """前一交易日（略過六日）。"""
    d = today.date() - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5 Sun=6
        d -= timedelta(days=1)
    return d.isoformat()


def pending_for_preopen(now: datetime) -> dict[str, Any]:
    """
    僅接受「嚴格＝前一交易日」且尚未提醒的 0050／正2 操作。
    不再用 4 日寬限把更舊的減碼叫回來。
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
        # 過期：順便清檔，避免報告殘留誤導
        clear_pending(reason=f"stale_as_of_{as_of}_expect_{expect}", as_of=as_of)
        return {"as_of": as_of, "items": [], "reason": "stale"}
    if doc.get("reminded_for_as_of") == as_of:
        return {"as_of": as_of, "items": [], "reason": "already_reminded"}
    return doc


def mark_reminded(now: datetime) -> None:
    doc = load_pending()
    doc["reminded_at"] = now.isoformat(timespec="seconds")
    doc["reminded_for_as_of"] = doc.get("as_of")
    save_pending(doc)
    write_preopen_report(doc, note="already_reminded")


def write_preopen_report(doc: dict, *, note: Optional[str] = None) -> None:
    """讓 preopen_reminder.md 永遠對齊 pending，不留舊減碼句。"""
    try:
        from tw_time import taiwan_now

        now = taiwan_now()
    except Exception:
        now = datetime.now()
    items = list(doc.get("items") or [])
    as_of = doc.get("as_of") or "—"
    reason = note or doc.get("cleared_reason") or ""
    lines = [
        "# 開盤前提醒｜0050／正2\n\n",
        f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n",
        f"來源日：**{as_of}** EOD  \n\n",
    ]
    if not items:
        lines.append(f"今日無待執行操作（{reason or 'empty'}）。\n\n")
        lines.append(
            "> 對齊最新策略：大盤年線上＋Level3 → 正2 **續抱、禁止加碼**；"
            "勿沿用過期「破年線減碼」文案。  \n"
        )
    else:
        lines.append(
            "> 前一日收盤建議尚未執行則請於開盤後穩定期處理；**09:00~09:30 不殺**。  \n\n"
        )
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. **{it.get('code')}**：{it.get('text')}  \n")
    os.makedirs(os.path.dirname(PREOPEN_REPORT_PATH), exist_ok=True)
    with open(PREOPEN_REPORT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    # 手動對齊：python src_scripts/eod_pending_ops.py --clear
    import sys

    if "--clear" in sys.argv:
        clear_pending(reason="manual_clear")
        print("cleared", PENDING_PATH)
    else:
        print(json.dumps(load_pending(), ensure_ascii=False, indent=2))
