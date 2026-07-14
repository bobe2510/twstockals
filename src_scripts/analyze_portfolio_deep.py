import os
import json
import shutil
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "portfolio_and_watchlist.md")

# 投資策略與操作建議 (針對持倉與觀察股的個人對策)
STRATEGIES = {
    "006205": {
        "action": "建議直接出清",
        "one_sentence": "【出清回收】趁目前獲利 {roi:+.2f}% 且陸股長線弱勢，立刻全數出清，回收資金轉投台股。",
        "detail": "目前帳面損益 {roi:+.2f}%。陸股長線動能弱，建議回收這筆資金轉投台股 AI 股或正二，提升整體資金效率。"
    },
    "00631L": {
        "action": "無須停損，拉回加碼",
        "one_sentence": "【長線續抱】無須理會大盤短期整理，若未來指數有回測年線，將反1出清的資金在此處低接加碼。",
        "detail": "台股長線多頭指標。槓桿型 ETF 適合長線持有，若未來大盤大跌回測年線，可將反1出清的資金分批加碼至此。"
    },
    "00632R": {
        "action": "⚠️ 逢彈出清，勿死抱",
        "one_sentence": "【逢彈出清】反1是會天天耗損的『時間毒藥』，趁大盤回檔、反1反彈時立刻果斷割肉變現！",
        "detail": "【反向槓桿陷阱】反1因期貨轉倉成本與每日複利損耗，淨值會天天流失。即使大盤暴跌，也極難回本至 {cost:.2f} 元。建議趁大盤出現短期回檔、反1反彈時，果斷割肉收回資金，轉投高效率資產。"
    },
    "00687B": {
        "action": "無須停損，放著領息",
        "one_sentence": "【放著領息】降息只是時間問題，當作資產避風港，穩收 4.5% 配息並靜待債價反彈。",
        "detail": "長天期美債有穩定配息，且降息只是時間問題，債價有絕對下限。當作資產避風港，靜待降息循環啟動即可。"
    },
    "00752": {
        "action": "逢彈減碼/出清",
        "one_sentence": "【逢彈減碼】目前套牢 {roi:.2f}%，陸股缺乏AI動能，趁政策利多急彈時分批認賠清倉。",
        "detail": "目前虧損約 {roi:.2f}%。陸港股長線趨勢偏弱，建議趁政策利多急彈時分批出清，將資金挪回台美科技股。"
    },
    "00882": {
        "action": "逢彈減碼/出清",
        "one_sentence": "【逢彈減碼】不要攤平，趁陸港股出現利多急彈時減碼出清，將資金收回轉投台股標的。",
        "detail": "目前虧損約 {roi:.2f}%。高股息雖然有配息支持，但陸股大環境較差，建議趁彈升時減碼，轉向台股高股息或市值型標的。"
    },
    "3483": {
        "action": "暫時續抱，靜待輪動",
        "one_sentence": "【暫時續抱】低檔黃金交叉確立，近兩日法人連買且資減，以『年線』為最終防守續抱。",
        "detail": "AI 散熱模組為 3~5 年長線主流題材，基本面未變。目前 {roi:.2f}% 屬電子股正常修正範圍，年線未破前不需砍在低點。"
    },
    "6213": {
        "action": "整張移動停利，拉回再接",
        "one_sentence": "【整張移動停利】以收盤跌破 5MA 作為整張一次賣出訊號，拉回月線再接回。",
        "detail": "目前獲利 {roi:+.2f}%，但短線月線乖離率高達 {bias_20:+.1f}% 嚴重過熱。建議採取『整張移動停利』：以收盤跌破 5MA 作為訊號，一旦跌破則整張一次賣出獲利了結，拉回月線再伺機買回。"
    },
    "6191": {
        "action": "分批加碼，月線防守",
        "one_sentence": "【分批佈局】投信買超力道強勁且資減籌碼沉澱，建議回測 10MA 至月線區間分批承接，收盤跌破月線執行防守。",
        "detail": "【投信鎖籌碼標的】此股為標準內資波段鎖籌碼標的，受外資撤退影響小。目前帳面損益 {roi:+.2f}%，拉回 10MA 至月線區間為加碼安全點。"
    },
    "3706": {
        "action": "防守型分批試單",
        "one_sentence": "【拉回承接】近期均線糾纏，以月線支撐進行試單，收盤破 5日低點停損。",
        "detail": "目前籌碼動能適中。若大盤拉回，於 5MA 至月線 (20MA) 之間可分批建立首批基本持股部位。"
    },
    "3484": {
        "action": "強勢順勢跟車",
        "one_sentence": "【順勢跟車】AI 降規利多，放量站穩所有均線，回踩 5MA 可防守布局。",
        "detail": "本股屬主升段爆發股，法人吃貨比例高。操作上以收盤價守住 5MA 續抱，一旦跌破 5日低點即行移動停利。"
    },
    "5469": {
        "action": "⚠️ 瀕臨破位，反彈減碼",
        "one_sentence": "【反彈減碼】昨日收盤已剛好卡在 5日低點 {low_5d:.2f} 元臨界線。今早開盤後若確認跌破，請利用 10:00 - 11:30 反彈波段逢彈出清或減持，防守兩日不站回法則。",
        "detail": "已建倉 1,000股。股價昨日收盤已壓在 5日低點 {low_5d:.2f} 元。今日為兩日不站回判定的最後關鍵，若今早無法隨大盤反彈站回 10MA ({ma10:.2f} 元) 以上，請於反彈波段執行減量或清倉，切勿隨意攤平。"
    },
    "1308": {
        "action": "拉回缺口分批承接",
        "one_sentence": "【拉回承接】週五爆量長紅突圍，呈價量齊揚噴出態勢，建議拉回跳空缺口 14.60 - 15.00 元分批承接。",
        "detail": "本股為塑膠工業領頭羊，法人 5 日瘋狂吸籌 70.4% 且連買 3 天。由於股價週五收在 15.85 元，乖離偏大，絕不追高，拉回測試缺口下緣（昨高 14.60）至 5MA（約 14.45）附近為極佳的狙擊入場點。"
    },
    "2301": {
        "action": "低乖離防守佈局",
        "one_sentence": "【低乖離承接】日線底部分批吃貨，近月線 {ma20:.2f} 元為極佳主力防守點位。",
        "detail": "作為 AI 伺服器電源龍頭，外資目標價調升至 275 元。目前股價距月線僅 {bias_20:.1f}%（安全低乖離），投信連續 6 天大買，拉回 5MA 附近可分批承接建立部位。"
    },
    "1313": {
        "action": "待拉回 5MA 佈局",
        "one_sentence": "【高乖離警示】塑膠強勢類股，法人大吃貨 173% 且連買 5 天，但乖離高達 13.8%，嚴禁追高。",
        "detail": "塑膠類股動能強勁。聯成短線漲幅已大，週線乖離高，操作上絕不追高。靜待股價拉回測試 5MA（約 12.6）或 10MA 再行低吸布局。"
    },
    "1907": {
        "action": "回踩 5MA 進場",
        "one_sentence": "【突破回測】紙業龍頭整理後帶量突破，法人連買 4 天且吃貨比 126.8%，拉回 5MA 附近承接。",
        "detail": "造紙工業動能佳。永豐餘帶量突破平台，短線乖離 +6.4% 尚屬溫和，建議回測 5MA（約 27.6 元）不破時分批切入，防守設 5 日低點。"
    },
    "1464": {
        "action": "順勢跟車",
        "one_sentence": "【突破跟車】紡織強勢股突破創高，法人連買 3 天，拉回 5MA 附近分批承接。",
        "detail": "紡織纖維類股動能第 4 名。得力股價基期低，短線呈爆量突破多頭排列，可於回踩 5MA 附近分批低接，跌破 10MA 執行停損防守。"
    },
    "2449": {
        "action": "強勢順勢跟車",
        "one_sentence": "【順勢跟車】封測大廠受惠AI需求旺盛，主力資增建倉鎖碼，建議回踩5MA或等待賣壓宣洩後分批承接。",
        "detail": "AI晶片封測需求旺盛，京元電呈現均線多頭且KD黃金交叉。5日法人大買28.6%且融資主力鎖碼。最新收盤335.00元，月線正乖離+8.64%稍微偏大，建議冷靜等待盤中拉回5MA（約331.90元）附近分批試單。"
    },
    "6412": {
        "action": "低乖離分批佈局",
        "one_sentence": "【拉回承接】5日法人大買超50.0%且資減籌碼沉澱，均線多頭排列，回踩5MA可安全布局。",
        "detail": "電供大廠群電籌碼極佳，5日法人大買超佔均量50.0%且融資呈資減沉澱。KD指標於高檔黃金交叉。目前月線乖離率+5.29%，若盤中拉回5MA（約95.46元）附近是相當安全的切入點。"
    }
}

