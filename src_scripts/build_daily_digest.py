# -*- coding: utf-8 -*-
"""
Fixed digests: 07:30 / 13:45 (trading days) / 19:00 Taipei.

  python src_scripts/build_daily_digest.py --slot am
  python src_scripts/build_daily_digest.py --slot close
  python src_scripts/build_daily_digest.py --slot pm
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from event_bus import active_events  # noqa: E402
from notify import notify  # noqa: E402
from tw_time import taiwan_now  # noqa: E402

LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")
PENDING_PATH = os.path.join(WORKSPACE, "reports", "latest", "eod_pending_ops.json")
CURRENT_PATH = os.path.join(WORKSPACE, "reports", "latest", "CURRENT_STATE.md")
PLAYBOOK_PATH = os.path.join(WORKSPACE, "reports", "latest", "action_intents.json")


def _load(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(".md"):
            return f.read()
        return json.load(f)


def is_tw_trading_day(d: date | None = None) -> bool:
    """交易日判定：先看 warehouse 今日是否有 TAIEX 新 bar；無資料時退回平日判斷。

    （tw_eod ingest 於 14:00 起寫入；13:45 digest_close 前若當日为假日不會有新 bar。
    注意：13:45 時當日 bar 尚未 ingest，故以「平日且非長假」邏輯輔助——
    若最後一根 TAIEX bar 距今超過 4 個日曆日，視為連假中，略過收盤報。）
    """
    d = d or taiwan_now().date()
    if d.weekday() >= 5:
        return False
    try:
        from ingest_common import read_ohlc_csv, symbol_csv_path

        rows = read_ohlc_csv(symbol_csv_path("twse", "TAIEX"))
        if rows:
            last = date.fromisoformat(rows[-1]["date"])
            if last == d:
                return True
            # 最後 bar 落後超過 4 個日曆日 → 連假／資料中斷，不當交易日推收盤報
            if (d - last).days > 4:
                return False
    except Exception:
        pass
    return True


def _money(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def build_body(slot: str) -> tuple[str, str]:
    tw = taiwan_now()
    levels = _load(LEVELS_PATH)
    targets = _load(TARGETS_PATH)
    pending = _load(PENDING_PATH)
    intents = _load(PLAYBOOK_PATH)

    macro = levels.get("macro_level", "—")
    as_of = levels.get("as_of") or tw.strftime("%Y-%m-%d")

    # Capital / holdings snapshot
    lines = [
        f"時點 {tw.strftime('%Y-%m-%d %H:%M')}（台北）｜slot={slot}",
        f"資料 as_of：{as_of}｜大盤 Level：**{macro}**",
        "",
        "【部位】",
    ]
    for h in targets.get("portfolio") or []:
        code = h.get("code")
        name = h.get("name", "")
        shares = h.get("shares")
        cost = h.get("cost")
        row = next(
            (r for r in (levels.get("levels") or []) if str(r.get("code")) == str(code)),
            None,
        )
        px = row.get("close") if row else None
        roi = row.get("roi_pct") if row else None
        extra = ""
        if px is not None:
            extra = f" 現價 {px}"
        if roi is not None:
            try:
                extra += f" ROI {float(roi):+.1f}%"
            except (TypeError, ValueError):
                pass
        lines.append(f"• {code} {name} ×{shares} 成本 {cost}{extra}")

    gp = (targets.get("multi_asset") or {}).get("gold_passbook") or {}
    if gp.get("qty"):
        lines.append(
            f"• 黃金存摺 {gp.get('qty')}g ≈ {_money(gp.get('approx_twd'))} TWD"
        )
    fx = (targets.get("multi_asset") or {}).get("forex_usd") or {}
    if fx.get("usd") or fx.get("qty"):
        lines.append(f"• 美金現金 {fx.get('usd') or fx.get('qty')} USD")

    # 唯一真相：multi_asset.deployable_cash_twd（與 CURRENT_STATE 一致）
    deployable = (targets.get("multi_asset") or {}).get("deployable_cash_twd")
    if deployable is not None:
        lines.append(f"• 可再投入 ≈ {_money(deployable)} TWD")

    # Active events
    lines.append("")
    lines.append("【進行中事件】")
    act = active_events()
    if not act:
        lines.append("• （無）")
    else:
        for ev in act:
            eid = ev.get("event_id")
            since = (ev.get("since") or "")[:16]
            meta = ev.get("meta") or {}
            lines.append(f"• {eid} since {since} {meta}")

    # Actions / pending
    lines.append("")
    lines.append("【需執行／待辦】")
    eod_actions = levels.get("eod_actions") or []
    ops = []
    if isinstance(pending, dict):
        ops = pending.get("ops") or pending.get("items") or pending.get("actions") or []
    if isinstance(ops, list) and ops:
        for op in ops[:12]:
            if isinstance(op, str):
                lines.append(f"• {op}")
            elif isinstance(op, dict):
                lines.append(f"• {op.get('text') or op.get('title') or op}")
    elif eod_actions:
        for a in eod_actions[:12]:
            lines.append(f"• {a}")
    else:
        lines.append("• （無急迫待辦；詳見 levels／playbook）")

    if isinstance(intents, dict) and intents.get("intents"):
        lines.append("")
        lines.append("【Playbook 意圖摘要】")
        for it in (intents.get("intents") or [])[:8]:
            if isinstance(it, dict):
                lines.append(
                    f"• {it.get('code') or ''} {it.get('action') or it.get('intent') or it}"
                )

    if slot == "close":
        lines.append("")
        lines.append("【收盤窗】破防守／年線事件以收盤確認為準；執行 ≥13:40 或隔日開盤。")
    if slot == "am":
        lines.append("")
        lines.append("【早報】開盤 09:00–09:30 凍結恐慌單；隔夜事件見上。")
    if slot == "pm":
        lines.append("")
        lines.append("【晚報】含美股／加密視窗收斂；明日待辦以上方為準。")

    title_map = {
        "am": f"早報現況 {tw.strftime('%m/%d %H:%M')}",
        "close": f"收盤執行報 {tw.strftime('%m/%d %H:%M')}",
        "pm": f"晚報現況 {tw.strftime('%m/%d %H:%M')}",
    }
    title = title_map.get(slot, f"日報 {tw.strftime('%m/%d %H:%M')}")
    body = "\n".join(lines)
    return title, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["am", "close", "pm"], required=True)
    ap.add_argument("--force-notify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-holiday-close",
        action="store_true",
        help="假日仍推 13:45（預設略過）",
    )
    args = ap.parse_args()

    if args.slot == "close" and not args.allow_holiday_close and not is_tw_trading_day():
        print("[digest] close slot skipped (非交易日)")
        return 0

    # Refresh event state quietly before digest (no edge spam)
    try:
        from eval_market_events import run_all

        run_all(
            close_confirm=(args.slot == "close"),
            quiet=True,
            force=False,
        )
    except Exception as e:
        print(f"[digest] eval quiet error: {e}")

    title, body = build_body(args.slot)
    out_path = os.path.join(
        WORKSPACE, "reports", "latest", f"digest_{args.slot}.md"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{body}\n")
    print(body)

    if args.dry_run:
        print("[digest] dry-run, not notifying")
        return 0

    # Digests always notify (daily dedupe by rule_id)
    prev = os.environ.get("TWSTOCKALS_DIGEST_ONLY")
    if prev:
        os.environ["TWSTOCKALS_DIGEST_ONLY"] = "0"
    try:
        notify(
            title,
            body[:3500],
            symbol="DIGEST",
            rule_id=f"digest_{args.slot}",
            urgency="eod_action",
            force=args.force_notify,
        )
    finally:
        if prev is not None:
            os.environ["TWSTOCKALS_DIGEST_ONLY"] = prev
    return 0


if __name__ == "__main__":
    sys.exit(main())
