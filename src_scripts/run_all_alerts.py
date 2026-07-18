# -*- coding: utf-8 -*-
"""
Unified alert runner — event_digest model:

  Fixed push: digest_am (07:30) / digest_close (13:45) / digest_pm (19:00)
  Edge push: EVENT via eval_market_events (Level / TWD / breach / shock / ingest)
  Background scans: update reports／event_state; routine notify suppressed

Legacy modes kept for manual／過渡；排程請改用 digest_* ＋ close_confirm／scan_bg。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "src_scripts")
MARKER_PATH = os.path.join(ROOT, "reports", "latest", "close_confirm_ran.json")
sys.path.insert(0, SCRIPTS)
from notify import clear_notify_batch, flush_notify_batch  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def run_script(name: str, extra_args: list[str], *, batch: bool = True) -> int:
    path = os.path.join(SCRIPTS, name)
    cmd = [sys.executable, path, *extra_args]
    print(f"\n=== RUN {name} {' '.join(extra_args)} ===")
    env = os.environ.copy()
    env["TWSTOCKALS_WORKSPACE"] = ROOT
    env["PYTHONPATH"] = SCRIPTS + os.pathsep + env.get("PYTHONPATH", "")
    if batch:
        env["TWSTOCKALS_BATCH_NOTIFY"] = "1"
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    print(f"=== EXIT {name} code={proc.returncode} ===")
    return proc.returncode


def _mark_close_confirm() -> None:
    os.makedirs(os.path.dirname(MARKER_PATH), exist_ok=True)
    now = taiwan_now()
    with open(MARKER_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"date": now.strftime("%Y-%m-%d"), "at": now.isoformat(timespec="seconds")},
            f,
            ensure_ascii=False,
            indent=2,
        )


def _close_confirm_already_ran_today() -> bool:
    if not os.path.exists(MARKER_PATH):
        return False
    try:
        with open(MARKER_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return str(doc.get("date") or "") == taiwan_now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _pre_ingest(mode: str) -> None:
    try:
        from ingest_for_mode import run_ingest_for_mode

        print(f"\n=== PRE-INGEST for mode={mode} ===")
        ok = run_ingest_for_mode(mode, notify_on_fail=True, health_notify=True)
        print(f"=== PRE-INGEST done ok={ok} ===")
    except Exception as e:
        print(f"[run_all_alerts] pre-ingest error: {e}")


def _eval_events(*, close_confirm: bool, quiet: bool, force_notify: bool) -> None:
    try:
        from eval_market_events import run_all

        print(f"\n=== EVAL EVENTS close_confirm={close_confirm} quiet={quiet} ===")
        run_all(
            close_confirm=close_confirm,
            quiet=quiet,
            force=force_notify,
        )
    except Exception as e:
        print(f"[run_all_alerts] eval_market_events error: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[
            "digest_am",
            "digest_close",
            "digest_pm",
            "scan_bg",
            "close_confirm",
            "all",
            "intraday",
            "eod",
            "multi",
            "multi_day",
        ],
        default="digest_pm",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--backup", action="store_true")
    # 預設關彈窗（雲端／droplet 安全）；本機要彈窗用 --popup 開啟
    parser.add_argument("--popup", action="store_true", help="本機桌面彈窗（僅 Windows）")
    parser.add_argument("--no-popup", action="store_true", help="（相容舊參數；預設即不彈窗）")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    print(
        f"run_all_alerts mode={args.mode} at "
        f"{taiwan_now().isoformat(timespec='seconds')} (Asia/Taipei)"
    )
    print(f"workspace={ROOT}")

    if args.mode == "close_confirm" and args.backup and _close_confirm_already_ran_today():
        print("close_confirm 備援：今日已跑過，略過（降噪）")
        sys.exit(0)

    clear_notify_batch()
    common = []
    if args.force:
        common.append("--force")
    if args.force_notify:
        common.append("--force-notify")

    codes = []

    # ----- Fixed digests -----
    if args.mode == "digest_am":
        if not args.no_ingest:
            _pre_ingest("multi")
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)
        codes.append(
            run_script(
                "build_daily_digest.py",
                ["--slot", "am"]
                + (["--force-notify"] if args.force_notify else []),
                batch=False,
            )
        )
        sys.exit(1 if any(c not in (0, None) for c in codes) else 0)

    if args.mode == "digest_close":
        if not args.no_ingest:
            _pre_ingest("close_confirm")
        codes.append(run_script("sync_runtime_state.py", [], batch=False))
        codes.append(run_script("refresh_levels_live.py", [], batch=False))
        sw = list(common)
        if not args.popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        sw.append("--close-confirm")
        codes.append(run_script("scan_black_swan.py", sw))
        xargs = list(common)
        if "--force" not in xargs:
            xargs.append("--force")
        codes.append(run_script("scan_exit_watch.py", xargs))
        eargs = list(common)
        if "--force" not in eargs:
            eargs.append("--force")
        eargs.append("--save-pending")
        codes.append(run_script("scan_position_levels.py", eargs))
        _mark_close_confirm()
        _eval_events(close_confirm=True, quiet=False, force_notify=args.force_notify)
        codes.append(
            run_script(
                "build_daily_digest.py",
                ["--slot", "close"]
                + (["--force-notify"] if args.force_notify else []),
                batch=False,
            )
        )
        # flush any batched leftovers (usually empty in event_digest)
        flush_notify_batch(
            f"收盤執行報 {taiwan_now().strftime('%m/%d %H:%M')}（台北）",
            force=args.force_notify,
            symbol="DIGEST",
            rule_id="digest_close_batch",
        )
        sys.exit(1 if any(c not in (0, None) for c in codes) else 0)

    if args.mode == "digest_pm":
        if not args.no_ingest:
            _pre_ingest("multi")
        margs = list(common)
        if "--force" not in margs:
            margs.append("--force")
        codes.append(run_script("scan_multi_asset.py", margs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        codes.append(run_script("scan_watch_grades.py", wargs))
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)
        codes.append(
            run_script(
                "build_daily_digest.py",
                ["--slot", "pm"]
                + (["--force-notify"] if args.force_notify else []),
                batch=False,
            )
        )
        flush_notify_batch(
            f"晚報現況 {taiwan_now().strftime('%m/%d %H:%M')}（台北）",
            force=args.force_notify,
            symbol="DIGEST",
            rule_id="digest_pm_batch",
        )
        sys.exit(1 if any(c not in (0, None) for c in codes) else 0)

    # ----- Background scan (no digest); events may still edge-push -----
    if args.mode == "scan_bg":
        if not args.no_ingest:
            _pre_ingest("intraday")
        sw = list(common)
        if not args.popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        codes.append(run_script("scan_black_swan.py", sw))
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)
        flush_notify_batch("背景掃描", force=False, symbol="EVENT", rule_id="scan_bg")
        sys.exit(1 if any(c not in (0, None) for c in codes) else 0)

    # ----- Legacy paths (still event_digest-suppressed for routine notify) -----
    if not args.no_ingest:
        _pre_ingest(args.mode)

    if args.mode in ("all", "intraday"):
        sw = list(common)
        if not args.popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        codes.append(run_script("scan_black_swan.py", sw))
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)

    if args.mode in ("all", "close_confirm"):
        codes.append(run_script("sync_runtime_state.py", []))
        codes.append(run_script("refresh_levels_live.py", []))
        sw = list(common)
        if not args.popup:
            sw.append("--no-popup")
        if "--force" not in sw:
            sw.append("--force")
        sw.append("--close-confirm")
        codes.append(run_script("scan_black_swan.py", sw))
        xargs = list(common)
        if "--force" not in xargs:
            xargs.append("--force")
        codes.append(run_script("scan_exit_watch.py", xargs))
        _mark_close_confirm()
        _eval_events(close_confirm=True, quiet=False, force_notify=args.force_notify)

    if args.mode in ("all", "eod"):
        codes.append(run_script("sync_runtime_state.py", []))
        codes.append(run_script("refresh_levels_live.py", []))
        eargs = list(common)
        if "--force" not in eargs:
            eargs.append("--force")
        eargs.append("--save-pending")
        codes.append(run_script("scan_position_levels.py", eargs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        wargs.append("--save-pending")
        codes.append(run_script("scan_watch_grades.py", wargs))
        _eval_events(close_confirm=True, quiet=False, force_notify=args.force_notify)

    if args.mode == "multi_day":
        margs = list(common)
        if "--force" not in margs:
            margs.append("--force")
        margs.append("--day")
        margs.append("--skip-btc")
        codes.append(run_script("scan_multi_asset.py", margs))
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)

    if args.mode in ("all", "multi"):
        margs = list(common)
        if "--force" not in margs:
            margs.append("--force")
        codes.append(run_script("scan_multi_asset.py", margs))
        wargs = list(common)
        if "--force" not in wargs:
            wargs.append("--force")
        codes.append(run_script("scan_watch_grades.py", wargs))
        _eval_events(close_confirm=False, quiet=False, force_notify=args.force_notify)

    bad = [c for c in codes if c not in (0, None)]
    tw = taiwan_now()
    flush_notify_batch(
        f"警報摘要 {tw.strftime('%m/%d %H:%M')}（台北）",
        force=args.force_notify,
        symbol="DIGEST",
        rule_id=f"legacy_{args.mode}",
    )
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
