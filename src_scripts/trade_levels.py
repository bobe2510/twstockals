# -*- coding: utf-8 -*-
"""進場／出場說明：推薦推播一律附帶點位。"""
from __future__ import annotations

from typing import Any, Optional


def _px(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def entry_plan_for_symbol(
    s: dict,
    *,
    code: str,
    market: str = "TW",
    grade: str = "",
) -> str:
    """依均線產出進場／防守／停利說明（給觀測推薦用）。"""
    px = s.get("price")
    ma5, ma10, ma20 = s.get("ma5"), s.get("ma10"), s.get("ma20")
    ma50, ma200 = s.get("ma50"), s.get("ma200")
    lines: list[str] = []

    if market == "US" or code in ("VOO", "VXUS", "QQQ", "QQQM"):
        entry = ma50 or ma20 or ma5
        hard = ma200
        lines.append(f"進場參考：現價 {_px(px)}；優先靠近季線(50MA) {_px(ma50)} 分批")
        if ma20:
            lines.append(f"亦可對齊月線附近 {_px(ma20)}")
        lines.append(
            f"防守：收盤跌破年線(200MA) {_px(hard)} → 減碼／暫停加碼（EOD確認）"
        )
        lines.append("停利：達標可先賣約1/3；其餘用季線／年線移動防守（非盤中殺）")
        return "\n".join(lines)

    if code == "00631L":
        lines.append(f"進場／加碼：現價 {_px(px)}；回測 10MA {_px(ma10)} 或 20MA {_px(ma20)}（須年線上＋Level≤2）")
        lines.append("硬條件：大盤收盤跌破年線 → 正2減碼／空倉（EOD）")
        lines.append(f"輔助減碼：收盤跌破 10MA {_px(ma10)} 可先減，不必一次砍光")
        return "\n".join(lines)

    if code == "0050":
        lines.append(f"進場：現價 {_px(px)}；回測 5MA {_px(ma5)}／10MA {_px(ma10)} 分批（Level1；Level3不加）")
        lines.append(f"更深買點：月線 20MA {_px(ma20)} 附近")
        lines.append(f"移動防守：收盤跌破 10MA {_px(ma10)} 可減；硬停可看 5日低（持股後）")
        return "\n".join(lines)

    # 一般台股觀測
    lines.append(f"初次進場：回測 5MA {_px(ma5)}（現價 {_px(px)}）")
    lines.append(f"加碼：10MA {_px(ma10)}；月線防守／加碼 20MA {_px(ma20)}")
    # 5日低若無，用約略
    lines.append("停損：收盤跌破近5日低（建倉後以 levels 為準，EOD確認）")
    lines.append(f"停利：獲利後收盤跌破 10MA {_px(ma10)}（或強勢用5MA）移動停利")
    if grade in ("A", "S"):
        lines.append(f"本檔評等 {grade}：較建議在上述進場帶分批，勿追離均線過遠")
    return "\n".join(lines)


def holding_exit_plan(
    *,
    code: str,
    name: str,
    close: Optional[float],
    cost: Optional[float],
    roi_pct: Optional[float],
    stop: Optional[float],
    profit: Optional[float],
    ma5: Optional[float] = None,
    ma10: Optional[float] = None,
    is_etf_core: bool = False,
    policy: str = "",
) -> list[str]:
    """持股必報：成本、停損、停利狀態。"""
    out: list[str] = []
    label = f"{code} {name}".strip()
    cost_s = _px(cost)
    close_s = _px(close)
    roi_s = f"{float(roi_pct):+.1f}%" if roi_pct is not None else "—"

    if is_etf_core or policy == "gradual_exit":
        # ETF 核心另有 holding_rules；這裡只補狀態列
        return out

    # 個股：一定說清楚停損／停利價
    head = f"{label}｜成本 {cost_s}／現價 {close_s}（{roi_s}）"
    stop_s = _px(stop)
    profit_s = _px(profit)

    if stop is not None and close is not None and float(close) <= float(stop):
        out.append(f"停損（砍虧）：{head}｜已觸發 ≤ 停損 {stop_s}（5日低）")
    else:
        out.append(f"停損守備：{head}｜停損價 {stop_s}（收盤跌破才執行）")

    # 套牢部位：只報停損／續抱，絕不以「停利」字樣推播（避免誤砍虧）
    if roi_pct is not None and float(roi_pct) <= 0:
        out.append(
            f"殘倉套牢：{label} {roi_s}｜勿當停利賣；僅盯停損 {stop_s}（收盤確認）"
        )
        return out

    if roi_pct is not None and float(roi_pct) > 0 and profit is not None:
        if close is not None and float(close) < float(profit):
            out.append(
                f"停利（鎖定漲幅）：{label} 報酬 {roi_s}｜收盤 {close_s} < 停利線 {profit_s}"
            )
        else:
            out.append(
                f"停利線：{label} 報酬 {roi_s}｜移動停利 {profit_s}"
                f"（5MA {_px(ma5)}／10MA {_px(ma10)}）｜未跌破則續抱"
            )
    elif profit is not None:
        out.append(f"停利線參考：{profit_s}（需先轉為獲利才啟動移動停利）")

    return out
