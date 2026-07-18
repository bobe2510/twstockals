# -*- coding: utf-8 -*-
"""
Edge-triggered market / system events → Telegram.

State: reports/latest/event_state.json
  events[event_id] = {active, since, last_change, notify_clear, meta, reclaim_streak, fail_streak, ok_streak}

apply_desired():
  False→True → push onset (once)
  True→True  → silence (optional meta update)
  True→False → push clear only if notify_clear=True
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
STATE_PATH = os.path.join(WORKSPACE, "reports", "latest", "event_state.json")

try:
    from tw_time import taiwan_now
except Exception:  # pragma: no cover

    def taiwan_now() -> datetime:
        return datetime.now()


def _now_iso() -> str:
    return taiwan_now().isoformat(timespec="seconds")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"updated_at": None, "events": {}}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "events": {}}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state["updated_at"] = _now_iso()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def active_events(state: Optional[dict] = None) -> list[dict]:
    st = state if state is not None else load_state()
    out = []
    for eid, ev in (st.get("events") or {}).items():
        if ev.get("active"):
            out.append({"event_id": eid, **ev})
    out.sort(key=lambda x: x.get("since") or "")
    return out


def _push(title: str, body: str, rule_id: str, *, force: bool = False) -> None:
    # Bypass digest-only quiet for EVENT pushes
    prev = os.environ.get("TWSTOCKALS_DIGEST_ONLY")
    if prev:
        os.environ["TWSTOCKALS_DIGEST_ONLY"] = "0"
    try:
        from notify import notify

        notify(
            title,
            body,
            symbol="EVENT",
            rule_id=rule_id,
            urgency="emergency",
            force=force,
        )
    finally:
        if prev is not None:
            os.environ["TWSTOCKALS_DIGEST_ONLY"] = prev


def apply_desired(
    event_id: str,
    active: bool,
    *,
    title_on: str,
    body_on: str,
    title_off: str = "",
    body_off: str = "",
    notify_clear: bool = True,
    meta: Optional[dict] = None,
    force_notify: bool = False,
    quiet: bool = False,
) -> str:
    """
    Update event and optionally notify.
    Returns: 'onset' | 'clear' | 'hold_on' | 'hold_off' | 'noop'
    """
    state = load_state()
    events = state.setdefault("events", {})
    prev = events.get(event_id) or {}
    was = bool(prev.get("active"))
    now_active = bool(active)
    meta = dict(meta or {})

    if was == now_active:
        # refresh meta while holding
        entry = dict(prev)
        entry["active"] = now_active
        if meta:
            entry.setdefault("meta", {}).update(meta)
        entry["notify_clear"] = notify_clear if "notify_clear" not in prev else prev.get(
            "notify_clear", notify_clear
        )
        events[event_id] = entry
        save_state(state)
        return "hold_on" if now_active else "hold_off"

    if now_active and not was:
        entry = {
            "active": True,
            "since": _now_iso(),
            "last_change": _now_iso(),
            "notify_clear": notify_clear,
            "meta": meta,
            "reclaim_streak": 0,
            "fail_streak": int(prev.get("fail_streak") or 0),
            "ok_streak": 0,
        }
        events[event_id] = entry
        save_state(state)
        if not quiet:
            _push(title_on, body_on, f"onset_{event_id}", force=force_notify)
        return "onset"

    # clear
    entry = dict(prev)
    entry["active"] = False
    entry["last_change"] = _now_iso()
    entry["cleared_at"] = _now_iso()
    if meta:
        entry.setdefault("meta", {}).update(meta)
    entry["notify_clear"] = notify_clear
    events[event_id] = entry
    save_state(state)
    do_clear = bool(prev.get("notify_clear", notify_clear)) and notify_clear
    if do_clear and not quiet and (title_off or body_off):
        _push(
            title_off or f"事件解除：{event_id}",
            body_off or "狀態已解除。",
            f"clear_{event_id}",
            force=force_notify,
        )
        return "clear"
    return "noop"


def bump_streak(event_id: str, *, success: bool) -> dict:
    """Track consecutive fail/ok for ingest-style events. Returns updated entry."""
    state = load_state()
    events = state.setdefault("events", {})
    entry = dict(events.get(event_id) or {"active": False, "meta": {}})
    if success:
        entry["ok_streak"] = int(entry.get("ok_streak") or 0) + 1
        entry["fail_streak"] = 0
    else:
        entry["fail_streak"] = int(entry.get("fail_streak") or 0) + 1
        entry["ok_streak"] = 0
    events[event_id] = entry
    save_state(state)
    return entry


def set_reclaim_streak(event_id: str, streak: int) -> None:
    state = load_state()
    events = state.setdefault("events", {})
    entry = dict(events.get(event_id) or {"active": False, "meta": {}})
    entry["reclaim_streak"] = int(streak)
    events[event_id] = entry
    save_state(state)


def get_event(event_id: str) -> dict:
    return dict((load_state().get("events") or {}).get(event_id) or {})
