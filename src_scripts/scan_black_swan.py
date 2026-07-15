# -*- coding: utf-8 -*-
import os
import json
import urllib.request
import xml.etree.ElementTree as ET
import ctypes
import sys
import shutil
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
LOG_FILE = os.path.join(WORKSPACE, "reports", "black_swan_alerts.log")
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "black_swan_defense.md")
LEVELS_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
ALERT_RULES_PATH = os.path.join(WORKSPACE, "config", "alert_rules.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from tw_time import taiwan_now  # noqa: E402
try:
    from notify import notify, load_alert_rules
    from holding_rules import is_core_etf
except Exception:
    notify = None
    is_core_etf = lambda code, name="": False  # noqa: E731

    def load_alert_rules():
        if os.path.exists(ALERT_RULES_PATH):
            with open(ALERT_RULES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

# 警報閾值設定（可被 alert_rules.json 覆寫）
TAIEX_ALERT_PCT = -1.5
PORTFOLIO_ALERT_PCT = -4.0
TRACKED_ALERT_PCT = -7.0
TWD_ALERT_PCT = 0.40
US_ALERT_PCT = -3.0

PANIC_KEYWORDS = ["崩跌", "暴跌", "重挫", "慘跌", "跌停", "違約交割", "斷頭", "系統性風險", "黑天鵝", "崩盤", "危機", "債務違約", "美債大跌"]
RELEVANT_SECTORS = ["電腦", "週邊", "伺服器", "散熱", "PCB", "印刷電路", "電子", "半導體", "債券", "美債", "美金"]
OTC_CODES = {"3483", "00687B", "7734", "4542", "7828", "6291", "3484", "3624", "6163", "6510"}


def apply_threshold_overrides():
    global TAIEX_ALERT_PCT, PORTFOLIO_ALERT_PCT, TRACKED_ALERT_PCT, TWD_ALERT_PCT, US_ALERT_PCT
    rules = load_alert_rules()
    th = rules.get("thresholds") or {}
    TAIEX_ALERT_PCT = float(th.get("taiex_alert_pct", TAIEX_ALERT_PCT))
    PORTFOLIO_ALERT_PCT = float(th.get("portfolio_alert_pct", PORTFOLIO_ALERT_PCT))
    TRACKED_ALERT_PCT = float(th.get("tracked_alert_pct", TRACKED_ALERT_PCT))
    TWD_ALERT_PCT = float(th.get("twd_alert_pct", TWD_ALERT_PCT))
    US_ALERT_PCT = float(th.get("us_alert_pct", US_ALERT_PCT))
    return rules


def load_targets():
    json_path = os.path.join(WORKSPACE, "config", "my_targets.json")
    if not os.path.exists(json_path):
        return [], [], set()
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    cleared = {
        str(x.get("code"))
        for x in (data.get("cleared_positions") or [])
        if x.get("code")
    }
    return data.get("portfolio", []), data.get("watchlist", []), cleared


def load_levels():
    if not os.path.exists(LEVELS_PATH):
        return {}
    try:
        with open(LEVELS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_tw_code(code):
    code = str(code)
    if not code or code.isalpha():
        return False
    return code.isdigit() or (code[:1].isdigit() and code.isalnum())


def get_realtime_prices(symbols):
    tw_symbols = [c for c in symbols if is_tw_code(c)]
    ex_ch_list = ["tse_t00.tw"]
    for code in tw_symbols:
        prefix = "otc" if code in OTC_CODES else "tse"
        ex_ch_list.append(f"{prefix}_{code}.tw")

    ex_ch_str = "|".join(ex_ch_list)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res = response.read().decode('utf-8')
            data = json.loads(res)
            return data.get("msgArray", [])
    except Exception as e:
        print(f"抓取即時報價失敗: {e}")
        return []


def fetch_yahoo_quote(sym):
    """Compat: use market_data (Stooq/Binance/Yahoo fallback)."""
    try:
        from market_data import fetch_quote
        q = fetch_quote(sym)
        if not q:
            return None
        return {
            "symbol": sym,
            "price": q["price"],
            "prev_close": q["prev_close"],
            "change_pct": q["change_pct"],
            "source": q.get("source"),
        }
    except Exception as e:
        print(f"quote {sym} 失敗: {e}")
        return None


def check_us_market_indicators():
    symbols = {
        "TSM": "台積電 ADR",
        "EWT": "MSCI 台灣 ETF",
        "NQ=F": "那斯達克 100 期指"
    }
    results = []
    for sym, name in symbols.items():
        q = fetch_yahoo_quote(sym)
        if not q:
            continue
        change_pct = q["change_pct"]
        is_warning = change_pct <= US_ALERT_PCT
        results.append({
            "symbol": sym,
            "name": name,
            "price": q["price"],
            "change_pct": change_pct,
            "is_warning": is_warning,
            "message": (
                f"🇺🇸 {name} ({sym}) 大跌 {change_pct:.2f}%！"
                f"(最新價: {q['price']:.2f} / 昨收: {q['prev_close']:.2f})"
            ) if is_warning else ""
        })
    return results


def check_multi_asset_shocks(rules):
    th = rules.get("thresholds") or {}
    gold_th = float(th.get("gold_alert_pct", -5.0))
    crypto_th = float(th.get("crypto_alert_pct", -8.0))
    us_etf_th = float(th.get("us_etf_alert_pct", -5.0))
    twd_th = float(th.get("twd_alert_pct", TWD_ALERT_PCT))

    specs = [
        ("GC=F", "黃金", gold_th, False),
        ("BTC-USD", "Bitcoin", crypto_th, False),
        ("ETH-USD", "Ethereum", crypto_th, False),
        ("VOO", "VOO", us_etf_th, False),
        ("VXUS", "VXUS", us_etf_th, False),
        ("QQQ", "QQQ", us_etf_th, False),
        ("USDTWD=X", "美元兌台幣", twd_th, True),
    ]
    alerts = []
    status = []
    for sym, name, thr, upside_bad in specs:
        q = fetch_yahoo_quote(sym)
        if not q:
            continue
        status.append({"symbol": sym, "name": name, **q})
        if upside_bad:
            if q["change_pct"] >= thr:
                alerts.append(f"💸 {name} ({sym}) 急升/貶值壓力 {q['change_pct']:+.2f}%")
        else:
            if q["change_pct"] <= thr:
                alerts.append(f"🌊 {name} ({sym}) 急跌 {q['change_pct']:+.2f}%（閾值 {thr}%）")
    return alerts, status


def scan_news_headlines(relevant_names):
    alerts = []
    seen_titles = set()

    url_yahoo = "https://tw.news.yahoo.com/rss/stock"
    req_yahoo = urllib.request.Request(url_yahoo, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req_yahoo, timeout=10) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item')[:15]:
                title = item.find('title').text.strip()
                link = item.find('link').text.strip()
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                has_panic = any(kw in title for kw in PANIC_KEYWORDS)
                is_relevant = any(x in title for x in ["台股", "加權", "台積電", "輝達"]) or \
                              any(name in title for name in relevant_names) or \
                              any(sec in title for sec in RELEVANT_SECTORS)
                if has_panic and is_relevant:
                    alerts.append({"title": title, "link": link, "source": "Yahoo新聞"})
    except Exception as e:
        print(f"Yahoo 新聞頭條掃描失敗: {e}")

    url_cnyes = "https://news.cnyes.com/api/v3/news/category/headline?limit=15"
    req_cnyes = urllib.request.Request(url_cnyes, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req_cnyes, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            news_items = data.get("items", {}).get("data", [])
            for item in news_items:
                title = item.get("title", "").strip()
                news_id = item.get("newsId")
                if not title or not news_id or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = f"https://news.cnyes.com/news/id/{news_id}"
                has_panic = any(kw in title for kw in PANIC_KEYWORDS)
                is_relevant = any(x in title for x in ["台股", "加權", "台積電", "輝達", "美股", "降息"]) or \
                              any(name in title for name in relevant_names) or \
                              any(sec in title for sec in RELEVANT_SECTORS)
                if has_panic and is_relevant:
                    alerts.append({"title": title, "link": link, "source": "鉅亨頭條"})
    except Exception as e:
        print(f"鉅亨網頭條 API 掃描失敗: {e}")
    return alerts


def check_twd_exchange_rate():
    q = fetch_yahoo_quote("USDTWD=X")
    if not q:
        return None
    change_pct = q["change_pct"]
    current_rate = q["price"]
    prev_close = q["prev_close"]
    is_warning = change_pct >= TWD_ALERT_PCT
    return {
        "rate": current_rate,
        "change_pct": change_pct,
        "is_warning": is_warning,
        "message": (
            f"💸 新台幣急貶！目前匯率 {current_rate:.4f} "
            f"(昨收: {prev_close:.4f} / 貶值: {change_pct:+.2f}%)，警惕外資提款風險！"
        ) if is_warning else f"目前匯率: {current_rate:.4f} (波幅: {change_pct:+.2f}%)"
    }


def trigger_desktop_alert(message):
    ctypes.windll.user32.MessageBoxW(0, message, "🚨 台股黑天鵝警報 🚨", 0x10 | 0x0)


def check_stop_level_breaches(
    price_map,
    levels_doc,
    *,
    close_confirm=False,
    live_portfolio_codes=None,
    cleared_codes=None,
):
    """個股破防守：盤中只記錄；close_confirm 才產生可推播文案。

    必須與 my_targets 即時持股交集：levels.json 過期時不得對已出清標的推播。
    """
    # None = 未提供活持股（僅靠 cleared 過濾）；空 set = 無持股 → 全部跳過
    live = None if live_portfolio_codes is None else set(live_portfolio_codes)
    cleared = set(cleared_codes or [])
    alerts = []
    for row in levels_doc.get("levels") or []:
        if row.get("status") != "portfolio":
            continue
        code = str(row.get("code") or "")
        if not code:
            continue
        # 活持股為準：不在 portfolio、或已列入 cleared_positions → 永不告警
        if live is not None and code not in live:
            continue
        if code in cleared:
            continue
        if row.get("profit_rule") == "etf_core" or is_core_etf(code, row.get("name", "")):
            continue
        stop = row.get("stop") or row.get("low_5d")
        if code not in price_map or stop is None:
            continue
        px = price_map[code]
        if px <= stop:
            if close_confirm:
                alerts.append(
                    f"🛡️ 收盤確認破防守：{code} {row.get('name','')} "
                    f"近收盤 {px:.2f} ≤ 停損 {stop:.2f}。"
                    f"請再核對 13:30 收盤；執行窗 13:40 後／隔日開盤，禁止開盤殺低。"
                )
            else:
                alerts.append(
                    f"（盤中僅記錄不推播）{code} {row.get('name','')} "
                    f"盤中 {px:.2f} ≤ 停損 {stop:.2f} → 改約 13:10 收盤確認"
                )
    return alerts


def in_close_confirm_window(now, rules):
    cc = rules.get("close_confirm") or {}
    if cc.get("enabled") is False:
        return False
    start = str(cc.get("start_hhmm", "1305"))
    end = str(cc.get("end_hhmm", "1325"))
    t = now.strftime("%H%M")
    return start <= t <= end


def main():
    now = taiwan_now()
    current_hour = now.hour
    rules = apply_threshold_overrides()

    is_force = "--force" in sys.argv
    asset_window = "--asset-window" in sys.argv
    close_confirm = "--close-confirm" in sys.argv
    in_tw_session = 7 <= current_hour < 14
    in_asset_session = current_hour >= 20 or current_hour < 5

    if not is_force and not close_confirm:
        if asset_window and not in_asset_session:
            print(
                f"非多資產晚間視窗 (台北 20:00~05:00) 且無 --force，退出。"
                f" now={now.isoformat()}"
            )
            sys.exit(0)
        if (not asset_window) and (not in_tw_session):
            print(
                f"非盤中監控時間 (台北 07:00 ~ 13:59) 且無 --force 參數，腳本默默退出。"
                f" now={now.isoformat()}"
            )
            sys.exit(0)

    no_popup = "--no-popup" in sys.argv
    enable_alert_popup = (
        (is_force or in_tw_session)
        and not no_popup
        and not asset_window
        and not close_confirm
    )
    push_stock_plunge = bool(rules.get("intraday_push_stock_plunge", False))

    mode_label = (
        "收盤確認破防守"
        if close_confirm
        else ("多資產視窗" if asset_window else "台股緊急／大盤（個股停損不推）")
    )
    print(f"開始掃描市場狀態... 基準時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"模式: {mode_label} | 彈窗: {'開' if enable_alert_popup else '關'}")

    holdings, watchlist, cleared_codes = load_targets()
    levels_doc = load_levels()
    # force_exit 僅對「仍持有」標的生效；已出清者不應再推
    force_exit_codes = {
        str(c) for c in (levels_doc.get("force_exit_codes") or [])
        if str(c) not in cleared_codes
    }
    for h in holdings:
        if h.get("force_exit"):
            force_exit_codes.add(h["code"])
    reverse_like = (
        ({"00632R"} | {c for c in force_exit_codes if str(c).endswith("R")})
        - cleared_codes
    )

    all_codes = []
    portfolio_codes = set()
    watchlist_codes = set()
    code_to_name = {}
    relevant_names = []

    for h in holdings:
        code = h["code"]
        if code in cleared_codes:
            continue  # 防呆：cleared 與 portfolio 同時出現時以出清為準
        all_codes.append(code)
        portfolio_codes.add(code)
        code_to_name[code] = h["name"]
        relevant_names.append(h["name"])

    for w in watchlist:
        code = w["code"]
        if w.get("market") == "US":
            continue
        if code not in portfolio_codes:
            all_codes.append(code)
            watchlist_codes.add(code)
            code_to_name[code] = w["name"]
            relevant_names.append(w["name"])

    price_alerts = []
    price_status_list = []
    price_map = {}
    msg_array = get_realtime_prices(all_codes) if not asset_window else []

    taiex_change = 0.0
    taiex_close = 0.0

    for stock in msg_array:
        code = stock.get("c")
        name = stock.get("n", "")
        try:
            prev_close = float(stock.get("y", 0.0))
            if prev_close <= 0:
                continue
            z_val = stock.get("z", "-")
            if z_val != "-" and z_val != "":
                current_price = float(z_val)
            else:
                b_val = stock.get("b", "-")
                if b_val != "-" and b_val != "":
                    current_price = float(b_val.split("_")[0])
                else:
                    current_price = prev_close
            change_pct = ((current_price - prev_close) / prev_close) * 100

            if code == "t00":
                taiex_change = change_pct
                taiex_close = current_price
                if change_pct <= TAIEX_ALERT_PCT:
                    price_alerts.append(
                        f"🔴 加權指數 (大盤) 重挫 {change_pct:.2f}%！(最新價: {current_price:.2f})"
                        f"｜個股防守改收盤確認，勿盤中殺低。"
                    )
            else:
                price_map[code] = current_price
                status = "持股" if code in portfolio_codes else "觀測"
                price_status_list.append({
                    "code": code,
                    "name": code_to_name.get(code, name),
                    "status": status,
                    "prev_close": prev_close,
                    "close": current_price,
                    "change_pct": change_pct
                })
                # 個股重挫：盤中原則不推（避免阿呆谷）；反1／force_exit 例外；收盤確認窗可推
                if code in portfolio_codes and change_pct <= PORTFOLIO_ALERT_PCT:
                    line = (
                        f"⚠️ 持股【{code} {code_to_name[code]}】重挫 {change_pct:.2f}%！"
                        f"(最新價: {current_price:.2f})"
                    )
                    if code in reverse_like:
                        price_alerts.append(
                            line + "｜若為反1／出清標的：可規劃逢高變現（非殺多單）。"
                        )
                    elif close_confirm or push_stock_plunge:
                        price_alerts.append(line + ("｜收盤確認窗。" if close_confirm else ""))
                elif code in watchlist_codes and change_pct <= TRACKED_ALERT_PCT:
                    if close_confirm or push_stock_plunge:
                        price_alerts.append(
                            f"🟡 觀測股【{code} {code_to_name[code]}】重挫 {change_pct:.2f}%！"
                            f"(最新價: {current_price:.2f})"
                        )
        except ValueError:
            continue

    stop_alerts = check_stop_level_breaches(
        price_map,
        levels_doc,
        close_confirm=close_confirm,
        live_portfolio_codes=portfolio_codes,
        cleared_codes=cleared_codes,
    ) if price_map else []
    us_indicators = check_us_market_indicators()
    us_alerts = [x["message"] for x in us_indicators if x["is_warning"] and x["message"]]
    rate_info = check_twd_exchange_rate()
    exchange_alerts = [rate_info["message"]] if (rate_info and rate_info["is_warning"]) else []
    asset_alerts, asset_status = check_multi_asset_shocks(rules)
    news_alerts = [] if asset_window else scan_news_headlines(relevant_names)

    macro_level = levels_doc.get("macro_level")
    macro_alerts = []
    if macro_level in (2, 3):
        macro_alerts.append(
            f"大盤濾網目前 Level {macro_level}（個股防守以收盤確認；盤中勿跟外資殺低）"
        )

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("# 🚨 黑天鵝防禦網即時警報 (Black Swan Defense Report)\n\n")
        f.write(f"掃描基準時間：{now.strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(
            "監控對象：加權／匯率／美股夜盤／多資產；"
            "**個股破防守改約 13:10 收盤確認後才推播**  \n"
        )
        f.write(
            "> 分級：盤中只推 **大盤／匯率／反1出清類**；"
            "個股停損／破防守 **不盤中推**，避免賣在阿呆谷。  \n\n"
        )
        if close_confirm:
            f.write("> ⏱ 目前為 **收盤確認窗**：以近收盤價核對防守線。  \n\n")

        f.write("## 📌 當前總經與市場狀態\n\n")
        f.write(f"* **加權指數 (TAIEX)**: **{taiex_close:.2f}** ({taiex_change:+.2f}%)  \n")
        if macro_level:
            f.write(f"* **日報濾網 Level**: **{macro_level}**  \n")
        if rate_info:
            f.write(f"* **新台幣匯率 (USD/TWD)**: **{rate_info['rate']:.4f}** ({rate_info['change_pct']:+.2f}%)  \n")
            if rate_info['is_warning']:
                f.write(f"  > 🚨 **匯率警告**：{rate_info['message']}  \n")
        f.write("\n")

        f.write("## 🇺🇸 美股夜盤先行指標\n\n")
        f.write("| 指標名稱 | 股號 | 最新價格 | 單日漲跌幅 | 狀態警示 |\n")
        f.write("| :--- | :---: | :---: | :---: | :--- |\n")
        for u in us_indicators:
            color = "🔴" if u["change_pct"] >= 1.0 else "🟢" if u["change_pct"] <= -1.0 else "⚪"
            warn_str = "⚠️ 重挫警戒" if u["is_warning"] else "正常"
            f.write(
                f"| {u['name']} | `{u['symbol']}` | {u['price']:,.2f} | "
                f"{color} **{u['change_pct']:+.2f}%** | {warn_str} |\n"
            )
        f.write("\n")

        f.write("## 🌊 多資產波動\n\n")
        f.write("| 名稱 | 代號 | 價格 | 漲跌幅 |\n")
        f.write("| :--- | :---: | :---: | :---: |\n")
        for a in asset_status:
            f.write(
                f"| {a['name']} | `{a['symbol']}` | {a['price']:,.4f} | "
                f"**{a['change_pct']:+.2f}%** |\n"
            )
        f.write("\n")

        f.write("## 📊 持股與觀測個股即時波幅\n\n")
        f.write("| 狀態 | 股號 | 股名 | 昨日收盤 | 最新價格 | 即時漲跌幅 | 狀態警示 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :--- |\n")
        for p in price_status_list:
            color = "🔴" if p["change_pct"] >= 3.0 else "🟢" if p["change_pct"] <= -3.0 else "⚪"
            warn_str = "⚠️ 重挫（僅記錄）" if (
                (p["status"] == "持股" and p["change_pct"] <= PORTFOLIO_ALERT_PCT) or
                (p["status"] == "觀測" and p["change_pct"] <= TRACKED_ALERT_PCT)
            ) else "正常"
            f.write(
                f"| {p['status']} | `{p['code']}` | **{p['name']}** | {p['prev_close']:.2f} | "
                f"{p['close']:.2f} | {color} **{p['change_pct']:+.2f}%** | {warn_str} |\n"
            )

        f.write("\n## 📰 關聯類股與總經重大恐慌新聞\n\n")
        if news_alerts:
            for idx, n in enumerate(news_alerts, 1):
                f.write(f"{idx}. **[{n['title']}]({n['link']})** (來源: {n['source']})  \n")
        else:
            f.write("🟢 目前未偵測到與您持股、觀察股或關聯類股相關的恐慌性重大新聞。  \n")

        f.write("\n## 🔔 警報發送日誌\n\n")
        all_alerts = (
            price_alerts + stop_alerts + us_alerts + exchange_alerts +
            asset_alerts + macro_alerts + [f"【新聞】{x['title']}" for x in news_alerts]
        )
        if all_alerts:
            f.write("### 🚨 本次偵測觸發警報項目：\n\n")
            for alert in all_alerts:
                f.write(f"* {alert}\n")
        else:
            f.write("✅ 本次篩選安全無虞，未觸發任何閾值警報。\n")

    date_compact = now.strftime("%Y%m%d_%H%M%S")
    history_path = os.path.join(WORKSPACE, "reports", "history", f"black_swan_defense_{date_compact}.md")
    shutil.copy(REPORT_PATH, history_path)

    # 推播：盤中＝大盤／匯率／美股／多資產／反1；破防守僅 close_confirm
    push_price = []
    for a in price_alerts:
        if "加權指數" in a or "反1" in a or "出清標的" in a:
            push_price.append(a)
        elif close_confirm:
            push_price.append(a)

    push_stops = [a for a in stop_alerts if close_confirm and "收盤確認破防守" in a]

    emergency_alerts = push_price + push_stops + us_alerts + exchange_alerts + asset_alerts
    if emergency_alerts:
        alert_body = "\n".join(emergency_alerts + [x['title'] for x in news_alerts])
        if close_confirm:
            alert_body = (
                "【收盤確認｜非盤中殺低】\n"
                + alert_body
                + "\n\n執行：13:40後或隔日開盤；開盤09:00-09:30凍結。"
            )
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{now_str}]\n{alert_body}\n" + "=" * 50 + "\n")

        if notify:
            notify(
                title=(
                    f"收盤確認破防守 {now.strftime('%m/%d %H:%M')}"
                    if close_confirm
                    else f"緊急市場警報 {now.strftime('%m/%d %H:%M')}"
                ),
                body=alert_body[:3500],
                symbol="MARKET",
                rule_id="close_confirm_stop" if close_confirm else "black_swan_emergency",
                urgency="emergency",
                force=("--force-notify" in sys.argv),
            )

        if enable_alert_popup:
            trigger_desktop_alert(alert_body)
            print("警報視窗已彈出。")
        else:
            print("警報已記錄／推播（未彈窗）。")
    else:
        print("無推播項目（個股破防守改收盤確認），防禦網報告更新完畢。")


if __name__ == "__main__":
    main()
