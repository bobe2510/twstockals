# -*- coding: utf-8 -*-
"""
約 12:00（台北）：BTC／ETH 午間狀態推播。
既有偏重 → 不加碼；急跌仍警戒；破 50MA 標註可減參考。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "crypto_noon.md")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from market_data import fetch_daily  # noqa: E402
from notify import load_alert_rules, notify  # noqa: E402
from grade_buy_policy import product_policy  # noqa: E402
from tw_time import taiwan_now  # noqa: E402


def load_targets() -> dict:
    if not os.path.exists(TARGETS_PATH):
        return {}
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_crypto(sym: str) -> Optional[dict]:
    rows = fetch_daily(sym)
    if len(rows) < 5:
        return None
    closes = [float(r["close"]) for r in rows]
    px = closes[-1]
    prev = closes[-2]
    change_pct = ((px - prev) / prev) * 100 if prev else 0.0
    return {
        "symbol": sym,
        "price": px,
        "change_pct": change_pct,
        "ma50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
        "ma200": sum(closes[-200:]) / 200 if len(closes) >= 200 else None,
        "source": rows[-1].get("source"),
    }


def _bias(px: float, ma: Optional[float]) -> Optional[float]:
    if ma is None or ma == 0:
        return None
    return (px - ma) / ma * 100


def format_asset(name: str, code: str, q: Optional[dict], *, pause_add: bool, shock_pct: float) -> tuple[list[str], list[str]]:
    """Return (report_lines, push_bullets)."""
    lines: list[str] = []
    bullets: list[str] = []
    pol = product_policy(code)
    min_g = pol.get("buy_min_grade") or "A"
    sell_note = pol.get("sell_note") or "破 50MA 可減"

    lines.append(f"## {name} (`{code}`)\n\n")
    if not q:
        lines.append("* 報價失敗  \n\n")
        bullets.append(f"{name}：報價失敗")
        return lines, bullets

    b50 = _bias(q["price"], q.get("ma50"))
    b200 = _bias(q["price"], q.get("ma200"))
    lines.append(f"* 價格：**{q['price']:,.2f}** USD（{q['change_pct']:+.2f}%）  \n")
    if q.get("ma50") is not None and b50 is not None:
        lines.append(f"* 50MA：{q['ma50']:,.2f}（乖離 {b50:+.2f}%）  \n")
    if q.get("ma200") is not None and b200 is not None:
        lines.append(f"* 200MA：{q['ma200']:,.2f}（乖離 {b200:+.2f}%）  \n")

    status = []
    if pause_add or pol.get("pause_add_default"):
        status.append("加碼暫停（偏重／政策）")
        lines.append(f"* **加碼：暫停**｜門檻≥{min_g} 但建議金額 **0**  \n")
    else:
        status.append(f"門檻≥{min_g} 才考慮加")
        lines.append(f"* 推播門檻：≥**{min_g}**（目前可評估加碼）  \n")

    if q.get("ma50") is not None and q["price"] < q["ma50"]:
        status.append("低於50MA｜可減參考")
        lines.append(f"* **出場參考**：{sell_note}  \n")
    else:
        lines.append("* 相對季線：未破／資料不足  \n")

    if q["change_pct"] <= shock_pct:
        status.append(f"急跌{q['change_pct']:+.1f}%")
        lines.append(f"* **緊急**：單日 {q['change_pct']:+.2f}% ≤ 閾值 {shock_pct}%  \n")

    lines.append("\n")
    bit = f"{name} {q['price']:,.0f}（{q['change_pct']:+.1f}%）"
    if b50 is not None:
        bit += f"｜vs50MA {b50:+.1f}%"
    if status:
        bit += "｜" + "；".join(status)
    bullets.append(bit)
    return lines, bullets


def main() -> None:
    now = taiwan_now()
    force = "--force" in sys.argv
    hhmm = now.strftime("%H%M")
    # 11:45~12:30 或 --force
    if not force and not ("1145" <= hhmm <= "1230"):
        print(
            f"非加密午間窗（台北 11:45~12:30）且無 --force，退出。"
            f" now={now.isoformat()}"
        )
        sys.exit(0)

    rules = load_alert_rules()
    th = rules.get("thresholds") or {}
    shock = float(th.get("crypto_alert_pct", -8.0))

    targets = load_targets()
    multi = targets.get("multi_asset") or {}
    pause_add = True
    crypto_approx = None
    for c in multi.get("crypto") or []:
        if c.get("approx_twd_total_crypto"):
            crypto_approx = c["approx_twd_total_crypto"]
            break
    # 偏重則暫停；未標市值也預設暫停（與現行一致）
    if crypto_approx is not None and crypto_approx < 250_000:
        pause_add = False

    btc = fetch_crypto("BTC-USD")
    eth = fetch_crypto("ETH-USD")

    lines = [
        "# BTC／ETH 午間狀態\n\n",
        f"時間：{now.strftime('%Y-%m-%d %H:%M:%S')}（台北）  \n",
        "> 24h 市場；既有偏重則**不加碼**，急跌只警戒不追。  \n\n",
    ]
    bullets: list[str] = []
    for name, code, q in (
        ("Bitcoin", "BTC-USD", btc),
        ("Ethereum", "ETH-USD", eth),
    ):
        rl, bl = format_asset(
            name, code, q, pause_add=pause_add, shock_pct=shock
        )
        lines.extend(rl)
        bullets.extend(bl)

    if crypto_approx is not None:
        lines.append(f"* 加密粗估市值約 **{crypto_approx:,.0f}** TWD  \n")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    body = [
        f"午間加密（{now.strftime('%m/%d %H:%M')} 台北）",
        f"加碼：{'暫停' if pause_add else '可依門檻評估'}",
        "",
    ]
    body += [f"• {b}" for b in bullets]
    body.append("")
    body.append("規則：偏重不加；急跌不追；破50MA 才考慮減。")

    # 急跌用較高優先；否則一般 digest
    urg = "emergency" if any(
        q and q["change_pct"] <= shock for q in (btc, eth)
    ) else "eod_action"
    notify(
        title=f"BTC／ETH 午間 {now.strftime('%m/%d %H:%M')}",
        body="\n".join(body),
        symbol="CRYPTO",
        rule_id="crypto_noon",
        urgency=urg,
        force=("--force-notify" in sys.argv),
    )
    print(f"加密午間已推｜{REPORT_PATH}")


if __name__ == "__main__":
    main()
