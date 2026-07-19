# -*- coding: utf-8 -*-
"""
Evaluate whitelist market/system events and edge-notify via event_bus.

  python src_scripts/eval_market_events.py
  python src_scripts/eval_market_events.py --close-confirm
  python src_scripts/eval_market_events.py --quiet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from event_bus import (  # noqa: E402
    apply_desired,
    bump_streak,
    get_event,
    set_reclaim_streak,
)
from holding_rules import is_core_etf, is_tw_stock_code  # noqa: E402
from notify import load_alert_rules  # noqa: E402
from tw_time import taiwan_now  # noqa: E402

LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")
MANIFEST_PATH = os.path.join(
    WORKSPACE, "market_crawled_cache", "warehouse", "manifest.json"
)


def _load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _policies(rules: dict) -> dict:
    return dict(rules.get("event_policies") or {})


def _ma(closes: list[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _daily_closes(sym: str) -> list[tuple[str, float]]:
    import market_data as md

    rows = md.fetch_daily(sym)
    out = []
    for r in rows:
        try:
            out.append((r["date"], float(r["close"])))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def eval_macro_level(*, quiet: bool, force: bool) -> list[str]:
    levels = _load_json(LEVELS_PATH)
    level = levels.get("macro_level")
    if level is None:
        return []
    try:
        level = int(level)
    except (TypeError, ValueError):
        return []

    prev = get_event("macro_level")
    prev_level = (prev.get("meta") or {}).get("level")
    results = []

    # Track discrete level in meta; notify on transitions involving 2/3
    if prev_level is None:
        apply_desired(
            "macro_level",
            level >= 2,
            title_on=f"大盤進入 Level {level}",
            body_on=f"macro_level={level}。暫停追高／緊縮加碼；個股防守看收盤。",
            title_off="大盤離開警戒（回 Level 1）",
            body_off="macro_level=1。可依 playbook 恢復常態布局。",
            notify_clear=True,
            meta={"level": level},
            force_notify=force,
            quiet=True,  # first seed: no spam
        )
        results.append(f"macro_level seed={level}")
        return results

    if int(prev_level) == level:
        apply_desired(
            "macro_level",
            level >= 2,
            title_on="",
            body_on="",
            notify_clear=True,
            meta={"level": level},
            quiet=True,
        )
        results.append(f"macro_level hold={level}")
        return results

    # Level changed
    going_worse = level > int(prev_level)
    going_better = level < int(prev_level)
    if going_worse and level >= 2:
        apply_desired(
            "macro_level",
            True,
            title_on=f"大盤 Level {prev_level}→{level}",
            body_on=(
                f"濾網升級至 Level {level}。"
                "暫停積極開倉；緊縮停損／禁止弱勢加碼。"
            ),
            title_off="",
            body_off="",
            notify_clear=True,
            meta={"level": level, "from": int(prev_level)},
            force_notify=force,
            quiet=quiet,
        )
        # Force onset even if already active at L2 going to L3
        if int(prev_level) >= 2 and level >= 3:
            from event_bus import _push

            if not quiet:
                _push(
                    f"大盤 Level {prev_level}→{level}",
                    f"濾網由 Level {prev_level} 升至 {level}。全面防禦／降低持股成數。",
                    f"onset_macro_level_{level}",
                    force=force,
                )
        results.append(f"macro_level {prev_level}->{level} worse")
    elif going_better:
        still_alert = level >= 2
        apply_desired(
            "macro_level",
            still_alert,
            title_on=f"大盤仍在 Level {level}",
            body_on=f"由 Level {prev_level} 降至 {level}，仍屬警戒。",
            title_off=f"大盤離開警戒：Level {prev_level}→{level}",
            body_off=f"濾網回 Level {level}。可依 playbook 恢復布局。",
            notify_clear=True,
            meta={"level": level, "from": int(prev_level)},
            force_notify=force,
            quiet=quiet,
        )
        if still_alert and not quiet:
            from event_bus import _push

            _push(
                f"大盤降級 Level {prev_level}→{level}",
                f"仍屬警戒區（Level {level}），勿立刻追高。",
                f"onset_macro_level_down_{level}",
                force=force,
            )
        results.append(f"macro_level {prev_level}->{level} better")
    return results


def eval_twd_shock(rules: dict, *, quiet: bool, force: bool) -> list[str]:
    th = float((rules.get("thresholds") or {}).get("twd_alert_pct", 0.40))
    day = taiwan_now().strftime("%Y%m%d")
    eid = f"fx_twd_shock_{day}"
    import market_data as md

    # shock 類即時檢查：跳過 warehouse 快取直抓（避免用到過期日線）
    q = md.fetch_quote("USDTWD=X", use_cache=False)
    if not q:
        q = md.fetch_quote("USDTWD=X")  # 直抓失敗退回快取
    if not q:
        return ["twd: no quote"]
    chg = float(q.get("change_pct") or 0.0)
    hit = chg >= th
    # onset-only: notify_clear=False; daily event_id auto-expires next day
    apply_desired(
        eid,
        hit,
        title_on=f"台幣急貶 {chg:+.2f}%",
        body_on=(
            f"USD/TWD {q.get('price')}（單日 {chg:+.2f}% ≥ {th}%）。"
            "外資撤資風險升高；勿追外資主導股。"
        ),
        notify_clear=False,
        meta={"change_pct": chg, "price": q.get("price")},
        force_notify=force,
        quiet=quiet,
    )
    # Clear other days' active shock flags quietly
    from event_bus import load_state, save_state

    st = load_state()
    changed = False
    for k, ev in list((st.get("events") or {}).items()):
        if k.startswith("fx_twd_shock_") and k != eid and ev.get("active"):
            ev["active"] = False
            ev["last_change"] = taiwan_now().isoformat(timespec="seconds")
            changed = True
    if changed:
        save_state(st)
    return [f"twd hit={hit} chg={chg:.2f}"]


def _qty_held(code: str, targets: dict) -> float:
    for item in targets.get("portfolio") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("code")) == code:
            try:
                return float(item.get("shares") or item.get("qty") or 0)
            except (TypeError, ValueError):
                return 0.0
    ma = targets.get("multi_asset") or {}
    for bucket in ("crypto", "us_etf"):
        for item in ma.get(bucket) or []:
            if isinstance(item, str):
                if item == code:
                    return 1.0
                continue
            if not isinstance(item, dict):
                continue
            item_code = str(item.get("code") or item.get("symbol") or "")
            if item_code == code:
                try:
                    q = item.get("qty")
                    if q is None:
                        q = item.get("shares")
                    return float(q or 0)
                except (TypeError, ValueError):
                    return 0.0
    if code in ("GC=F", "XAU"):
        gp = ma.get("gold_passbook") or {}
        try:
            return float(gp.get("qty") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def eval_core_breaches(
    rules: dict, *, close_confirm: bool, quiet: bool, force: bool
) -> list[str]:
    """Stop / year-line breaches — only meaningful on close_confirm or --force-close."""
    if not close_confirm:
        return ["breach: skip (need close_confirm)"]

    pol = _policies(rules)
    stock_reclaim_days = int(pol.get("stock_reclaim_days", 2))
    etf_reclaim_days = int(pol.get("etf_reclaim_days", 1))
    levels = _load_json(LEVELS_PATH)
    targets = _load_json(TARGETS_PATH)
    live = {str(x.get("code")) for x in (targets.get("portfolio") or [])}
    results = []

    # Stock stop breaches from levels
    for row in levels.get("levels") or []:
        if row.get("status") != "portfolio":
            continue
        code = str(row.get("code") or "")
        if code not in live:
            continue
        name = row.get("name") or ""
        # 個股停損；ETF／正2 走年線事件，不走 5 日低
        if is_core_etf(code, name) or not is_tw_stock_code(code):
            continue
        stop = row.get("stop") or row.get("low_5d")
        px = row.get("close")
        if stop is None or px is None:
            continue

        eid = f"stop_{code}"
        breached = float(px) <= float(stop)
        need = stock_reclaim_days
        ev = get_event(eid)

        if breached:
            set_reclaim_streak(eid, 0)
            apply_desired(
                eid,
                True,
                title_on=f"收盤破防守：{code} {name}",
                body_on=(
                    f"收盤 {float(px):.2f} ≤ 停損 {float(stop):.2f}。"
                    f"執行窗 13:40 後／隔日開盤；開盤 09:00–09:30 凍結。"
                    f"解除需連續 {need} 日站回。"
                ),
                title_off=f"防守站回：{code} {name}",
                body_off=f"已連續 {need} 日收盤站回停損 {float(stop):.2f}。",
                notify_clear=True,
                meta={"px": px, "stop": stop, "need_reclaim": need},
                force_notify=force,
                quiet=quiet,
            )
            results.append(f"{code}: breach")
        else:
            # reclaim logic
            if not ev.get("active"):
                continue
            streak = int(ev.get("reclaim_streak") or 0) + 1
            set_reclaim_streak(eid, streak)
            if streak >= need:
                apply_desired(
                    eid,
                    False,
                    title_on="",
                    body_on="",
                    title_off=f"防守站回：{code} {name}",
                    body_off=(
                        f"連續 {streak} 日收盤站回停損 {float(stop):.2f}"
                        f"（現價 {float(px):.2f}）。"
                    ),
                    notify_clear=True,
                    meta={"px": px, "stop": stop, "reclaim_streak": streak},
                    force_notify=force,
                    quiet=quiet,
                )
                results.append(f"{code}: cleared streak={streak}")
            else:
                results.append(f"{code}: reclaim {streak}/{need}")

    # 00631L / core: TAIEX year-line (200MA) as breach proxy
    taiex = _daily_closes("TAIEX")
    if not taiex:
        # fallback: use levels macro + 00631L ma20 only as soft
        results.append("yearline: no TAIEX series")
    else:
        closes = [c for _, c in taiex]
        ma200 = _ma(closes, 200)
        last_px = closes[-1]
        eid = "yearline_taiex_00631L"
        if ma200 is None:
            results.append("yearline: insufficient TAIEX history")
        else:
            breached = last_px < ma200
            held_631 = _qty_held("00631L", targets) > 0
            if not held_631:
                results.append("yearline: 00631L not held")
            else:
                need = etf_reclaim_days
                ev = get_event(eid)
                if breached:
                    set_reclaim_streak(eid, 0)
                    apply_desired(
                        eid,
                        True,
                        title_on="正2／大盤破年線",
                        body_on=(
                            f"TAIEX {last_px:.0f} < 200MA {ma200:.0f}。"
                            "正2：袖口減／禁止加碼；勿盤中殺低。"
                        ),
                        title_off="大盤站回年線",
                        body_off=f"TAIEX 收盤站回 200MA（{ma200:.0f}）。",
                        notify_clear=True,
                        meta={"taiex": last_px, "ma200": ma200},
                        force_notify=force,
                        quiet=quiet,
                    )
                    results.append("yearline: breach")
                elif ev.get("active"):
                    streak = int(ev.get("reclaim_streak") or 0) + 1
                    set_reclaim_streak(eid, streak)
                    if streak >= need:
                        apply_desired(
                            eid,
                            False,
                            title_on="",
                            body_on="",
                            title_off="大盤站回年線",
                            body_off=f"TAIEX 已站回 200MA（{ma200:.0f}）。",
                            notify_clear=True,
                            meta={"taiex": last_px, "ma200": ma200},
                            force_notify=force,
                            quiet=quiet,
                        )
                        results.append(f"yearline: cleared {streak}")
                    else:
                        results.append(f"yearline: reclaim {streak}/{need}")

    return results


def _can_exec_buy(code: str, targets: dict) -> bool:
    """True if watch grade path would allow buy — soft: in approved buy_allowed."""
    au = targets.get("approved_universe") or {}
    for item in au.get("buy_allowed") or []:
        if str(item.get("id") or item.get("code")) == code:
            return True
    return False


def eval_asset_shocks(rules: dict, *, quiet: bool, force: bool) -> list[str]:
    pol = _policies(rules)
    th = rules.get("thresholds") or {}
    gold_th = float(th.get("gold_alert_pct", -5.0))
    crypto_th = float(th.get("crypto_alert_pct", -8.0))
    require_ma50 = bool(pol.get("crypto_shock_require_below_50ma", True))
    day = taiwan_now().strftime("%Y%m%d")
    targets = _load_json(TARGETS_PATH)
    import market_data as md

    results = []

    def _shock(sym: str, name: str, threshold: float, *, crypto: bool) -> None:
        eid = f"{'crypto' if crypto else 'gold'}_shock_{sym.replace('=','_')}_{day}"
        # shock 類即時檢查：跳過快取直抓；失敗退回快取
        q = md.fetch_quote(sym, use_cache=False) or md.fetch_quote(sym)
        if not q:
            results.append(f"{sym}: no quote")
            return
        chg = float(q.get("change_pct") or 0.0)
        held = _qty_held(sym, targets) > 0
        if sym == "GC=F":
            gp = (targets.get("multi_asset") or {}).get("gold_passbook") or {}
            try:
                held = held or float(gp.get("qty") or 0) > 0
            except (TypeError, ValueError):
                held = held or bool(gp.get("qty"))
        allowed = held or _can_exec_buy(sym, targets)

        below_ma = True
        if crypto and require_ma50:
            series = _daily_closes(sym)
            closes = [c for _, c in series]
            ma50 = _ma(closes, 50)
            px = float(q.get("price") or 0)
            below_ma = ma50 is not None and px < ma50
            if ma50 is None:
                results.append(f"{sym}: no ma50")
                below_ma = False

        hit = chg <= threshold and allowed and below_ma
        apply_desired(
            eid,
            hit,
            title_on=f"{name}急跌 {chg:+.2f}%",
            body_on=(
                f"{sym} {q.get('price')}（{chg:+.2f}% ≤ {threshold}%）"
                + ("；且＜50MA。" if crypto and require_ma50 else "。")
                + ("已持有／可執行門檻內。" if allowed else "")
                + "急跌中不追買。"
            ),
            notify_clear=False,
            meta={"change_pct": chg, "allowed": allowed, "below_ma50": below_ma},
            force_notify=force,
            quiet=quiet,
        )
        results.append(f"{sym}: hit={hit} chg={chg:.2f} allowed={allowed} ma50={below_ma}")

    _shock("GC=F", "黃金", gold_th, crypto=False)
    _shock("BTC-USD", "BTC", crypto_th, crypto=True)
    _shock("ETH-USD", "ETH", crypto_th, crypto=True)

    # Quiet-expire old day keys
    from event_bus import load_state, save_state

    st = load_state()
    changed = False
    for k, ev in list((st.get("events") or {}).items()):
        if ("_shock_" in k) and (day not in k) and ev.get("active"):
            if k.startswith("fx_"):
                continue
            ev["active"] = False
            changed = True
    if changed:
        save_state(st)
    return results


def eval_us_ib_window(*, quiet: bool, force: bool) -> list[str]:
    """
    美股布局窗（獨立於 pause_us_ib，專門回答「何時該入金 IB」）：
    以 VOO（核心錨）站上年線或12月動量轉正為開窗訊號；VXUS/QQQ 狀態併陳參考。
    這是入金時機提示，不是買點；買點仍走 scan_watch_grades（受 pause_us_ib 管控）。
    2026-07-18 trend_exit_backtest：VOO/QQQ 用 200MA-or-動量；VXUS 動量無效改純200MA。
    """
    results = []
    gates: dict[str, dict] = {}
    for sym, kind in (("VOO", "mom_or_ma"), ("QQQ", "mom_or_ma"), ("VXUS", "ma_only")):
        series = _daily_closes(sym)
        if len(series) < 210:
            results.append(f"us_ib_window {sym}: insufficient history")
            continue
        closes = [c for _, c in series]
        px = closes[-1]
        ma200 = _ma(closes, 200)
        if ma200 is None:
            continue
        above200 = px > ma200
        mom12 = len(closes) >= 253 and px > closes[-253]
        gate_on = above200 if kind == "ma_only" else (above200 or mom12)
        bias200 = (px - ma200) / ma200 * 100
        gates[sym] = {
            "gate_on": gate_on,
            "above200": above200,
            "mom12": mom12,
            "bias200": round(bias200, 1),
        }

    if "VOO" not in gates:
        results.append("us_ib_window: VOO data unavailable")
        return results

    voo_on = gates["VOO"]["gate_on"]
    on_syms = [s for s, g in gates.items() if g["gate_on"]]
    off_syms = [s for s, g in gates.items() if not g["gate_on"]]
    detail = "；".join(
        f"{s} {'ON' if g['gate_on'] else 'OFF'}(vs200MA{g['bias200']:+.1f}%)"
        for s, g in gates.items()
    )

    targets = _load_json(TARGETS_PATH)
    pause_us = bool((targets.get("multi_asset") or {}).get("pause_us_ib"))
    pause_note = (
        "\n（目前 pause_us_ib=true：買點與匯款催促仍暫停；這是入金啟動提示，"
        "資金到位、確認可執行後再把設定改 false 恢復正式買點推播。）"
        if pause_us
        else ""
    )

    apply_desired(
        "us_ib_window",
        voo_on,
        title_on="美股布局窗開啟｜建議開始入金 IB",
        body_on=(
            f"VOO（核心錨）轉多：{detail}。\n"
            "IB 電匯通常需 1-3 個工作天到帳，建議現在啟動匯款流程；"
            "資金到位後再依評等分批進場（VOO:VXUS≈7:3，QQQ 成長袖較小）。"
            + pause_note
        ),
        title_off="美股布局窗關閉",
        body_off=f"VOO 轉空：{detail}。窗口關閉，暫緩入金。",
        notify_clear=True,
        meta={"on": on_syms, "off": off_syms},  # 精簡：明細只在轉態推播內文，避免每日事件列雜訊
        force_notify=force,
        quiet=quiet,
    )
    results.append(f"us_ib_window: voo_on={voo_on} on={on_syms} off={off_syms}")
    return results


def eval_ingest(*, quiet: bool, force: bool) -> list[str]:
    rules = load_alert_rules()
    pol = _policies(rules)
    need_fail = int(pol.get("ingest_fail_streak", 2))
    need_ok = int(pol.get("ingest_ok_streak", 2))
    manifest = _load_json(MANIFEST_PATH)
    jobs = manifest.get("jobs") or {}
    results = []
    eid = "ingest_pipeline"
    # Aggregate: any critical job fail counts as fail tick when health run
    critical = ["tw_eod", "us_eod", "fx_gold", "crypto"]
    if not jobs:
        entry = bump_streak(eid, success=False)
        results.append(f"ingest: no manifest fail_streak={entry.get('fail_streak')}")
    else:
        any_fail = any(not (jobs.get(j) or {}).get("ok", False) for j in critical if j in jobs)
        # If no critical jobs logged today-ish, don't hammer
        if not any(j in jobs for j in critical):
            results.append("ingest: no critical jobs")
            return results
        entry = bump_streak(eid, success=not any_fail)
        results.append(
            f"ingest: any_fail={any_fail} fail={entry.get('fail_streak')} ok={entry.get('ok_streak')}"
        )

    entry = get_event(eid)
    fail_n = int(entry.get("fail_streak") or 0)
    ok_n = int(entry.get("ok_streak") or 0)
    should_active = fail_n >= need_fail
    if ok_n >= need_ok:
        should_active = False

    apply_desired(
        eid,
        should_active,
        title_on=f"資料倉連續失敗 ×{fail_n}",
        body_on=(
            f"ingest／health 連續失敗 ≥ {need_fail}。"
            "掃描可能用過期倉或 API fallback；請檢查 Droplet／Actions。"
        ),
        title_off="資料倉管線恢復",
        body_off=f"連續成功 ≥ {need_ok}，health 恢復。",
        notify_clear=True,
        meta={"fail_streak": fail_n, "ok_streak": ok_n},
        force_notify=force,
        quiet=quiet,
    )
    return results


def run_all(
    *,
    close_confirm: bool = False,
    quiet: bool = False,
    force: bool = False,
    skip_ingest: bool = False,
) -> dict[str, list[str]]:
    rules = load_alert_rules()
    out: dict[str, list[str]] = {}
    out["macro"] = eval_macro_level(quiet=quiet, force=force)
    out["twd"] = eval_twd_shock(rules, quiet=quiet, force=force)
    out["breach"] = eval_core_breaches(
        rules, close_confirm=close_confirm, quiet=quiet, force=force
    )
    out["shock"] = eval_asset_shocks(rules, quiet=quiet, force=force)
    out["us_ib_window"] = eval_us_ib_window(quiet=quiet, force=force)
    if not skip_ingest:
        out["ingest"] = eval_ingest(quiet=quiet, force=force)
    for k, v in out.items():
        print(f"[eval:{k}] {v}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--close-confirm", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="Update state only, no Telegram")
    ap.add_argument("--force-notify", action="store_true")
    ap.add_argument("--skip-ingest", action="store_true")
    args = ap.parse_args()
    run_all(
        close_confirm=args.close_confirm,
        quiet=args.quiet,
        force=args.force_notify,
        skip_ingest=args.skip_ingest,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
