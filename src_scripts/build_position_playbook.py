# -*- coding: utf-8 -*-
"""
產出 position_playbook.md + action_intents.json。
依 config/position_playbook.json 角色規則與現行持倉／配置。
推播 deployable 建議：僅寫 Intent，不自動改 my_targets。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

WORKSPACE = os.environ.get("TWSTOCKALS_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))

from qty_suggest import (  # noqa: E402
    already_suggested_trim,
    format_intent_line,
    load_playbook,
    load_trim_state,
    make_intent,
    mark_trim_suggested,
    suggest_deployable,
    trim_shares,
    write_intents,
)

TARGETS = os.path.join(WORKSPACE, "config", "my_targets.json")
LEVELS = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
POLICY = os.path.join(WORKSPACE, "config", "grade_buy_policy.json")
REPORT = os.path.join(WORKSPACE, "reports", "latest", "position_playbook.md")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _nav_parts(targets: dict) -> dict:
    """粗估各袖口 TWD 市值。"""
    multi = targets.get("multi_asset") or {}
    gold = (multi.get("gold_passbook") or {}).get("approx_twd") or 0
    # 美金依「目的地」分兩袋（2026-07-21）：
    #   fx_ballast＝囤匯壓艙石（forex_usd，一直是美金）→ 歸 gold_fx 避險袖
    #   ib_usd    ＝匯IB待買股（IB現金＋電匯在途，要變美股）→ 歸 us_etf 袖（待部署）
    # 同一種幣不重複計兩袖；us_etf 缺口自動抵掉已在IB的美金，避免重複匯款。
    fx_rate = float(multi.get("usdtwd_rate_hint") or 32.4)
    fx_ballast = float((multi.get("forex_usd") or {}).get("approx_twd") or 0)
    ib_usd = (float(multi.get("ib_cash_usd") or 0)
              + float(multi.get("ib_wire_in_transit_usd") or 0)) * fx_rate
    usd = fx_ballast + ib_usd  # 合計仍計入總 NAV
    crypto = 0
    for c in multi.get("crypto") or []:
        if c.get("approx_twd_total_crypto"):
            crypto = float(c["approx_twd_total_crypto"])
            break
    port = {}
    for p in targets.get("portfolio") or []:
        code = str(p.get("code") or "")
        shares = float(p.get("shares") or 0)
        cost = float(p.get("cost") or 0)
        # 無即時價時用成本近似
        port[code] = {"shares": shares, "cost": cost, "approx": shares * cost}
    # overlay levels close if any
    levels = _load(LEVELS)
    for row in levels.get("levels") or []:
        code = str(row.get("code") or "")
        if code in port and row.get("close") is not None:
            port[code]["approx"] = float(port[code]["shares"]) * float(row["close"])
            port[code]["close"] = float(row["close"])
    invested = sum(v["approx"] for v in port.values()) + float(gold) + float(usd) + float(crypto)
    cash = float(multi.get("total_cash_twd") or 0)
    deployable = float(
        multi.get("deployable_cash_twd")
        or (targets.get("approved_universe") or {}).get("deployable_twd")
        or 0
    )
    if not deployable:
        deployable = float((_load(POLICY).get("deployable_cash_twd") or 0))
    total_nav = invested + cash
    return {
        "port": port,
        "gold": float(gold),
        "usd": float(usd),
        "fx_ballast": float(fx_ballast),  # 囤匯壓艙石 → gold_fx
        "ib_usd": float(ib_usd),          # 匯IB待買股 → us_etf 待部署
        "crypto": float(crypto),
        "invested": invested,
        "cash": cash,
        "deployable": deployable,
        "total_nav": total_nav or 1.0,
        "macro_level": int(levels.get("macro_level") or 2),
        "above_200": next(
            (r.get("above_200ma") for r in (levels.get("levels") or []) if r.get("code") == "TAIEX"),
            None,
        ),
    }


def _alloc_pct(nav: dict, key: str, targets: dict) -> tuple[float, float, float]:
    """回傳 (held_pct, target_pct, held_twd)。"""
    alloc = targets.get("allocation_targets") or {}
    target = float(alloc.get(key) or 0)
    total = nav["total_nav"]
    if key == "tw_lev_00631L":
        held = (nav["port"].get("00631L") or {}).get("approx") or 0
    elif key == "tw_core_0050":
        held = (nav["port"].get("0050") or {}).get("approx") or 0
    elif key == "bonds":
        held = (nav["port"].get("00687B") or {}).get("approx") or 0
    elif key == "tw_stocks":
        held = sum(
            (nav["port"].get(c) or {}).get("approx") or 0 for c in ("2301", "3484")
        )
    elif key == "gold":
        held = nav["gold"]
    elif key == "fx":
        held = nav.get("fx_ballast", nav["usd"])  # 只算囤匯壓艙石美金
    elif key == "gold_fx":
        # 舊合併鍵（向後相容）：黃金＋壓艙石美金
        held = nav["gold"] + nav.get("fx_ballast", nav["usd"])
    elif key == "crypto":
        held = nav["crypto"]
    elif key == "us_etf":
        # 美股袖＝已買ETF＋匯IB待買股的美金（現金＋在途）；後者是「待部署」進度
        held = sum(
            float(x.get("approx_twd") or 0)
            for x in ((targets.get("multi_asset") or {}).get("us_etf") or [])
        ) + nav.get("ib_usd", 0.0)
    else:
        held = 0.0
    held = float(held)
    return (held / total if total else 0.0), target, held


def build() -> dict:
    pb = load_playbook()
    targets = _load(TARGETS)
    policy = _load(POLICY)
    nav = _nav_parts(targets)
    intents = []
    cards = []
    trim_state = load_trim_state()

    # —— 正2 ——
    lev = nav["port"].get("00631L") or {}
    shares = float(lev.get("shares") or 0)
    close = lev.get("close") or lev.get("cost")
    pct, tgt, held_v = _alloc_pct(nav, "tw_lev_00631L", targets)
    # 帶寬 +3pp（2026-07-19 rebalance_band_backtest：窄帶寬只加摩擦，5-10%全面優於1-3%）
    over = pct > tgt + 0.03 if tgt else False
    card = {
        "code": "00631L",
        "role": "core_tw_lev",
        "entry": "conditional：≥B＋L1＋年線上",
        "add": "conditional：評等＋止穩；L≥3／破年線禁止",
        "tp": "僅超配再平衡（無常規10MA停利）",
        "sl": "破年線袖口減約1/3",
        "held_pct": round(pct * 100, 1),
        "target_pct": round(tgt * 100, 1),
        "today": "無動作",
    }
    if nav["above_200"] is False and shares > 0:
        qty, note = trim_shares(shares, 1 / 3)
        trigger = "sl_200"
        if not already_suggested_trim("00631L", trigger, trim_state):
            intents.append(
                make_intent(
                    code="00631L",
                    venue="TW",
                    side="sell",
                    action="sl",
                    qty=qty,
                    unit="股",
                    twd=(qty * float(close)) if close else None,
                    limit_ref="大盤破年線",
                    urgency="WARN",
                    rationale=f"正2破年線減碼｜{note}｜持有{shares:.0f}股",
                    priority=10,
                )
            )
            mark_trim_suggested("00631L", trigger, qty, trim_state)
            card["today"] = f"停損／減碼建議賣 {qty} 股（{note}）"
        else:
            card["today"] = "破年線減碼已建議、待回報成交（不重複累加）"
    elif over and shares > 0:
        # 超額股數
        excess_twd = held_v - tgt * nav["total_nav"]
        if close and close > 0:
            raw_sh = excess_twd / float(close)
            qty, note = trim_shares(min(shares, raw_sh), 1.0)
            if qty <= 0:
                qty, note = trim_shares(shares, 1 / 3)
            trigger = "rebalance"
            if not already_suggested_trim("00631L", trigger, trim_state):
                intents.append(
                    make_intent(
                        code="00631L",
                        venue="TW",
                        side="sell",
                        action="rebalance_trim",
                        qty=qty,
                        unit="股",
                        twd=qty * float(close),
                        limit_ref=f"超配 {pct*100:.1f}%>目標{tgt*100:.0f}%",
                        rationale=f"正2超配再平衡｜{note}",
                        priority=20,
                    )
                )
                mark_trim_suggested("00631L", trigger, qty, trim_state)
                card["today"] = f"再平衡建議賣 {qty} 股"
    elif nav["macro_level"] >= 3:
        card["today"] = "gate：禁止加倉（Level≥3）｜續抱年線"
        intents.append(
            make_intent(
                code="00631L",
                venue="TW",
                side="hold",
                action="gate_blocked",
                rationale="Level≥3 禁止加倉；破年線才減碼",
                gate_type="conditional",
                reenable_when="Level回1且站回年線",
                priority=90,
            )
        )
    cards.append(card)

    # —— 0050 底倉（純長抱；唯一減碼路徑＝超配再平衡） ——
    p0050 = nav["port"].get("0050") or {}
    sh50 = float(p0050.get("shares") or 0)
    px50 = p0050.get("close") or p0050.get("cost")
    c_pct, c_tgt, c_held = _alloc_pct(nav, "tw_core_0050", targets)
    card50 = {
        "code": "0050",
        "role": "core_tw",
        "entry": "≥B 分批（flat）",
        "add": "評等升級不加碼；新錢依 watch_grades",
        "tp": "無（純長抱 B方案）；僅超配再平衡",
        "sl": "無（exit_rule_backtest 2026-07-18）",
        "held_pct": round(c_pct * 100, 1),
        "target_pct": round(c_tgt * 100, 1),
        "today": "無動作" if sh50 else "尚未建倉（新錢走 watch_grades）",
    }
    # +5pp（rebalance_band_backtest 2026-07-19）
    if c_tgt and c_pct > c_tgt + 0.05 and sh50 > 0 and px50:
        excess_twd = c_held - c_tgt * nav["total_nav"]
        qty, note = trim_shares(min(sh50, excess_twd / float(px50)), 1.0)
        if qty > 0 and not already_suggested_trim("0050", "rebalance", trim_state):
            intents.append(
                make_intent(
                    code="0050",
                    venue="TW",
                    side="sell",
                    action="rebalance_trim",
                    qty=qty,
                    unit="股",
                    twd=qty * float(px50),
                    limit_ref=f"超配 {c_pct*100:.1f}%>目標{c_tgt*100:.0f}%",
                    rationale=f"0050 超配再平衡（純長抱唯一減碼路徑）｜{note}",
                    priority=30,
                )
            )
            mark_trim_suggested("0050", "rebalance", qty, trim_state)
            card50["today"] = f"再平衡建議賣 {qty} 股"
    cards.append(card50)

    # —— 美債出清 ——
    bond = nav["port"].get("00687B") or {}
    bsh = float(bond.get("shares") or 0)
    bclose = bond.get("close") or bond.get("cost")
    bcard = {
        "code": "00687B",
        "role": "gradual_exit",
        "entry": "structural 關（目標權重0）",
        "add": "structural 關｜解禁＝改 allocation＋role",
        "tp": "逢彈賣約1/3至清完",
        "sl": "不砍阿呆谷",
        "held_pct": round(_alloc_pct(nav, "bonds", targets)[0] * 100, 1),
        "target_pct": 0.0,
        "today": "分批出清中（見 EOD／短均）",
    }
    if bsh > 0 and bclose:
        qty, note = trim_shares(bsh, 1 / 3)
        bcard["today"] = f"逢彈可賣 {qty} 股（{note}）→轉現金／美金／黃金"
        # 不自動推 trim 除非 levels 有反彈訊號；僅列 playbook
    cards.append(bcard)

    # —— 個股 ——
    for code in ("2301", "3484"):
        p = nav["port"].get(code) or {}
        sh = float(p.get("shares") or 0)
        cards.append(
            {
                "code": code,
                "role": "stock_residual",
                "entry": "structural 關（不擴股池）",
                "add": "structural 關",
                "tp": "ROI12/25%＋移動均線（僅獲利）",
                "sl": "5日低兩日不站回→出清",
                "held_pct": None,
                "target_pct": None,
                "today": f"持有 {sh:.0f} 股｜禁止加倉｜詳 EOD levels",
            }
        )

    # —— 黃金（獨立超配檢查；黃金上限才真正生效，不再被 fx 稀釋） ——
    g_pol = (policy.get("products") or {}).get("GOLD") or {}
    u_pol = (policy.get("products") or {}).get("USDTWD") or {}
    g_pct, g_tgt, g_held = _alloc_pct(nav, "gold", targets)
    gold_today = f"持有約 {nav['gold']:,.0f} 元（{g_pct*100:.1f}%／目標{g_tgt*100:.0f}%）"
    if g_tgt and g_pct > g_tgt + 0.05:  # +5pp
        excess = g_held - g_tgt * nav["total_nav"]
        gold_today = f"黃金超配 {g_pct*100:.1f}%>{g_tgt*100:.0f}%｜建議減約 {excess:,.0f} 元"
        if not already_suggested_trim("GOLD", "rebalance", trim_state):
            intents.append(make_intent(
                code="GOLD", venue="BOT", side="sell", action="rebalance_trim",
                qty=None, unit="", twd=excess,
                limit_ref=f"黃金 {g_pct*100:.1f}%>目標{g_tgt*100:.0f}%",
                rationale="黃金超配再平衡（獨立上限；長抱唯一減碼路徑）", priority=30))
            mark_trim_suggested("GOLD", "rebalance", 0, trim_state)
    cards.append({
        "code": "GOLD", "role": "gold",
        "entry": f"≥{g_pol.get('buy_min_grade', 'B')}；budget 見 policy",
        "add": "≥B＋未滿budget（買滿長抱）",
        "tp": "僅超配再平衡；50MA停利已停用", "sl": "未過gate＝不加（非硬停損）",
        "held_pct": round(g_pct * 100, 1), "target_pct": round(g_tgt * 100, 1),
        "today": gold_today,
    })

    # —— 美金壓艙石（獨立目標；只算囤匯，不含匯IB待買股的美金） ——
    fx_pct, fx_tgt, fx_held = _alloc_pct(nav, "fx", targets)
    fx_today = f"壓艙石約 {nav.get('fx_ballast', 0):,.0f} 元（{fx_pct*100:.1f}%／目標{fx_tgt*100:.0f}%）"
    if fx_tgt and fx_pct > fx_tgt + 0.03:  # 低波動，帶寬窄一點
        excess = fx_held - fx_tgt * nav["total_nav"]
        fx_today = f"美金壓艙石超配 {fx_pct*100:.1f}%>{fx_tgt*100:.0f}%｜可減約 {excess:,.0f} 元（或轉IB買股）"
    elif fx_tgt and fx_pct < fx_tgt - 0.03:
        fx_today += "｜低於目標，美金回到買點區（乖離年線轉負）時補壓艙石"
    cards.append({
        "code": "USDTWD", "role": "usd_fx_ballast",
        "entry": f"≥{u_pol.get('buy_min_grade', 'A')}（囤匯壓艙石，非匯IB款）",
        "add": "≥A且美金便宜；乖離≥1.5%關加", "tp": "1.5%/3%袖口減碼",
        "sl": "同均值回歸減碼",
        "held_pct": round(fx_pct * 100, 1), "target_pct": round(fx_tgt * 100, 1),
        "today": fx_today,
    })

    # —— crypto 超配 ——
    cpct, ctgt, cheld = _alloc_pct(nav, "crypto", targets)
    ccard = {
        "code": "CRYPTO",
        "role": "crypto",
        "entry": "超配則先 trim；達標後才談建倉",
        "add": "達標前禁止",
        "tp": "主＝再平衡至目標占比",
        "sl": "破50MA優先清超額",
        "held_pct": round(cpct * 100, 1),
        "target_pct": round(ctgt * 100, 1),
        "today": "達標",
    }
    # 小袖用相對帶寬 ~50%目標（3%→觸發於4.5%）；絕對帶寬對小袖永不觸發
    if cpct > ctgt + 0.015 and cheld > 0:
        excess = cheld - ctgt * nav["total_nav"]
        ccard["today"] = f"超配｜建議減約 {excess:,.0f} 元市值至≤{ctgt*100:.0f}%"
        intents.append(
            make_intent(
                code="CRYPTO",
                venue="CEX",
                side="sell",
                action="rebalance_trim",
                qty=None,
                unit="",
                twd=excess,
                limit_ref=f"占比{cpct*100:.1f}%>目標{ctgt*100:.0f}%",
                urgency="WARN",
                rationale="加密超配：主路徑再平衡減碼（非只等破線）",
                gate_type="temporary",
                reenable_when="占比≤目標後才可談加碼",
                priority=20,
            )
        )
    cards.append(ccard)

    # —— 資金部署 ——
    dep = suggest_deployable(
        total_liquid=nav["cash"] or nav["deployable"] * 2,
        deployable_now=nav["deployable"],
        macro_level=nav["macro_level"],
        playbook=pb,
    )
    # total_liquid：優先 total_cash
    if nav["cash"] <= 0 and nav["deployable"] > 0:
        dep = suggest_deployable(
            total_liquid=nav["deployable"] / max(dep["ratio"], 0.15),
            deployable_now=nav["deployable"],
            macro_level=nav["macro_level"],
            playbook=pb,
        )
    deploy_line = "維持"
    if dep.get("action"):
        intents.append(
            make_intent(
                code="CASH",
                venue="BANK",
                side="adjust",
                action=dep["action"],
                qty=None,
                unit="",
                twd=dep["target_deployable"],
                limit_ref=f"Level{dep['level']} ratio={dep['ratio']:.0%}",
                urgency="INFO",
                rationale=(
                    f"建議可再投入上限 {dep['deployable_now']:,.0f}→{dep['target_deployable']:,.0f}元"
                    f"（地板{dep['cash_floor']:,.0f}）；確認後再改設定"
                ),
                gate_type="conditional",
                reenable_when=dep.get("reenable_when", ""),
                priority=60,
            )
        )
        deploy_line = (
            f"{'上調' if dep['action']=='raise_deploy_budget' else '下調'}至 "
            f"{dep['target_deployable']:,.0f} 元"
        )

    path = write_intents(
        intents,
        extra={"nav": {k: nav[k] for k in ("invested", "cash", "deployable", "total_nav", "macro_level")}},
    )

    # —— markdown ——
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 持倉操作 Playbook（四件套）",
        "",
        f"- 產生：{now}",
        f"- 目標函數：{pb.get('objective')}",
        f"- 階段1：{pb.get('phase1_verdict')} — {pb.get('phase1_note')}",
        f"- NAV 粗估：總計約 {nav['total_nav']:,.0f}｜已投資 {nav['invested']:,.0f}｜"
        f"現金 {nav['cash']:,.0f}｜可再投入 {nav['deployable']:,.0f}｜Level **{nav['macro_level']}**",
        f"- Intent：`reports/latest/action_intents.json`",
        "",
        "## 資金部署",
        "",
        f"- 今日建議：**{deploy_line}**（推播≠已改 `deployable_cash_twd`）",
        "",
        "## 各商品四件套",
        "",
        "| 代號 | 角色 | 建倉 | 加倉 | 停利／再平衡 | 停損 | 持倉%/目標% | 今日 |",
        "|------|------|------|------|--------------|------|-------------|------|",
    ]
    for c in cards:
        hp = c.get("held_pct")
        tp = c.get("target_pct")
        pct_s = f"{hp}/{tp}" if hp is not None else "—"
        lines.append(
            f"| {c['code']} | {c['role']} | {c['entry']} | {c['add']} | {c['tp']} | {c['sl']} | "
            f"{pct_s} | {c['today']} |"
        )
    lines += [
        "",
        "## 今日 Intent（已去重優先序）",
        "",
    ]
    data = _load(path)
    if data.get("intents"):
        for i, it in enumerate(data["intents"], 1):
            lines.append(f"{i}. {format_intent_line(it)}")
    else:
        lines.append("*無強制 Intent（或僅 gate 說明）。*")
    lines += [
        "",
        "## 規則備註",
        "",
        "- 正2：**無常規10MA停利**（階段1 B／PASS_CP）；破年線才袖口減。",
        "- 超配：主路徑再平衡；gate 關閉時報告說明、不催買。",
        "- 數量：台股整張；不足1張標餘額出清。",
        "",
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {REPORT}")
    print(f"Wrote {path} ({len(data.get('intents') or [])} intents)")
    return {"report": REPORT, "intents": path, "deploy": dep, "cards": len(cards)}


def main():
    res = build()
    if "--notify" in sys.argv:
        try:
            from notify import notify

            data = _load(res["intents"])
            actionable = [
                i
                for i in (data.get("intents") or [])
                if i.get("action") not in ("gate_blocked", "hold")
            ]
            if actionable:
                body = "\n".join(f"{n}. {format_intent_line(i)}" for n, i in enumerate(actionable, 1))
                body += "\n\n（確認後才改設定／下單；詳 position_playbook.md）"
                notify(
                    title=f"Playbook 動作 {datetime.now().strftime('%m/%d %H:%M')}（{len(actionable)}）",
                    body=body,
                    symbol="PLAYBOOK",
                    rule_id="playbook_digest",
                    urgency="INFO",
                    force="--force-notify" in sys.argv,
                )
                print(f"notify {len(actionable)} actionable intents")
            else:
                print("無須推播的 Intent（僅 gate/hold）")
        except Exception as e:
            print(f"notify 略過：{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