def calculate_sniper_score(r):
    """
    計算狙擊手實戰權重評分：
    Base = p_score - r_score
    InstBonus: 吃貨比 >= 15% 加 15 分，>= 50% 再加 20 分
    StreakBonus: 法人連買天數，每天加 2 分，最多加 10 分
    BiasBonus: 20MA乖離 <= 5% 加 25 分 (安全低乖離)；>= 8% 扣 15 分；>= 12% 扣 40 分
    WashoutFilter: 洗盤過濾器。若 KD 呈死亡交叉，但 5日吃貨比 >= 100% 且 20MA乖離 <= 5%，則額外加 15 分補償 KD 扣分
    """
    if "p_score" not in r or "r_score" not in r:
        return 0.0
    
    base_score = r["p_score"] - r["r_score"]
    inst_ratio = r.get("inst_ratio", 0.0)
    consec_buy = r.get("consecutive_buy", 0)
    bias_20 = r.get("bias_20", 0.0)
    kd_status = r.get("kd_status", "")
    
    # 1. 吃貨比加分
    inst_bonus = 0.0
    if inst_ratio >= 15.0:
        inst_bonus += 15.0
    if inst_ratio >= 50.0:
        inst_bonus += 20.0
        
    # 2. 連買天數加分
    streak_bonus = min(consec_buy, 5) * 2.0
    
    # 3. 乖離率阻擊點位獎懲
    bias_bonus = 0.0
    if bias_20 <= 5.0:
        bias_bonus += 25.0
    elif bias_20 >= 12.0:
        bias_bonus -= 40.0
    elif bias_20 >= 8.0:
        bias_bonus -= 15.0
        
    # 4. 洗盤過濾器 (高積蓄、靠近月線的死亡交叉)
    washout_filter = 0.0
    if "死亡交叉" in kd_status and inst_ratio >= 100.0 and bias_20 <= 5.0:
        washout_filter += 15.0
        
    return base_score + inst_bonus + streak_bonus + bias_bonus + washout_filter

LEVELS_JSON_PATH = os.path.join(WORKSPACE, "reports", "latest", "levels.json")
CP_BEST_JSON_PATH = os.path.join(WORKSPACE, "reports", "latest", "strategy_cp_best.json")
TARGETS_PATH = os.path.join(WORKSPACE, "config", "my_targets.json")


def load_targets_full():
    """Load full my_targets.json (portfolio, watchlist, multi_asset, allocation)."""
    if not os.path.exists(TARGETS_PATH):
        return {
            "portfolio": [],
            "watchlist": [],
            "multi_asset": {},
            "allocation_targets": {},
            "force_exit_codes": [],
        }
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_targets():
    data = load_targets_full()
    return data.get("portfolio", []), data.get("watchlist", [])


def load_cp_best():
    if not os.path.exists(CP_BEST_JSON_PATH):
        return None
    try:
        with open(CP_BEST_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_levels_json(payload):
    os.makedirs(os.path.dirname(LEVELS_JSON_PATH), exist_ok=True)
    with open(LEVELS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def classify_holding_bucket(code, name=""):
    code = str(code)
    if code == "0050":
        return "tw_core_0050"
    if code == "00631L":
        return "tw_lev_00631L"
    if code in ("00687B",) or "債" in name:
        return "bonds"
    if code.startswith("00") and len(code) == 6:
        # other TW ETFs (e.g. 00882 China) count as satellite / exit candidates
        return "tw_stocks"
    if len(code) == 4:
        return "tw_stocks"
    return "other"

def fetch_yahoo_history(sym):
    import urllib.request
    import json
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=365d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            res = data['chart']['result'][0]
            meta = res['meta']
            current_rate = meta['regularMarketPrice']
            prev_close = meta['chartPreviousClose']
            change_pct = ((current_rate - prev_close) / prev_close) * 100
            
            # Parse daily close history
            quotes = res['indicators']['quote'][0]
            closes = [c for c in quotes['close'] if c is not None]
            
            ma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else None
            ma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else None
            
            return {
                "current": current_rate,
                "change_pct": change_pct,
                "ma50": ma50,
                "ma200": ma200
            }
    except Exception as e:
        print(f"警告: Yahoo 歷史數據 {sym} 獲取失敗: {e}")
        return None

def load_taiex_index_data():
    """從歷史 K 線檔案中讀取最新大盤收盤價與計算 20MA、50MA、200MA"""
    try:
        data_dir = os.path.join(WORKSPACE, "market_crawled_cache")
        dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d)) and d.isdigit()]
        if not dirs:
            return None
        latest_folder = sorted(dirs)[-1]
        taiex_path = os.path.join(data_dir, latest_folder, "TAIEX_kline.csv")
        if os.path.exists(taiex_path):
            import pandas as pd
            df = pd.read_csv(taiex_path).sort_values("date").reset_index(drop=True)
            if len(df) >= 20:
                close_val = float(df.iloc[-1]["close"])
                ma20_val = float(df["close"].tail(20).mean())
                ma50_val = float(df["close"].tail(50).mean()) if len(df) >= 50 else None
                ma200_val = float(df["close"].tail(200).mean()) if len(df) >= 200 else None
                return {
                    "close": close_val,
                    "ma20": ma20_val,
                    "ma50": ma50_val,
                    "ma200": ma200_val,
                    "date": df.iloc[-1]["date"]
                }
    except Exception as e:
        print(f"載入大盤資料失敗: {e}")
    return None

