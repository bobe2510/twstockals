# -*- coding: utf-8 -*-
"""
對齊執行時狀態：以 config/my_targets.json 為唯一真相，
清除／覆寫 reports/latest 中會誤導決策的過期持股與策略文案。

用法：
  python src_scripts/sync_runtime_state.py
  python src_scripts/sync_runtime_state.py --clear-pending
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
TARGETS = os.path.join(WORKSPACE, "config", "my_targets.json")
LATEST = os.path.join(WORKSPACE, "reports", "latest")
HOLDINGS = os.path.join(LATEST, "holdings.json")
LEVELS = os.path.join(LATEST, "levels.json")
STATE_MD = os.path.join(LATEST, "CURRENT_STATE.md")
PORTFOLIO_MD = os.path.join(LATEST, "portfolio_and_watchlist.md")
WATCH_MD = os.path.join(LATEST, "watch_grades.md")
MULTI_MD = os.path.join(LATEST, "multi_asset_levels.md")
EOD_MD = os.path.join(LATEST, "eod_action_list.md")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from eod_pending_ops import clear_pending, load_pending  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


CLEARED_HINT = re.compile(
    r"(00632R|00882|3483|5469|6191|逢彈分批出清|錯誤策略出清|反1)"
)


def _load_targets() -> dict:
    with open(TARGETS, "r", encoding="utf-8") as f:
        return json.load(f)


def sync_holdings(targets: dict, now_iso: str) -> None:
    multi = targets.get("multi_asset") or {}
    rows = []
    for h in targets.get("portfolio") or []:
        rows.append(
            {
                "code": h.get("code"),
                "name": h.get("name"),
                "shares": h.get("shares"),
                "cost": h.get("cost"),
                "policy": h.get("policy"),
                "note": h.get("note"),
            }
        )
    gold = multi.get("gold_passbook") or {}
    fx = multi.get("forex_usd") or {}
    doc = {
        "as_of": now_iso,
        "portfolio": rows,
        "cleared_positions": targets.get("cleared_positions") or [],
        "force_exit_codes": targets.get("force_exit_codes") or [],
        "multi_asset_summary": {
            "gold_g": gold.get("qty"),
            "usd": fx.get("qty"),
            "deployable_cash_twd": multi.get("deployable_cash_twd"),
            "pause_us_ib": bool(multi.get("pause_us_ib")),
        },
    }
    os.makedirs(LATEST, exist_ok=True)
    with open(HOLDINGS, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"holdings.json ← {len(rows)} 檔持倉")


def scrub_levels(targets: dict, now_iso: str) -> None:
    if not os.path.exists(LEVELS):
        return
    with open(LEVELS, "r", encoding="utf-8") as f:
        doc = json.load(f)
    live = {str(h.get("code")) for h in (targets.get("portfolio") or []) if h.get("code")}
    cleared = {
        str(x.get("code")) for x in (targets.get("cleared_positions") or []) if x.get("code")
    }
    force = {str(c) for c in (targets.get("force_exit_codes") or []) if c}

    kept = []
    for row in doc.get("levels") or []:
        code = str(row.get("code") or "")
        if not code:
            continue
        # 已出清不得再當 portfolio
        if code in cleared and row.get("status") == "portfolio":
            print(f"levels: 移除已出清 portfolio 列 {code}")
            continue
        if row.get("status") == "portfolio" and code not in live:
            print(f"levels: 移除非現持股 portfolio 列 {code}")
            continue
        if code in live:
            row["status"] = "portfolio"
            row["force_exit"] = code in force
        kept.append(row)

    # 覆寫易誤導的 eod_actions
    new_acts = []
    for a in doc.get("eod_actions") or []:
        if any(c in a for c in cleared) or CLEARED_HINT.search(a):
            print(f"levels: 丟棄過期 eod_action：{a[:60]}…")
            continue
        if "00631L" in a and ("破年線" in a or "續抱或減碼" in a):
            a = "正2擇時：00631L → 年線上＋Level≥3：續抱、禁止加碼（非破年線減碼）"
        new_acts.append(a)
    # 確保有正2現況句
    if live & {"00631L"} and not any("00631L" in a for a in new_acts):
        new_acts.insert(
            0,
            "正2擇時：00631L → 年線上＋Level≥3：續抱、禁止加碼（非破年線減碼）",
        )

    doc["levels"] = kept
    doc["eod_actions"] = new_acts
    doc["force_exit_codes"] = sorted(force)
    doc["generated_at"] = now_iso
    doc["synced_at"] = now_iso
    with open(LEVELS, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"levels.json 已 scrub｜portfolio 列對齊現持股")


def write_current_state(targets: dict, now) -> None:
    multi = targets.get("multi_asset") or {}
    port = targets.get("portfolio") or []
    cleared = targets.get("cleared_positions") or []
    pause = bool(multi.get("pause_us_ib"))
    cash = int(multi.get("deployable_cash_twd") or 0)
    lines = [
        "# 現行狀態（唯一對齊基準）\n\n",
        f"更新：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n",
        f"來源：`config/my_targets.json`  \n\n",
        "> **決策只看本檔 + 當日 EOD／推播。**  \n",
        "> `portfolio_and_watchlist.md` 若基準日過舊或仍列已出清標的，視為過期，勿執行。  \n\n",
        "## 現持股\n\n",
        "| 代號 | 名稱 | 股數 | 成本 | 政策 |\n",
        "|------|------|------|------|------|\n",
    ]
    for h in port:
        lines.append(
            f"| `{h.get('code')}` | {h.get('name')} | {h.get('shares')} | "
            f"{h.get('cost')} | {h.get('policy') or '—'} |\n"
        )
    lines.append("\n## 已出清（勿再當持倉／勿再推「出清窗」）\n\n")
    for x in cleared:
        lines.append(
            f"* `{x.get('code')}` {x.get('name')}｜{x.get('cleared_on')}｜{x.get('note') or ''}\n"
        )
    lines.extend(
        [
            "\n## 策略摘要（現行）\n\n",
            f"* 可再投入現金：**{cash:,}** 元（既有持倉外）  \n",
            f"* pause_us_ib：**{pause}**（true＝美股只觀測不催匯款）  \n",
            "* 正2 `00631L`：年線上＋Level≥3 → **續抱、禁止加碼**；**破年線**才減碼／空倉  \n",
            "* 美債 `00687B`：`gradual_exit` 逢彈分批，不加碼  \n",
            "* 個股殘倉（2301／3484）：收盤確認停損／移動停利；不新開個股  \n",
            "* 買點用詞：=門檻**允許買進**／較優**建議買進**／S**強烈建議買進**  \n",
            "* 加密：偏重 → 不加碼；破 50MA 可減參考  \n\n",
            "## 過期報告處理\n\n",
            "* 已對 `levels.json`／`holdings.json`／`eod_pending_ops` 做 scrub  \n",
            "* `portfolio_and_watchlist.md` 若仍含反1／00882 出清窗 → 頂部會被蓋上過期警告  \n",
        ]
    )
    with open(STATE_MD, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"寫入 {STATE_MD}")


def stamp_stale_portfolio_report(targets: dict, now) -> None:
    """在過期持股報告頂部強制蓋章，避免執行已出清標的。"""
    if not os.path.exists(PORTFOLIO_MD):
        return
    text = open(PORTFOLIO_MD, "r", encoding="utf-8").read()
    live = {str(h.get("code")) for h in (targets.get("portfolio") or [])}
    cleared = {
        str(x.get("code")) for x in (targets.get("cleared_positions") or []) if x.get("code")
    }
    looks_stale = bool(CLEARED_HINT.search(text)) or any(
        f"`{c}`" in text and c in cleared for c in cleared
    )
    # 也檢查是否把已出清當持股表
    for c in ("00632R", "00882", "3483", "5469", "6191"):
        if c in cleared and re.search(rf"\|\s*`{c}`\s*\|.*持有", text):
            looks_stale = True
    banner = (
        f"> [!CAUTION]\n"
        f"> **⛔ 本報告可能過期（同步於 {now.strftime('%Y-%m-%d %H:%M')}）**  \n"
        f"> 現行持股只認：`{'`、`'.join(sorted(live))}`。  \n"
        f"> **已出清勿再操作**：`{'`、`'.join(sorted(cleared))}`。  \n"
        f"> 請改看 [`CURRENT_STATE.md`](CURRENT_STATE.md) 與當日 `eod_action_list.md`。  \n"
        f"> 完整日報請重跑 `market_screener`／`analyze_portfolio_deep` 後才可信。  \n\n"
    )
    # 去掉舊 stamp 再蓋
    text = re.sub(
        r"> \[!CAUTION\]\n> \*\*⛔ 本報告可能過期[\s\S]*?> 完整日報請重跑[\s\S]*?\n\n",
        "",
        text,
        count=1,
    )
    if looks_stale or True:
        # 一律蓋章：此檔基準日常落後
        text = banner + text
    with open(PORTFOLIO_MD, "w", encoding="utf-8") as f:
        f.write(text)
    print("portfolio_and_watchlist.md 已蓋過期警告")


def patch_wording_headers() -> None:
    """把殘留舊用詞抬頭改成三階語氣說明。"""
    new_watch = (
        "> 推播語氣（回測級距）：**=門檻→允許買進**｜**較優→建議買進**｜**S→強烈建議買進**；"
        "低於門檻不推。D/C=觀望。  \n"
    )
    new_multi = (
        "> 評等維持真實 D/C/B/A/S；語氣依回測級距："
        "**允許買進**／**建議買進**／**強烈建議買進（S）**；"
        "ladder 升級=**請加碼**。  \n\n"
    )
    if os.path.exists(WATCH_MD):
        t = open(WATCH_MD, "r", encoding="utf-8").read()
        t2 = re.sub(
            r"> \*\*B=允許小買[\s\S]*?D/C=觀望。\s*\n",
            new_watch,
            t,
            count=1,
        )
        t2 = re.sub(
            r"> 首次=\*\*請買進[\s\S]*?不加碼。\s*\n",
            new_watch,
            t2,
            count=1,
        )
        if t2 != t:
            open(WATCH_MD, "w", encoding="utf-8").write(t2)
            print("watch_grades.md 抬頭用詞已對齊")
    if os.path.exists(MULTI_MD):
        t = open(MULTI_MD, "r", encoding="utf-8").read()
        t2 = re.sub(
            r"> 評等維持真實 D/C/B/A/S；[\s\S]*?不加碼。\s*\n\n",
            new_multi,
            t,
            count=1,
        )
        t2 = re.sub(
            r"> 評等維持真實 D/C/B/A/S；等於門檻=\*\*請買進\*\*；高於門檻=\*\*較推薦\*\*。\s*\n",
            new_multi.rstrip() + "\n",
            t2,
            count=1,
        )
        if t2 != t:
            open(MULTI_MD, "w", encoding="utf-8").write(t2)
            print("multi_asset_levels.md 抬頭用詞已對齊")


def stamp_eod_list(now) -> None:
    if not os.path.exists(EOD_MD):
        return
    t = open(EOD_MD, "r", encoding="utf-8").read()
    # 去掉已出清代號相關列
    lines = t.splitlines(keepends=True)
    out = []
    for ln in lines:
        if CLEARED_HINT.search(ln) and any(
            c in ln for c in ("00632R", "00882", "3483", "5469", "6191")
        ):
            continue
        out.append(ln)
    body = "".join(out)
    note = (
        f"\n> 同步戳記 {now.strftime('%Y-%m-%d %H:%M')}："
        f"已剔除已出清標的列；正2以「續抱、禁止加碼」為準（年線未破不減碼）。  \n"
    )
    if "同步戳記" not in body:
        # 插在第一個空行後
        parts = body.split("\n\n", 1)
        if len(parts) == 2:
            body = parts[0] + "\n\n" + note + "\n" + parts[1]
        else:
            body = note + body
    open(EOD_MD, "w", encoding="utf-8").write(body)
    print("eod_action_list.md 已剔除已出清列並戳記")


def main() -> None:
    now = taiwan_now()
    now_iso = now.isoformat(timespec="seconds")
    targets = _load_targets()
    sync_holdings(targets, now_iso)
    scrub_levels(targets, now_iso)
    write_current_state(targets, now)
    stamp_stale_portfolio_report(targets, now)
    patch_wording_headers()
    stamp_eod_list(now)

    clear = "--clear-pending" in sys.argv
    pend = load_pending()
    items = pend.get("items") or []
    if clear or any(CLEARED_HINT.search(str(it.get("text") or "")) for it in items):
        clear_pending(reason="sync_runtime_state_stale_or_flag")
        print("eod_pending 已清空（過期／含已出清語意）")
    elif not items and not pend.get("cleared_reason"):
        clear_pending(reason="sync_ensure_empty")
        print("eod_pending 確認為空")
    else:
        print(f"eod_pending 維持：items={len(items)} reason={pend.get('cleared_reason')}")

    print("sync_runtime_state 完成")


if __name__ == "__main__":
    main()
