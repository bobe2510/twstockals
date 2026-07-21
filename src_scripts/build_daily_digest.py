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

    # Active events（中文標籤，避免代號被漏看）
    lines.append("")
    lines.append("【進行中事件】")
    event_labels = {
        "macro_level": "大盤警戒",
        "yearline_taiex_00631L": "正2/大盤破年線",
        "us_ib_window": "★美股布局窗開啟（詳見下方今日行動）",
        "rule_health": "規則健康檢查失敗",
        "ingest_pipeline": "資料管線異常",
    }
    act = active_events()
    if not act:
        lines.append("• （無）")
    else:
        for ev in act:
            eid = str(ev.get("event_id"))
            label = event_labels.get(eid)
            if not label and eid.startswith("stop_"):
                label = f"破防守：{eid[5:]}"
            elif not label and "shock" in eid:
                label = f"急跌警戒：{eid}"
            since = (ev.get("since") or "")[:16]
            meta = ev.get("meta") or {}
            lines.append(f"• {label or eid} since {since} {meta}")

    # Actions / pending
    lines.append("")
    lines.append("【各部位狀態】")
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
        # 與 scan_position_levels 同步：核心ETF／債券的舊「總經句」已由各袖規則取代，
        # 直接顯示會與現行政策打架（例：債券寫「防禦續抱」但政策是 gradual_exit 逢彈出清）。
        STALE_PREFIXES = ("債券配置", "正2擇時", "0050底倉", "正2袖口")
        shown = [a for a in eod_actions if not str(a).startswith(STALE_PREFIXES)]
        if shown:
            for a in shown[:12]:
                lines.append(f"• {a}")
        else:
            lines.append("• （無；各袖規則見下方今日行動）")
    else:
        lines.append("• （無急迫待辦；詳見 levels／playbook）")

    # 【今日行動】把 playbook 意圖翻成「做什麼／多少／在哪做」，並分出要不要動手
    ACTION_LABELS = {
        "gate_blocked": "維持不動",
        "rebalance_trim": "再平衡減碼",
        "lower_deploy_budget": "調降可投入上限",
        "raise_deploy_budget": "調高可投入上限",
        "sl": "停損減碼",
        "sl_200": "破年線減碼",
        "tp": "停利減碼",
        "enter": "建倉買進",
        "add": "加碼買進",
        "exit_all": "全數出清",
    }
    SIDE_MARK = {"buy": "🟢 買", "sell": "🔴 賣", "hold": "⚪ 不動", "adjust": "🔧 改設定"}
    VENUE_LABELS = {
        "TW": "券商（台股）", "BOT": "台銀 App", "IB": "IB", "CEX": "幣安／幣托",
        "BANK": "設定調整（非交易）",
    }

    def _fmt_size(it: dict) -> str:
        qty, unit, twd = it.get("qty"), it.get("unit") or "", it.get("twd")
        if qty:
            s = f"{qty:,.0f} {unit}".strip()
            if twd:
                s += f"（約 {twd:,.0f} 元）"
            return s
        if twd:
            return f"約 {twd:,.0f} 元"
        return "—"

    all_intents = [x for x in (intents.get("intents") or []) if isinstance(x, dict)] \
        if isinstance(intents, dict) else []
    todo = [x for x in all_intents if x.get("side") in ("buy", "sell")]
    fyi = [x for x in all_intents if x.get("side") not in ("buy", "sell")]

    # 事件型待辦（非 playbook intent）：美股布局窗＝要去匯款，屬於必須動手的事
    event_todo = []
    for ev in act:
        if str(ev.get("event_id")) == "us_ib_window":
            w = (ev.get("meta") or {}).get("wire_twd") or 0
            amt = f"約 {w:,.0f} 元" if w else "金額見開窗推播"
            event_todo.append(
                f"• 🟢 匯款 IB｜{amt}（台銀臨櫃電匯）\n"
                f"    依據：美股趨勢閘門 ON（VOO 核心錨轉多）\n"
                f"    到帳後分 3 批×每月買進 VOO/VXUS/QQQ"
            )

    lines.append("")
    lines.append("【今日行動】")
    if not todo and not event_todo:
        lines.append("• ✅ 今日無需買賣。維持現狀即可。")
    for x in event_todo:
        lines.append(x)
    if todo:
        for it in todo[:6]:
            mark = SIDE_MARK.get(it.get("side"), "•")
            act = ACTION_LABELS.get(it.get("action"), it.get("action") or "")
            venue = VENUE_LABELS.get(it.get("venue"), it.get("venue") or "")
            lines.append(
                f"• {mark} {it.get('code')}｜{act} {_fmt_size(it)}｜在 {venue}"
            )
            if it.get("limit_ref"):
                lines.append(f"    依據：{it['limit_ref']}")
            if it.get("exec_after"):
                lines.append(f"    時機：{it['exec_after']}")
    for it in fyi[:4]:
        act = ACTION_LABELS.get(it.get("action"), it.get("action") or "")
        why = it.get("rationale") or ""
        lines.append(f"• ⚪ {it.get('code')}｜{act}（{why[:40]}）")

    if todo or event_todo:
        lines.append("")
        lines.append("【做完回報我】")
        lines.append("• 成交後告訴我：商品＋成交價＋股數／金額（例：「0050 買 160,000 元 @105.2」）")
        lines.append("• 我會更新持倉與現金，占比與下次建議才會準確；沒回報＝系統仍當你沒做")

    if slot == "close":
        lines.append("")
        lines.append("【收盤窗】破防守／年線事件以收盤確認為準；執行 ≥13:40 或隔日開盤。")
    if slot == "am":
        lines.append("")
        lines.append("【早報】開盤 09:00–09:30 凍結恐慌單；隔夜事件見上。")
    if slot == "pm":
        # 塵埃倉提醒（dust_rule）：核心幣／穩定幣之外的小幣，隨時可清、無需等訊號
        core_syms = {"BTC-USD", "ETH-USD", "USDT-USD"}
        dust = [
            c.get("name") or c.get("symbol")
            for c in (targets.get("multi_asset") or {}).get("crypto") or []
            if c.get("symbol") not in core_syms and float(c.get("qty") or 0) > 0
        ]
        if dust:
            lines.append("")
            lines.append(
                f"【塵埃倉】小幣未清：{('、'.join(str(d) for d in dust[:8]))}"
                "｜手續費划算時一次換 USDT（隨時可執行，不用等訊號）"
            )
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
