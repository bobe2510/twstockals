# -*- coding: utf-8 -*-
"""
隔日約 08:30：若前一日 EOD（~14:20）對 0050／正2 有建議操作，開盤前再推一次。
"""
from __future__ import annotations

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
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "preopen_reminder.md")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from eod_pending_ops import mark_reminded, pending_for_preopen  # noqa: E402
from notify import notify  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def main() -> None:
    now = taiwan_now()
    force = "--force" in sys.argv
    hhmm = now.strftime("%H%M")
    # 平日 08:20~08:50；或 --force
    if not force and not ("0820" <= hhmm <= "0850"):
        print(
            f"非開盤前提醒窗（台北 08:20~08:50）且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    doc = pending_for_preopen(now)
    items = list(doc.get("items") or [])
    as_of = doc.get("as_of") or "—"
    reason = doc.get("reason")

    lines = [
        "# 開盤前提醒｜0050／正2\n\n",
        f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n",
        f"來源日：**{as_of}** EOD  \n\n",
    ]

    if not items:
        lines.append(f"今日無待執行操作（{reason or 'empty'}）。\n")
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"無開盤前提醒：{reason or 'empty'}")
        sys.exit(0)

    lines.append("> 前一日收盤建議尚未執行則請於開盤後穩定期處理；**09:00~09:30 不殺**。  \n\n")
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. **{it.get('code')}**：{it.get('text')}  \n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    body = [
        f"開盤前提醒（來源 {as_of} EOD）",
        f"0050／正2 待執行 {len(items)} 項：",
        "",
    ]
    body += [f"{i}. [{it.get('code')}] {it.get('text')}" for i, it in enumerate(items[:20], 1)]
    body += ["", "執行：開盤後 10:00 起／或已預掛；09:00~09:30 不砍。"]

    notify(
        title=f"開盤前提醒 {now.strftime('%m/%d %H:%M')}｜0050／正2（{len(items)}）",
        body="\n".join(body),
        symbol="PREOPEN",
        rule_id="preopen_core_ops",
        urgency="eod_action",
        force=("--force-notify" in sys.argv),
    )
    mark_reminded(now)
    print(f"已推開盤前提醒 {len(items)} 項｜{REPORT_PATH}")


if __name__ == "__main__":
    main()
