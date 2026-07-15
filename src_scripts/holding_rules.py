# -*- coding: utf-8 -*-
"""持股分類：核心 ETF vs 個股停損停利規則。"""
from __future__ import annotations

# 長抱核心／配置型：不用個股 5日低 + 均線停利
CORE_ETF_CODES = frozenset({"0050", "00631L", "00687B"})

# 已剔除、不該再推「建倉」的代號（改提示銀行美元／黃金等）
REJECTED_BUY_CODES = frozenset({"00682U", "00635U", "PDBC", "USO", "XLE"})


def is_core_etf(code: str, name: str = "") -> bool:
    code = str(code or "")
    if code in CORE_ETF_CODES:
        return True
    if code in ("00687B",) or "債" in str(name):
        return True
    return False


def uses_stock_stop_rules(code: str, name: str = "", *, force_exit: bool = False) -> bool:
    """個股殘倉與 force_exit 衛星 ETF 才走 5日低／移動停利。"""
    if force_exit:
        return True
    if is_core_etf(code, name):
        return False
    return True


def core_etf_hold_text(code: str) -> str:
    code = str(code)
    if code == "00631L":
        return "正2：看大盤年線+Level；給成本／均線加減碼建議（非5日低硬砍）"
    if code == "00687B" or code.endswith("87B"):
        return "美債：長期逢彈出清 → 現金／美金／黃金；不加碼、不攤平"
    if code == "0050":
        return "0050底倉：目標占比再平衡；Level 1 回測分批"
    return "核心ETF：年線／Level／成本走勢建議"


def _fmt_px(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_roi(roi) -> str:
    if roi is None:
        return "—"
    return f"{float(roi):+.1f}%"


def core_etf_eod_actions(
    code: str,
    name: str,
    *,
    macro_level: int,
    above_200ma: bool | None,
    close: float | None = None,
    cost: float | None = None,
    roi_pct: float | None = None,
    ma5: float | None = None,
    ma10: float | None = None,
    ma20: float | None = None,
) -> list[str]:
    """核心 ETF 收盤後具體建議（含成本／走勢）。"""
    code = str(code)
    label = f"{code} {name}".strip()
    out: list[str] = []

    if roi_pct is None and cost and close and float(cost) > 0:
        roi_pct = (float(close) / float(cost) - 1.0) * 100.0

    below_ma10 = (
        close is not None and ma10 is not None and float(close) < float(ma10)
    )
    below_ma5 = (
        close is not None and ma5 is not None and float(close) < float(ma5)
    )
    near_ma10 = False
    if close is not None and ma10 is not None and float(ma10) > 0:
        near_ma10 = abs(float(close) - float(ma10)) / float(ma10) * 100 <= 1.2

    if code == "00631L":
        bits = [
            f"正2 {label}",
            f"成本 {_fmt_px(cost)}／現價 {_fmt_px(close)}（{_fmt_roi(roi_pct)}）",
            f"5MA {_fmt_px(ma5)}／10MA {_fmt_px(ma10)}",
            f"Level {macro_level}",
            "年線上" if above_200ma else ("年線下" if above_200ma is False else "年線不明"),
        ]
        head = "｜".join(bits)

        if above_200ma is False:
            # 年線破 → 真正減碼窗
            if roi_pct is not None and roi_pct > 0:
                out.append(
                    f"{head} → 【減碼】大盤破年線；帳面仍賺，建議先賣約 1/3～1/2 鎖定，剩倉看能否站回年線"
                )
            else:
                out.append(
                    f"{head} → 【減碼／空倉】大盤破年線且未賺；建議分批減至空倉或極小衛星，勿攤平"
                )
        elif macro_level >= 3:
            # 破月線但年線仍在：不加碼；依成本與短均給續抱／小減
            if below_ma5 or below_ma10:
                if roi_pct is not None and roi_pct >= 3:
                    out.append(
                        f"{head} → 【可小減】Level3＋破短均、仍小賺；可先賣約 1/3 降波動，其餘續抱等年線"
                    )
                elif roi_pct is not None and roi_pct > -3:
                    out.append(
                        f"{head} → 【續抱、禁止加碼】Level3＋小虧／平盤破短均；"
                        f"不砍在恐慌、不加碼；若收盤連兩日站不回 10MA({_fmt_px(ma10)}) 再考慮減 1/3"
                    )
                else:
                    out.append(
                        f"{head} → 【減碼優先於加碼】Level3＋虧損擴大；"
                        f"可先減約 1/3～1/2 控風險，剩餘續抱年線；禁止攤平"
                    )
            else:
                out.append(
                    f"{head} → 【續抱、禁止加碼】Level3 但短均未破；既有倉續抱，新錢不做正2"
                )
        elif macro_level == 2:
            out.append(
                f"{head} → 【不加碼】Level2 警戒；既有倉續抱，等 Level 回 1 或回測 10MA({_fmt_px(ma10)}) 再評估"
            )
        else:
            # Level 1 + 年線上
            if near_ma10 and (roi_pct is None or roi_pct < 8):
                out.append(
                    f"{head} → 【可小加】年線上＋Level1＋近 10MA；"
                    f"允許小額加碼（非必須），總部位仍受配置上限"
                )
            elif below_ma10 and roi_pct is not None and roi_pct >= 12:
                out.append(
                    f"{head} → 【可移動減碼】已賺 {_fmt_roi(roi_pct)} 且破 10MA；"
                    f"可先賣約 1/3 鎖利，其餘續抱年線"
                )
            else:
                out.append(
                    f"{head} → 【續抱】年線上＋Level1；無急迫加減，加碼看 watch_grades 評等"
                )

    elif code == "00687B" or "債" in name:
        bits = (
            f"美債 {label}｜成本 {_fmt_px(cost)}／現價 {_fmt_px(close)}（{_fmt_roi(roi_pct)}）"
            f"｜Level {macro_level}"
        )
        # 長期出清：不續抱當核心；逢彈分批轉現金／美金／黃金
        if below_ma5 or below_ma10:
            out.append(
                f"{bits} → 【續抱等彈】短均下方不砍低；反彈靠近 10MA({_fmt_px(ma10)}) "
                f"或單日彈≥2% 時賣約 1/3，資金轉現金／台銀美金／黃金"
            )
        elif near_ma10 or (ma5 and close and float(close) >= float(ma5)):
            out.append(
                f"{bits} → 【逢彈減碼】已近／站上短均，可先賣約 1/3～1/2；"
                f"剩餘同樣逢彈出清，目標債券占比→0，改現金／美金／黃金"
            )
        else:
            out.append(
                f"{bits} → 【分批出清中】不加碼、不攤平；"
                f"有反彈就減，出清後轉現金／台銀美金／黃金存摺"
            )

    elif code == "0050":
        bits = (
            f"0050 {label}｜成本 {_fmt_px(cost)}／現價 {_fmt_px(close)}（{_fmt_roi(roi_pct)}）"
            f"｜Level {macro_level}"
        )
        if macro_level >= 3:
            out.append(f"{bits} → 【底倉續抱】暫停積極加碼；新錢優先現金／防禦")
        elif macro_level == 2:
            out.append(f"{bits} → 【僅深拉回】月線附近才小買，不追價")
        else:
            out.append(
                f"{bits} → 【可分批】Level1；回測 5/10MA 分批買底倉（見 watch_grades）"
            )

    return out