def load_black_swan_alerts():
    """從 reports/latest/black_swan_defense.md 中讀取今日最新警報"""
    alerts = []
    path = os.path.join(WORKSPACE, "reports", "latest", "black_swan_defense.md")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if "### 🚨 本次偵測觸發警報項目：" in content:
                parts = content.split("### 🚨 本次偵測觸發警報項目：")
                if len(parts) > 1:
                    lines = parts[1].strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            break
                        if line.startswith("*"):
                            alerts.append(line.replace("*", "").strip())
        except Exception as e:
            print(f"讀取黑天鵝防禦報告失敗: {e}")
    return alerts

def generate_integrated_report(results, today_str):
    """
    從選股器的全市場計算結果中，過濾提取出持倉股與觀察股，
    並生成 portfolio_and_watchlist.md 深度整合診斷報告。
    """
    targets = load_targets_full()
    holdings = targets.get("portfolio", [])
    watchlist = targets.get("watchlist", [])
    multi_asset = targets.get("multi_asset", {})
    allocation_targets = targets.get("allocation_targets", {})
    force_exit_codes = set(targets.get("force_exit_codes", []))
    for h in holdings:
        if h.get("force_exit"):
            force_exit_codes.add(h["code"])

    if not holdings and not watchlist:
        print("未設定持倉或觀察股目標，略過整合報告生成。")
        return

    # 建立 code -> result 的快速查找字典
    results_map = {r["code"]: r for r in results}
    # 台股觀測 vs 美股觀測（美股不進 screener results）
    tw_watchlist = [w for w in watchlist if w.get("market", "TW") != "US"]
    us_watchlist = [w for w in watchlist if w.get("market") == "US"]
    levels_rows = []
    eod_actions = []
    
    # 1. 處理實體持股
    analyzed_holdings = []
    for h in holdings:
        code = h["code"]
        r = results_map.get(code)
        
        if r:
            # 複製算好的指標並新增持有量欄位
            diag = dict(r)
            # 臨時除息價調整 (5469 瀚宇博於 2026-07-09 除息 2.52 元)
            if code == "5469":
                diag["ma5"] = diag.get("ma5", 0.0) - 2.52
                diag["ma10"] = diag.get("ma10", 0.0) - 2.52
                diag["ma20"] = diag.get("ma20", 0.0) - 2.52
                diag["low_5d"] = diag.get("low_5d", 0.0) - 2.52
                r = dict(r)
                r["ma5"] = r.get("ma5", 0.0) - 2.52
                r["ma10"] = r.get("ma10", 0.0) - 2.52
                r["ma20"] = r.get("ma20", 0.0) - 2.52
                r["low_5d"] = r.get("low_5d", 0.0) - 2.52
            diag["shares"] = h["shares"]
            diag["cost"] = h["cost"]
            diag["cost_basis"] = h["shares"] * h["cost"]
            diag["market_value"] = h["shares"] * diag["close"]
            diag["pnl"] = diag["market_value"] - diag["cost_basis"]
            diag["roi"] = (diag["pnl"] / diag["cost_basis"]) * 100 if diag["cost_basis"] else 0.0
            
            # 格式化處置建議
            strat = STRATEGIES.get(code, {"action": "無建議", "one_sentence": "無", "detail": "無"})
            
            # 動態調整個股處置對策 (避免硬編碼過期而發出錯誤的減碼/出清警告)
            if len(code) == 4:
                close_val = diag["close"]
                low_5d_val = diag.get("low_5d", 0.0)
                if low_5d_val > 0 and close_val > low_5d_val:
                    if "減碼" in strat["action"] or "破位" in strat["action"] or "出清" in strat["action"]:
                        strat = {
                            "action": "守住防守，持股續抱",
                            "one_sentence": "【持股續抱】股價收盤 {close:.2f} 元守在防守點 {low_5d:.2f} 元之上，無撞到停損，建議繼續持有防守。",
                            "detail": "目前股價守在 5 日低點 {low_5d:.2f} 元之上，且量化綜合評分穩定，無觸發停損。建議以收盤價跌破 {low_5d:.2f} 元作為最終防守點續抱。"
                        }
            
            try:
                format_args = {
                    "roi": diag.get("roi", 0.0),
                    "bias_20": diag.get("bias_20", 0.0),
                    "cost": diag.get("cost", 0.0),
                    "low_5d": diag.get("low_5d", 0.0),
                    "ma10": diag.get("ma10", 0.0),
                    "ma5": diag.get("ma5", 0.0),
                    "ma20": diag.get("ma20", 0.0),
                    "close": diag.get("close", 0.0)
                }
                diag["one_sentence"] = strat["one_sentence"].format(**format_args)
                diag["detail"] = strat["detail"].format(**format_args)
            except Exception:
                diag["one_sentence"] = strat["one_sentence"]
                diag["detail"] = strat["detail"]
            diag["action"] = strat["action"]
            diag["is_etf"] = len(code) == 6 or code.startswith("00")
            diag["force_exit"] = code in force_exit_codes or bool(h.get("force_exit"))
            diag["bucket"] = classify_holding_bucket(code, h.get("name", ""))
            
            # 使用狙擊手實戰評分
            s_score = calculate_sniper_score(r)
            diag["score_str"] = f"**{s_score:.1f}** 分" if not diag["is_etf"] else "N/A (ETF)"
            
            # 💡 計算持股加碼與防守操作點位
            use_ma5_tp = r.get("ma_alignment") == "多頭排列" or r.get("consecutive_buy", 0) >= 5
            stop_px = r.get("low_5d")
            profit_px = r.get("ma5") if use_ma5_tp else r.get("ma10")
            add_px = None if (diag["is_etf"] and ("出清" in diag["action"] or "減碼" in diag["action"] or diag["force_exit"])) else r.get("ma10")

            if diag["force_exit"] or (diag["is_etf"] and ("出清" in diag["action"] or "減碼" in diag["action"])):
                diag["add_level_10ma"] = "⚠️ 建議減碼/不加碼"
                diag["add_level_20ma"] = "N/A"
                diag["stop_level"] = f"**{stop_px:.2f} 元 (5日低點)**" if stop_px else "N/A"
                diag["profit_level"] = "逢彈出清/減碼"
            else:
                diag["add_level_10ma"] = f"**{r['ma10']:.2f} 元 (10MA) 🌟**" if "ma10" in r else "N/A"
                diag["add_level_20ma"] = f"**{r['ma20']:.2f} 元 (20MA) 🚀**" if "ma20" in r else "N/A"
                diag["stop_level"] = f"**{r['low_5d']:.2f} 元 (5日低點)**" if "low_5d" in r else "N/A"
                
                if use_ma5_tp:
                    diag["profit_level"] = f"收盤價跌破 5MA ({r.get('ma5', 0):.2f} 元) 停利"
                else:
                    diag["profit_level"] = f"收盤價跌破 10MA ({r.get('ma10', 0):.2f} 元) 停利"

            levels_rows.append({
                "code": code,
                "name": diag.get("name", h.get("name", "")),
                "status": "portfolio",
                "force_exit": diag["force_exit"],
                "close": diag.get("close"),
                "stop": stop_px,
                "profit": profit_px,
                "entry": None,
                "add": add_px,
                "ma5": r.get("ma5"),
                "ma10": r.get("ma10"),
                "ma20": r.get("ma20"),
                "low_5d": stop_px,
                "profit_rule": "ma5" if use_ma5_tp else "ma10",
            })
            if diag["force_exit"]:
                eod_actions.append(f"出清窗：{code} {diag.get('name','')} 逢彈分批出清（錯誤策略）")
            elif stop_px and diag["close"] <= stop_px:
                eod_actions.append(f"停損：{code} 收盤 {diag['close']:.2f} ≤ 5日低 {stop_px:.2f}")
            elif profit_px and diag["close"] < profit_px and not diag["force_exit"]:
                eod_actions.append(f"停利檢視：{code} 收盤跌破移動停利 {profit_px:.2f}")
                    
            analyzed_holdings.append(diag)
        else:
            print(f"  ⚠️ 持股 {code} 未出現在全市場行情快取中，略過診斷。")

    # 2. 處理觀察股（僅台股市場）
    analyzed_watchlist = []
    for w in tw_watchlist:
        code = w["code"]
        r = results_map.get(code)
        
        if r:
            diag = dict(r)
            diag["entry_level"] = f"**{r['ma5']:.2f} 元 (5MA) 🌟**" if "ma5" in r else "N/A"
            diag["add_level"] = f"**{r['ma20']:.2f} 元 (20MA) 🚀**" if "ma20" in r else "N/A"
            diag["stop_level"] = f"**{r['low_5d']:.2f} 元 (5日低點)**" if "low_5d" in r else "N/A"
            
            # 動態停利對策
            if r["ma_alignment"] == "多頭排列" or r["ma_alignment"] == "🟢 多頭排列" or r["consecutive_buy"] >= 5:
                diag["profit_level"] = f"收盤價跌破 5MA ({r.get('ma5', 0):.2f} 元) 執行波段停利"
            else:
                diag["profit_level"] = f"收盤價跌破 10MA ({r.get('ma10', 0):.2f} 元) 執行移動停利"
                
            strat = STRATEGIES.get(code, {"action": "防守試單", "one_sentence": "無", "detail": "無"})
            try:
                format_args = {
                    "roi": 0.0,
                    "bias_20": diag.get("bias_20", 0.0),
                    "cost": diag.get("close", 0.0),
                    "low_5d": diag.get("low_5d", 0.0),
                    "ma10": diag.get("ma10", 0.0),
                    "ma5": diag.get("ma5", 0.0),
                    "ma20": diag.get("ma20", 0.0),
                    "close": diag.get("close", 0.0)
                }
                diag["one_sentence"] = strat["one_sentence"].format(**format_args)
                diag["detail"] = strat["detail"].format(**format_args)
            except Exception:
                diag["one_sentence"] = strat["one_sentence"]
                diag["detail"] = strat["detail"]
            diag["action"] = strat["action"]
            diag["is_etf"] = len(code) == 6 or code.startswith("00")
            
            # 使用狙擊手實戰評分
            s_score = calculate_sniper_score(r)
            diag["score_str"] = f"**{s_score:.1f}** 分" if not diag["is_etf"] else "N/A (ETF)"
            levels_rows.append({
                "code": code,
                "name": diag.get("name", w.get("name", "")),
                "status": "watchlist",
                "force_exit": False,
                "close": diag.get("close"),
                "stop": r.get("low_5d"),
                "profit": r.get("ma5") if (r.get("ma_alignment") == "多頭排列" or r.get("consecutive_buy", 0) >= 5) else r.get("ma10"),
                "entry": r.get("ma5"),
                "add": r.get("ma20"),
                "ma5": r.get("ma5"),
                "ma10": r.get("ma10"),
                "ma20": r.get("ma20"),
                "low_5d": r.get("low_5d"),
                "profit_rule": "ma5" if (r.get("ma_alignment") == "多頭排列" or r.get("consecutive_buy", 0) >= 5) else "ma10",
            })
            analyzed_watchlist.append(diag)
        else:
            print(f"  ⚠️ 觀察股 {code} 未出現在全市場行情快取中，略過診斷。")

    # 3. 建立個股黃金優先度排行榜 (綜合已持有與觀測股，排除 ETF)
    priority_list = []
    for r in analyzed_holdings:
        if not r["is_etf"]:
            priority_list.append({
                "code": r["code"],
                "name": r["name"],
                "status": "持有(加碼)",
                "rank_score": calculate_sniper_score(r),
                "bias_20": r["bias_20"],
                "inst_ratio": r["inst_ratio"],
                "consecutive_buy": r["consecutive_buy"],
                "target_level": f"加碼: {r['add_level_10ma']}<br>月線: {r['add_level_20ma']}",
                "stop_level": r["stop_level"],
                "profit_level": r["profit_level"],
                "one_sentence": r["one_sentence"]
            })
            
    for r in analyzed_watchlist:
        if not r["is_etf"]:
            priority_list.append({
                "code": r["code"],
                "name": r["name"],
                "status": "觀測(建倉)",
                "rank_score": calculate_sniper_score(r),
                "bias_20": r["bias_20"],
                "inst_ratio": r["inst_ratio"],
                "consecutive_buy": r["consecutive_buy"],
                "target_level": f"初買: {r['entry_level']}<br>月線: {r['add_level']}",
                "stop_level": r["stop_level"],
                "profit_level": r["profit_level"],
                "one_sentence": r["one_sentence"]
            })
            
    # 去重並依綜合得分 (rank_score) 降序排列
    seen_codes = set()
    unique_priority = []
    for item in priority_list:
        if item["code"] not in seen_codes:
            seen_codes.add(item["code"])
            unique_priority.append(item)
    unique_priority.sort(key=lambda x: x["rank_score"], reverse=True)

    # 4. 大盤加權指數狀態
    latest_date_str = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}"
    taiex_r = load_taiex_index_data()
    taiex_state_msg = ""
    is_preemptive = False
    is_bearish = False
    
    if taiex_r:
        close_val = taiex_r["close"]
        ma20_val = taiex_r.get("ma20", 0.0)
        bias = ((close_val - ma20_val) / ma20_val) * 100 if ma20_val > 0 else 999.0
        
        if close_val <= ma20_val:
            is_bearish = True
            taiex_state_msg = f"> [!WARNING]\n> **⚠️ 【大盤多空濾網 - Level 3 空頭避險區】**大盤收盤價 ({close_val:.2f}) 已跌破月線（20MA: {ma20_val:.2f}，乖離率: {bias:+.2f}%）。系統性風險偏高，建議將整體持股水位降低至 40% 以下，全面暫停波段與突破策略，並避開外資主導標的。"
        elif bias <= 1.5:
            is_preemptive = True
            taiex_state_msg = f"> [!WARNING]\n> **⚠️ 【大盤多空濾網 - Level 2 前置減碼警戒區】**大盤收盤價 ({close_val:.2f}) 雖守在月線之上，但已極度逼近月線邊緣（20MA: {ma20_val:.2f}，偏離率僅 {bias:+.2f}% ≤ 1.5%）。面臨破位崩跌風險，建議啟動**前置防衛對策**：暫停積極開倉與追高；緊縮持有個股之停損至 10MA 或 5 日低點；預防性回收時間毒藥（如反1）及槓桿型/弱勢標的資金，避免等正式破線時蒙受慘重損失。"
        else:
            taiex_state_msg = f"> [!NOTE]\n> **🟢 【大盤多空濾網 - Level 1 多頭安全區】**大盤收盤價 ({close_val:.2f}) 處於月線上方且處於安全偏離區（20MA: {ma20_val:.2f}，偏離率: {bias:+.2f}%）。市場格局偏多，適合積極布局強勢動能與低風險標的。"

    # 5. 寫入 Markdown 報告
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    cp_best = load_cp_best()
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("# 🏆 個人持倉處置與監控報告（見機停損停利）\n\n")
        f.write(f"評估基準日：{latest_date_str}  \n")
        f.write("策略轉向：**不再擴張個股選股池**；以持倉監控、錯誤策略出清、主力倉 EOD 防守為主。  \n")
        f.write("本報告套用 **70%籌碼面 + 30%技術面** 量化規則，並嵌入 CP（高報酬×低上班操作）選優結論。  \n\n")

        if cp_best:
            f.write(
                f"> [!TIP]\n"
                f"> **🏅 目前 CP 最優策略 = {cp_best.get('best_strategy')}**  \n"
                f"> CP **{cp_best.get('best_cp')}**｜CAGR {cp_best.get('best_cagr')}%｜"
                f"MDD {cp_best.get('best_mdd')}%｜年化上班操作 {cp_best.get('best_workday_ops_per_year')} 次  \n"
                f"> 本週預估需手動操作 ≤ **{cp_best.get('weekly_ops_estimate', 0):.2f}** 次"
                f"（詳見 `reports/latest/strategy_cp_ranking.md`）。  \n\n"
            )
        else:
            f.write(
                "> [!NOTE]\n"
                "> 尚未找到 CP 回測結果。請執行 `python src_scripts/run_etf_backtest.py` 產生排名。  \n\n"
            )

        f.write(f"{taiex_state_msg}\n\n")
        
        bs_alerts = load_black_swan_alerts()
        if bs_alerts:
            f.write("> [!WARNING]\n")
            f.write("> **🔥 【台指期夜盤黑天鵝警報與交易執行規範】**\n")
            for alert in bs_alerts:
                f.write(f"> 🚨 {alert}  \n")
            if is_bearish:
                f.write("> **🚨 操作心法 (Level 3 空頭避險區)**：大盤收盤已破月線。請採取**聰明減持**：對於做多部位，明早開盤 **09:00 - 09:30 避開第一波恐慌殺低**，等待 **10:00 - 11:30 反彈波**再行減量至 40% 以下；但對於**反向避險部位（如反1 00632R）**，則應趁開盤恐慌大跌、反向 ETF 價格衝到最高點時**逢高出清變現**。嚴格執行個股收盤停損，切勿隨意低接或攤平外資主導股。\n\n")
            elif is_preemptive:
                f.write("> **🚨 操作心法 (Level 2 前置減碼警戒區)**：大盤極度逼近月線，面臨跌破風險。請嚴禁追高與加碼。波段個股防守點前置縮緊至 10MA 或 5日低點，並於盤中反彈波段預防性變現弱勢/槓桿型部位以保留現金防禦。\n\n")
            else:
                f.write("> **🚨 操作心法 (Level 1 多頭安全區)**：雖有即時黑天鵝警報，但目前大盤仍在多頭安全區。請保持冷靜，開盤半小時內（09:00 - 09:30）嚴禁追高，依收盤判定為準。\n\n")
        else:
            f.write("> [!NOTE]\n")
            f.write("> **🟢 【台指期夜盤黑天鵝監控 - 正常】**\n")
            f.write("> 目前市場無重大異常警報。操作上請遵循大盤多空濾網之規範。\n\n")

        # 錯誤策略出清清單
        force_rows = [x for x in analyzed_holdings if x.get("force_exit")]
        f.write("## ⚠️ 0. 錯誤策略出清清單（優先處理）\n\n")
        if force_rows:
            f.write("| 股號 | 股名 | 報酬率 | 建議 |\n")
            f.write("| :---: | :--- | :---: | :--- |\n")
            for r in force_rows:
                f.write(
                    f"| `{r['code']}` | **{r['name']}** | **{r['roi']:+.2f}%** | "
                    f"逢彈分批出清，資金轉 0050／正2／避險資產 |\n"
                )
            f.write("\n")
        else:
            f.write("目前無標記 `force_exit` 的持股。  \n\n")

        f.write("## 📋 本週／收盤後執行清單（建議 13:40 後或隔日開盤）\n\n")
        if eod_actions:
            for a in eod_actions:
                f.write(f"* {a}\n")
            f.write("\n")
        else:
            f.write("* 無強制收盤動作；維持監控與 Level 濾網規範。  \n\n")
        
        # 寫入黃金優先度排行榜（個股殘倉：只減不擴語境）
        f.write("## 🎯 1. 持倉處置優先度（個股殘倉：見機停損停利，不再擴張）\n\n")
        f.write("| 優先順序 | 股號 | 股名 | 狀態屬性 | 狙擊權重分 | 20MA乖離 | 5日吃貨比 | 法人連買天數 | 🎯 狙擊手進場/加碼點位 | 🛡️ 停損守備點 | 📋 行動/移動停利對策 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- | :--- |\n")
        
        for idx, item in enumerate(unique_priority, 1):
            f.write(f"| **{idx}** | `{item['code']}` | **{item['name']}** | {item['status']} | **{item['rank_score']:.1f}** | {item['bias_20']:+.1f}% | {item['inst_ratio']:.1f}% | {item['consecutive_buy']}天 | {item['target_level']} | {item['stop_level']} | {item['profit_level']} |\n")
        f.write("\n\n")
        
        # 寫入實體持股部位與帳務總覽
        f.write("## 📊 2. 個人實體持股部位與帳務總覽\n\n")
        total_cost = sum(x["cost_basis"] for x in analyzed_holdings)
        total_value = sum(x["market_value"] for x in analyzed_holdings)
        total_pnl = total_value - total_cost
        total_roi = (total_pnl / total_cost) * 100 if total_cost else 0.0
        
        f.write(f"* **資產總投入成本**: **{total_cost:,.0f}** 元\n")
        f.write(f"* **當前資產總市值**: **{total_value:,.0f}** 元\n")
        pnl_color = "🔴" if total_pnl >= 0 else "🟢"  # 台灣股市紅色為正值，綠色為負值
        f.write(f"* **累積未實現損益**: {pnl_color} **{total_pnl:+,.0f}** 元\n")
        f.write(f"* **整體資產報酬率 (ROI)**: **{total_roi:+.2f}%**\n\n")

        # 配置 vs 目標
        f.write("### 📐 多資產配置 vs 目標（缺數字顯示待補）\n\n")
        bucket_value = {
            "tw_core_0050": 0.0,
            "tw_lev_00631L": 0.0,
            "tw_stocks": 0.0,
            "bonds": 0.0,
            "gold_fx": 0.0,
            "us_etf": 0.0,
            "crypto": 0.0,
        }
        for r in analyzed_holdings:
            b = r.get("bucket", "tw_stocks")
            if b in bucket_value:
                bucket_value[b] += r["market_value"]
            else:
                bucket_value["tw_stocks"] += r["market_value"]

        # multi_asset mark-to-market when qty present
        gold_pb = multi_asset.get("gold_passbook") or {}
        forex = multi_asset.get("forex_usd") or {}
        cryptos = multi_asset.get("crypto") or []
        gold_res_tmp = fetch_yahoo_history("GC=F")
        usdtwd_tmp = fetch_yahoo_history("USDTWD=X")
        multi_notes = []
        if gold_pb.get("qty") and gold_res_tmp and usdtwd_tmp:
            g_px = (gold_res_tmp["current"] * usdtwd_tmp["current"]) / 31.1034768
            gv = float(gold_pb["qty"]) * g_px
            bucket_value["gold_fx"] += gv
            multi_notes.append(f"黃金存摺約 {gv:,.0f} 元（{gold_pb['qty']}g）")
        else:
            multi_notes.append("黃金存摺：數量待填")
        if forex.get("qty") and usdtwd_tmp:
            fv = float(forex["qty"]) * usdtwd_tmp["current"]
            bucket_value["gold_fx"] += fv
            multi_notes.append(f"外匯 USD 約 {fv:,.0f} 元（{forex['qty']} USD）")
        else:
            multi_notes.append("外匯存摺：數量待填")
        for c in cryptos:
            sym = c.get("symbol")
            if c.get("qty") and sym:
                cres = fetch_yahoo_history(sym)
                if cres and usdtwd_tmp:
                    cv = float(c["qty"]) * cres["current"] * usdtwd_tmp["current"]
                    bucket_value["crypto"] += cv
                    multi_notes.append(f"{sym} 約 {cv:,.0f} 元")
                else:
                    multi_notes.append(f"{sym}：報價失敗")
            else:
                multi_notes.append(f"{c.get('symbol','crypto')}：數量待填")
        for u in (multi_asset.get("us_etf") or []) + us_watchlist:
            # held us_etf with qty would be in multi_asset.us_etf; watchlist only observe
            pass

        denom = total_value + bucket_value["gold_fx"] + bucket_value["crypto"] + bucket_value["us_etf"]
        if denom <= 0:
            denom = 1.0
        label_map = {
            "tw_core_0050": "台股底倉 0050",
            "tw_lev_00631L": "台股進攻 正2",
            "tw_stocks": "個股／其他台股ETF",
            "bonds": "債券／美債ETF",
            "gold_fx": "黃金＋外匯",
            "us_etf": "美股ETF",
            "crypto": "加密貨幣",
        }
        f.write("| 資產桶 | 目前市值 | 目前占比 | 目標占比 | 差距 |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: |\n")
        for key, label in label_map.items():
            cur_v = bucket_value.get(key, 0.0)
            cur_pct = cur_v / denom
            tgt = float(allocation_targets.get(key, 0.0) or 0.0)
            gap = cur_pct - tgt
            cur_disp = f"{cur_v:,.0f}" if cur_v > 0 else "待補倉／待填數量"
            f.write(
                f"| {label} | {cur_disp} | {cur_pct*100:.1f}% | {tgt*100:.0f}% | {gap*100:+.1f}pp |\n"
            )
        f.write("\n")
        for note in multi_notes:
            f.write(f"* {note}\n")
        f.write("\n")
        
        f.write("### 📋 實體持股與帳務總覽表\n\n")
        f.write("| 股號 | 股名 | 持有股數 | 投入成本 | 最新收盤 | 🛡️ 停損守備價 | 📈 動態停利點 (5MA) | 帳面損益 | 報酬率 | 外資持股 | 均線排列 | KD指標 | 資金主導屬性 |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        
        for r in analyzed_holdings:
            pnl_str = f"+{r['pnl']:,.0f}" if r['pnl'] >= 0 else f"{r['pnl']:,.0f}"
            roi_str = f"+{r['roi']:.2f}%" if r['roi'] >= 0 else f"{r['roi']:.2f}%"
            cap_type = "🚨 外資主導" if r["foreign_ratio"] >= 40.0 else "✅ 內資主導" if r["foreign_ratio"] <= 15.0 else "中等"
            sl_val = f"{r['low_5d']:.2f}" if "low_5d" in r else "-"
            tp_val = f"{r['ma5']:.2f}" if "ma5" in r else "-"
            name_flag = f"**{r['name']}**" + (" ⚠️出清" if r.get("force_exit") else "")
            f.write(f"| `{r['code']}` | {name_flag} | {r['shares']:,} | {r['cost_basis']:,.0f} | {r['close']:.2f} | **{sl_val}** | **{tp_val}** | **{pnl_str}** | **{roi_str}** | {r['foreign_ratio']:.2f}% | {r['ma_alignment']} | {r['kd_status']} | {cap_type} |\n")
            
        f.write("\n\n## 🔍 3. 個股詳細診斷與處置對策 (持股 + 觀測股)\n\n")
        
        # 寫入實體持股詳細診斷
        f.write("### 📂 [已建倉部位] 詳細診斷\n\n")
        for idx, r in enumerate(analyzed_holdings, 1):
            f.write(f"#### {idx}. `{r['code']}` {r['name']} (帳面損益: **{r['roi']:+.2f}%**)\n")
            f.write(f"> **💡 關鍵操作：{r['one_sentence']}**  \n\n")
            
            if r["foreign_ratio"] >= 40.0:
                f.write("> [!IMPORTANT]\n")
                f.write(f"> **資金主導屬性：🚨 外資主導型個股 (外資持股 {r['foreign_ratio']:.2f}%)**  \n")
                f.write("> 本股極易受到新台幣匯率波動影響。切忌高乖離追高，跌破月線且外資連賣需果斷出場。\n\n")
            elif r["foreign_ratio"] <= 15.0:
                f.write("> [!NOTE]\n")
                f.write(f"> **資金主導屬性：✅ 內資主導型標的 (外資持股 {r['foreign_ratio']:.2f}%)**  \n")
                f.write("> 籌碼主要由投信或主力控制，對外資的撤資有極強的免疫力。走勢通常較具獨立性，適合波段布局。\n\n")
                
            f.write(f"* **最新收盤**: {r['close']:.2f} 元 | **20MA 乖離率**: **{r['bias_20']:+.2f}%**\n")
            f.write(f"* **技術指標**: {r['ma_alignment']} / {r['kd_status']}\n")
            if not r["is_etf"]:
                f.write(f"* **籌碼指標**: 5日法人買超 **{r['inst_buy_5d']:.0f}** 張 / 連續買超 **{r['consecutive_buy']}** 天 / 5日融資變動 **{r['margin_diff_5d']:.0f}** 張\n")
                f.write(f"* **量化綜合評分**: {r['score_str']}\n")
            f.write(f"* **處置解析**: {r['detail']}\n\n")
            f.write("--- \n\n")
            
        # 寫入觀察股詳細診斷
        f.write("### 📂 [觀測追蹤部位] 詳細診斷\n\n")
        for idx, r in enumerate(analyzed_watchlist, 1):
            f.write(f"#### {idx}. `{r['code']}` {r['name']} (目前觀測中)\n")
            f.write(f"> **💡 關鍵操作：{r['one_sentence']}**  \n\n")
            
            if r["foreign_ratio"] >= 40.0:
                f.write("> [!IMPORTANT]\n")
                f.write(f"> **資金主導屬性：🚨 外資主導型個股 (外資持股 {r['foreign_ratio']:.2f}%)**  \n")
                f.write("> 外資持股高，若大盤不穩宜保守跟車。\n\n")
            elif r["foreign_ratio"] <= 15.0:
                f.write("> [!NOTE]\n")
                f.write(f"> **資金主導屬性：✅ 內資主導型標的 (外資持股 {r['foreign_ratio']:.2f}%)**  \n")
                f.write("> 內資投信大買，籌碼面極佳。\n\n")
                
            f.write(f"* **最新收盤**: {r['close']:.2f} 元 | **20MA 乖離率**: **{r['bias_20']:+.2f}%** | **5MA 乖離**: **{r['bias_5']:+.2f}%**\n")
            f.write(f"* **量化綜合評分**: {r['score_str']}\n")
            f.write(f"* **點位策略**: 初次進場 {r['entry_level']} / 主力加碼 {r['add_level']} / 停損點 {r['stop_level']}\n")
            f.write(f"* **處置解析**: {r['detail']}\n\n")
            f.write("--- \n\n")

        if us_watchlist:
            f.write("### 📂 [美股 ETF 觀測]（IB）\n\n")
            for w in us_watchlist:
                sym = w["code"]
                y = fetch_yahoo_history(sym)
                if y:
                    ma50_s = f"{y['ma50']:.2f}" if y.get("ma50") else "N/A"
                    ma200_s = f"{y['ma200']:.2f}" if y.get("ma200") else "N/A"
                    f.write(
                        f"* **{sym} {w.get('name','')}**: {y['current']:.2f} USD "
                        f"({y['change_pct']:+.2f}%)｜50MA {ma50_s}｜200MA {ma200_s}  \n"
                    )
                    levels_rows.append({
                        "code": sym,
                        "name": w.get("name", sym),
                        "status": "watchlist_us",
                        "force_exit": False,
                        "close": y["current"],
                        "stop": None,
                        "profit": None,
                        "entry": y.get("ma50"),
                        "add": y.get("ma200"),
                        "ma5": None,
                        "ma10": None,
                        "ma20": None,
                        "low_5d": None,
                        "profit_rule": "us_etf",
                        "currency": "USD",
                    })
                else:
                    f.write(f"* **{sym}**：Yahoo 報價失敗  \n")
            f.write("\n")
            
        # 4. 核心資產 ETF 擇時與資金配置指南 (ETF Trend Timing)
        if taiex_r:
            close_val = taiex_r["close"]
            ma50_val = taiex_r.get("ma50")
            ma200_val = taiex_r.get("ma200")
            
            ma50_val_str = f"**{ma50_val:.2f} 點**" if ma50_val else "N/A"
            ma200_val_str = f"**{ma200_val:.2f} 點**" if ma200_val else "N/A"
            
            bias_50_str = f"偏離率: {((close_val - ma50_val) / ma50_val) * 100:+.2f}%" if ma50_val else "N/A"
            bias_200_str = f"偏離率: {((close_val - ma200_val) / ma200_val) * 100:+.2f}%" if ma200_val else "N/A"
            
            taiex_50ma_signal = "🟢 【50MA 季線擇時：多頭持有】" if ma50_val and close_val > ma50_val else "🔴 【50MA 季線擇時：空頭空倉】"
            taiex_200ma_signal = "🟢 【200MA 年線擇時：多頭持有】" if ma200_val and close_val > ma200_val else "🔴 【200MA 年線擇時：空頭空倉】"
            
            if ma200_val and close_val > ma200_val:
                lev_advice = "大盤守穩年線之上，0050正2處於多頭獲利期。建議維持 CP 最優之年線擇時／0050+正2 混合骨架，分批建立長線多頭部位。"
                reverse_advice = "大盤處於多頭，反1（00632R）是會天天流失時間價值的毒藥。建議趁大盤回檔、反1出現短線反彈時，果斷逢高分批出清變現。"
                core_0050_advice = "0050 作為非槓桿壓艙底倉，可持續分批建立／再平衡至目標占比。"
            else:
                lev_advice = "大盤已跌破年線，0050正2進入空頭修正期。為避免雙倍槓桿在空頭盤整中被波動耗損嚴重侵蝕，強烈建議空倉（持現金避險），待收盤重回年線之上再行建立。"
                reverse_advice = "大盤處於空頭，反1可作為短線避險，但因為每日期貨轉倉成本和槓桿耗損，仍不宜死抱。建議待大盤隨波段震盪暴跌、反1衝高時逢高套現出清。"
                core_0050_advice = "年線空頭期優先保留現金與 0050 防禦底倉，暫停正2 加碼。"
                
            bond_advice = "降息長線趨勢不變，作為高殖利率與防禦性資產，建議在年線之下大盤弱勢時，作為安全資金避風港放著領息，穩健續抱。"
            
            f.write("\n## ⚖️ 4. 核心資產 ETF 擇時與資金配置指南 (ETF Trend Timing)\n\n")
            f.write("本指南套用 **200MA (年線) 與 50MA (季線) 擇時規章**，並以 CP 值選優結果作為主力倉依據：\n\n")
            f.write(f"* **大盤最新收盤**: **{close_val:.2f}** 點\n")
            f.write(f"* **大盤季線 (50MA)**: {ma50_val_str} ({bias_50_str}) | **擇時訊號**: {taiex_50ma_signal}\n")
            f.write(f"* **大盤年線 (200MA)**: {ma200_val_str} ({bias_200_str}) | **擇時訊號**: {taiex_200ma_signal}\n\n")
            f.write("### 💡 資金配置與操作建議：\n")
            f.write(f"* **0050**: {core_0050_advice}\n")
            f.write(f"* **0050正2 (00631L)**: {lev_advice}\n")
            f.write(f"* **00632R 反1**: {reverse_advice}\n")
            f.write(f"* **國泰20年美債 (00687B)**: {bond_advice}\n\n")

            # timing flip hint into eod_actions / levels meta
            if ma200_val:
                levels_rows.append({
                    "code": "TAIEX",
                    "name": "加權指數",
                    "status": "macro",
                    "force_exit": False,
                    "close": close_val,
                    "stop": ma20_val if taiex_r else None,
                    "profit": None,
                    "entry": None,
                    "add": None,
                    "ma5": None,
                    "ma10": None,
                    "ma20": taiex_r.get("ma20"),
                    "ma50": ma50_val,
                    "ma200": ma200_val,
                    "low_5d": None,
                    "profit_rule": "timing_200ma",
                    "above_200ma": bool(close_val > ma200_val),
                })
            
        # 5. 總體經濟與避險商品追蹤看板 (Macro & Safe Havens)
        gold_res = gold_res_tmp or fetch_yahoo_history("GC=F")
        usdtwd_res = usdtwd_tmp or fetch_yahoo_history("USDTWD=X")
        btc_res = fetch_yahoo_history("BTC-USD")
        eth_res = fetch_yahoo_history("ETH-USD")
        
        if gold_res and usdtwd_res:
            gold_price = gold_res["current"]
            gold_change = gold_res["change_pct"]
            gold_ma50 = gold_res["ma50"]
            gold_ma200 = gold_res["ma200"]
            
            usdtwd = usdtwd_res["current"]
            usdtwd_change = usdtwd_res["change_pct"]
            usdtwd_ma50 = usdtwd_res["ma50"]
            usdtwd_ma200 = usdtwd_res["ma200"]
            
            bot_gold = (gold_price * usdtwd) / 31.1034768
            bot_gold_ma50 = (gold_ma50 * usdtwd) / 31.1034768 if gold_ma50 else None
            bot_gold_ma200 = (gold_ma200 * usdtwd) / 31.1034768 if gold_ma200 else None
            
            f.write("## 🪙 5. 總體經濟與避險／衛星商品追蹤看板\n\n")
            f.write("本看板追蹤黃金存摺、外匯、加密與美股觀測，作為分批配置依據（禁止日內追價）：\n\n")
            
            gold_color = "🔴" if gold_change >= 0 else "🟢"
            usdtwd_color = "🔴" if usdtwd_change >= 0 else "🟢"
            
            f.write(f"* **國際黃金現貨 (GC=F)**: **{gold_price:.2f}** 美元/盎司 | 今日漲跌: {gold_color} **{gold_change:+.2f}%**\n")
            f.write(f"  * 50MA (季線支撐): **{gold_ma50:.2f}** 美元 ({((gold_price-gold_ma50)/gold_ma50)*100:+.2f}%)\n" if gold_ma50 else "")
            f.write(f"  * 200MA (年線大支撐): **{gold_ma200:.2f}** 美元 ({((gold_price-gold_ma200)/gold_ma200)*100:+.2f}%)\n" if gold_ma200 else "")
            
            f.write(f"* **美元兌新台幣 (USDTWD=X)**: **{usdtwd:.4f}** 元 | 今日漲跌: {usdtwd_color} **{usdtwd_change:+.2f}%**\n")
            f.write(f"  * 50MA (季均價): **{usdtwd_ma50:.4f}** 元\n" if usdtwd_ma50 else "")
            f.write(f"  * 200MA (年均價): **{usdtwd_ma200:.4f}** 元\n" if usdtwd_ma200 else "")
            
            f.write(f"* **臺灣銀行黃金存摺預估價格**: **{bot_gold:.2f}** 元/公克  \n")
            if gold_pb.get("qty"):
                f.write(f"  * 持有約 **{gold_pb['qty']}** 公克｜市值約 **{float(gold_pb['qty']) * bot_gold:,.0f}** 元\n")
            else:
                f.write("  * 持有數量：待填（`multi_asset.gold_passbook.qty`）\n")
            f.write(f"  * 🎯 **黃金初次進場點 (季線換算價)**: **{bot_gold_ma50:.2f}** 元/公克\n" if bot_gold_ma50 else "")
            f.write(f"  * 🚀 **黃金主力防禦點 (年線換算價)**: **{bot_gold_ma200:.2f}** 元/公克\n" if bot_gold_ma200 else "")
            f.write("\n")

            if btc_res:
                f.write(f"* **Bitcoin (BTC-USD)**: **{btc_res['current']:,.2f}** USD ({btc_res['change_pct']:+.2f}%)\n")
            if eth_res:
                f.write(f"* **Ethereum (ETH-USD)**: **{eth_res['current']:,.2f}** USD ({eth_res['change_pct']:+.2f}%)\n")
            f.write("\n")
            
            f.write("### 💡 最佳佈局區間與策略指南：\n")
            
            usd_advice_price = usdtwd_ma200 if usdtwd_ma200 else 30.50
            f.write(f"* **美金最佳買點 (弱勢美元期低接)**：目前美元匯率 ({usdtwd:.4f})。**建倉甜甜價為 {usd_advice_price:.2f} 元以下**（年均線下方）。\n")
            
            gold_advice_price = bot_gold_ma50 if bot_gold_ma50 else bot_gold * 0.95
            f.write(f"* **黃金存摺最佳買點**：以**{gold_advice_price:.2f} 元/公克 以下**（季線拉回區）分批；年線換算價為終極加碼區。\n")
            f.write("* **加密貨幣**：衛星倉硬上限建議 ≤5%；採週線／50·200MA 拉回，禁止日內追價。\n")
            f.write("* **美股 ETF（VOO/QQQ）**：可於晚間 IB 下單，不佔平日上班時間；小額試倉對齊目標配置。\n\n")

            levels_rows.append({
                "code": "GC=F",
                "name": "黃金",
                "status": "multi_asset",
                "close": gold_price,
                "entry": gold_ma50,
                "add": gold_ma200,
                "change_pct": gold_change,
            })
            levels_rows.append({
                "code": "USDTWD=X",
                "name": "美元兌台幣",
                "status": "multi_asset",
                "close": usdtwd,
                "entry": usdtwd_ma200,
                "change_pct": usdtwd_change,
            })
            if btc_res:
                levels_rows.append({
                    "code": "BTC-USD",
                    "name": "Bitcoin",
                    "status": "multi_asset",
                    "close": btc_res["current"],
                    "change_pct": btc_res["change_pct"],
                    "entry": btc_res.get("ma50"),
                    "add": btc_res.get("ma200"),
                })
            if eth_res:
                levels_rows.append({
                    "code": "ETH-USD",
                    "name": "Ethereum",
                    "status": "multi_asset",
                    "close": eth_res["current"],
                    "change_pct": eth_res["change_pct"],
                    "entry": eth_res.get("ma50"),
                    "add": eth_res.get("ma200"),
                })
            
    # Write levels.json for intraday / EOD scanners
    macro_level = 3 if is_bearish else (2 if is_preemptive else 1)
    write_levels_json({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": latest_date_str,
        "macro_level": macro_level,
        "force_exit_codes": sorted(list(force_exit_codes)),
        "eod_actions": eod_actions,
        "cp_best_strategy": (cp_best or {}).get("best_strategy"),
        "levels": levels_rows,
    })
            
    # 複製一份到 reports/history/ 作為備份
    date_compact = today_str
    history_path = os.path.join(WORKSPACE, "reports", "history", f"portfolio_and_watchlist_{date_compact}.md")
    shutil.copy(REPORT_PATH, history_path)
    print(f"深度診斷與觀測整合報告已生成！")
    print(f"levels.json 已寫入: {LEVELS_JSON_PATH}")

def main():
    # 獨立執行 standalone 模式：載入快取大檔並呼叫選股器邏輯獲取 results
    import market_screener as ms
    dates = ms.get_latest_trading_dates(90)
    profiles = ms.load_company_profiles()
    
    # 載入資料 (但不輸出選股排行 MD，僅在記憶體中運算結果)
    print("獨立執行模式下：加載大檔快取中...")
    results = ms.run_screener(dates, profiles, write_reports=False)
    
    today_str = dates[-1].replace("-", "")
    generate_integrated_report(results, today_str)

if __name__ == "__main__":
    main()
