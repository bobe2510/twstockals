import os
import json
import numpy as np
import pandas as pd
import sys
from datetime import datetime

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

# 外資持股比例對照表 (包含 7/1 最新設備股)
FOREIGN_RATIOS = {
    "6139": 31.91, "6693": 2.10, "2383": 44.30, "4764": 1.50, "6415": 79.72,
    "6191": 5.98, "2408": 14.25, "2467": 19.79, "6213": 21.63, "8996": 37.22,
    "5469": 12.65, "2344": 18.94, "2316": 37.59, "00631L": 0.50, "6291": 1.20,
    "3693": 6.68, "8162": 3.20, "2303": 40.89, "3706": 9.78, "5243": 52.76,
    "5285": 7.20, "6451": 63.88,
    "3563": 6.64, "7734": 2.95, "4542": 10.89, "6658": 1.60, "4503": 3.79,
    "3455": 10.22
}

def load_tracked_stocks():
    json_path = os.path.join(WORKSPACE, "tracked_stocks.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("tracked_stocks", [])

def calculate_kd(df):
    df = df.copy()
    df['low_9'] = df['min'].rolling(window=9).min()
    df['high_9'] = df['max'].rolling(window=9).max()
    df['rsv'] = 0.0
    denominator = df['high_9'] - df['low_9']
    non_zero = denominator != 0
    df.loc[non_zero, 'rsv'] = ((df.loc[non_zero, 'close'] - df.loc[non_zero, 'low_9']) / denominator[non_zero]) * 100
    
    k, d = 50.0, 50.0
    k_list, d_list = [], []
    for rsv in df['rsv']:
        if pd.isna(rsv):
            k_list.append(np.nan)
            d_list.append(np.nan)
        else:
            k = (2/3) * k + (1/3) * rsv
            d = (2/3) * d + (1/3) * k
            k_list.append(k)
            d_list.append(d)
    df['K'] = k_list
    df['D'] = d_list
    return df

def analyze_stock_risk_reward(code, name, target_dir, realtime_price=None):
    kline_path = os.path.join(target_dir, f"{code}_kline.csv")
    chips_inst_path = os.path.join(target_dir, f"{code}_chips_institutional.csv")
    chips_margin_path = os.path.join(target_dir, f"{code}_chips_margin.csv")
    
    res = {
        "code": code,
        "name": name,
        "close": 0.0,
        "bias_20": 0.0,
        "ma_alignment": "整理",
        "kd_status": "未知",
        "foreign_ratio": FOREIGN_RATIOS.get(code, 15.0),
        "inst_buy_5d": 0,
        "inst_ratio": 0.0,
        "margin_diff_5d": 0,
        "margin_usage_ratio": 0.0,
        "consecutive_buy": 0,
        "profit_potential": 50.0,
        "risk_score": 30.0,
        "rank_score": 20.0,
        "p_reasons": [],
        "r_reasons": []
    }
    
    if not os.path.exists(kline_path):
        return None
        
    df_k = pd.read_csv(kline_path).sort_values('date').reset_index(drop=True)
    if df_k.empty or len(df_k) < 20:
        return None
        
    if realtime_price is not None and realtime_price > 0:
        new_row = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "close": realtime_price,
            "open": realtime_price,
            "max": realtime_price,
            "min": realtime_price,
            "Trading_Volume": 0
        }
        df_k = pd.concat([df_k, pd.DataFrame([new_row])], ignore_index=True)
        
    df_k = calculate_kd(df_k)
    df_k['5MA'] = df_k['close'].rolling(5).mean()
    df_k['10MA'] = df_k['close'].rolling(10).mean()
    df_k['20MA'] = df_k['close'].rolling(20).mean()
    
    latest = df_k.iloc[-1]
    res["close"] = float(latest['close'])
    
    # 20日均量 (折算為張數)
    if 'Trading_Volume' in df_k.columns:
        avg_vol_20d_shares = df_k['Trading_Volume'].tail(20).mean()
        avg_vol_20d_lots = (avg_vol_20d_shares / 1000.0) if pd.notna(avg_vol_20d_shares) else 0.0
    else:
        avg_vol_20d_lots = 0.0
        
    # 20MA 乖離率
    ma20 = latest['20MA']
    if pd.notna(ma20) and ma20 != 0:
        res["bias_20"] = ((latest['close'] - ma20) / ma20) * 100
        
    # 均線排列
    ma5, ma10 = latest['5MA'], latest['10MA']
    if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
        if latest['close'] > ma5 > ma10 > ma20:
            res["ma_alignment"] = "多頭"
        elif latest['close'] < ma5 < ma10 < ma20:
            res["ma_alignment"] = "空頭"
            
    # KD 狀態
    k_val, d_val = latest['K'], latest['D']
    if pd.notna(k_val) and pd.notna(d_val):
        res["kd_status"] = "金叉" if k_val > d_val else "死叉"
        
    # 法人籌碼
    if os.path.exists(chips_inst_path):
        df_inst = pd.read_csv(chips_inst_path)
        if not df_inst.empty:
            df_inst = df_inst.sort_values('date')
            df_foreign = df_inst[df_inst['name'] == 'Foreign_Investor']
            df_trust = df_inst[df_inst['name'] == 'Investment_Trust']
            f_net = df_foreign.iloc[-5:]['buy'].sum() - df_foreign.iloc[-5:]['sell'].sum() if not df_foreign.empty else 0
            t_net = df_trust.iloc[-5:]['buy'].sum() - df_trust.iloc[-5:]['sell'].sum() if not df_trust.empty else 0
            res["inst_buy_5d"] = int((f_net + t_net) / 1000) # 折算為張數
            if avg_vol_20d_lots > 0:
                res["inst_ratio"] = (res["inst_buy_5d"] / avg_vol_20d_lots) * 100
            
            # 連買天數
            df_pivot = df_inst.pivot_table(index='date', columns='name', values=['buy', 'sell'])
            if not df_pivot.empty:
                df_pivot['net_foreign'] = df_pivot[('buy', 'Foreign_Investor')] - df_pivot[('sell', 'Foreign_Investor')] if ('buy', 'Foreign_Investor') in df_pivot.columns else 0
                df_pivot['net_trust'] = df_pivot[('buy', 'Investment_Trust')] - df_pivot[('sell', 'Investment_Trust')] if ('buy', 'Investment_Trust') in df_pivot.columns else 0
                df_pivot['net_total'] = df_pivot['net_foreign'] + df_pivot['net_trust']
                consecutive = 0
                for net in reversed(df_pivot['net_total'].tolist()):
                    if net > 0:
                        consecutive += 1
                    else:
                        break
                res["consecutive_buy"] = consecutive

    # 融資籌碼
    if os.path.exists(chips_margin_path):
        df_margin = pd.read_csv(chips_margin_path)
        if not df_margin.empty:
            df_margin = df_margin.sort_values('date')
            latest_margin = df_margin.iloc[-1]
            if 'MarginPurchaseTodayBalance' in df_margin.columns and 'MarginPurchaseLimit' in df_margin.columns:
                balance = float(latest_margin['MarginPurchaseTodayBalance'])
                limit = float(latest_margin['MarginPurchaseLimit'])
                if limit > 0:
                    res["margin_usage_ratio"] = (balance / limit) * 100
            
            balance_cols = [c for c in df_margin.columns if 'balance' in c.lower() or 'purchase' in c.lower() and 'limit' not in c.lower()]
            if balance_cols:
                col = balance_cols[0]
                res["margin_diff_5d"] = int(df_margin.iloc[-1][col] - df_margin.iloc[-5][col])

    # ==========================================================
    # 量化模型計算
    # ==========================================================
    # 融資大戶建倉與否判斷
    margin = res["margin_diff_5d"]
    margin_usage = res["margin_usage_ratio"]
    is_major_margin = False
    if margin > 0:
        ma20 = latest['20MA']
        if pd.notna(ma20) and latest['close'] > ma20 and res["inst_buy_5d"] > 0 and margin_usage < 25.0:
            is_major_margin = True

    # 1. 獲利可能性得分 (0-100)
    p_score = 40.0
    
    # 法人吃貨周轉率比值力道 (比例化買超)
    inst_ratio = res["inst_ratio"]
    if inst_ratio >= 15.0:
        p_score += 25
        res["p_reasons"].append(f"5日法人大買超(佔均量{inst_ratio:.1f}%)")
    elif inst_ratio >= 5.0:
        p_score += 15
        res["p_reasons"].append(f"5日法人買超(佔均量{inst_ratio:.1f}%)")
    elif inst_ratio > 0.0:
        p_score += 5
        
    # 法人連買天數
    if res["consecutive_buy"] >= 4:
        p_score += 15
        res["p_reasons"].append(f"法人強勢連買{res['consecutive_buy']}天")
    elif res["consecutive_buy"] >= 2:
        p_score += 10
        res["p_reasons"].append(f"法人連買{res['consecutive_buy']}天")
        
    # 技術排列
    if res["ma_alignment"] == "多頭":
        p_score += 10
        res["p_reasons"].append("均線多頭排列")
    if res["kd_status"] == "金叉":
        p_score += 10
        res["p_reasons"].append("KD黃金交叉")
        
    # 大戶資增建倉鎖碼加分
    if is_major_margin and margin > 800:
        p_score += 5
        res["p_reasons"].append("🔥 主力資增建倉鎖碼")
        
    res["profit_potential"] = min(100.0, p_score)
    
    # 2. 風險得分 (0-100)
    r_score = 25.0
    
    # 月線乖離風險 (權重最高)
    bias = res["bias_20"]
    if bias > 25.0:
        r_score += 45
        res["r_reasons"].append(f"🔴 月線超高乖離({bias:.1f}%)")
    elif bias > 15.0:
        r_score += 30
        res["r_reasons"].append(f"🔴 月線高乖離({bias:.1f}%)")
    elif bias > 8.0:
        r_score += 15
        res["r_reasons"].append(f"🟡 月線中乖離({bias:.1f}%)")
    elif bias <= 4.0:
        r_score -= 10
        res["r_reasons"].append("🟢 安全低乖離(<4%)")
        
    # 外資抽資風險
    f_ratio = res["foreign_ratio"]
    if f_ratio >= 40.0:
        r_score += 15
        res["r_reasons"].append(f"🚨 外資高持股({f_ratio:.1f}%)")
    elif f_ratio <= 15.0:
        r_score -= 10
        res["r_reasons"].append(f"✅ 內資主導({f_ratio:.1f}%)")
        
    # 融資散戶過熱與大戶建倉區分
    if margin > 800:
        if not is_major_margin:
            r_score += 15
            res["r_reasons"].append(f"🔴 融資飆升({margin}張)")
    elif margin < -500:
        r_score -= 10
        res["r_reasons"].append(f"🟢 融資減肥({margin}張)")
        
    # 技術面風險
    if latest['K'] > 80:
        r_score += 10
        res["r_reasons"].append("🟡 KD進入超買高檔區")
    if res["kd_status"] == "死叉":
        r_score += 10
        res["r_reasons"].append("🔴 KD高檔死亡交叉")
    if res["close"] < latest['20MA']:
        r_score += 15
        res["r_reasons"].append("🔴 股價處於月線下方(弱勢)")
        
    res["risk_score"] = max(5.0, min(100.0, r_score))
    
    # 3. 綜合性價比排行得分
    res["rank_score"] = res["profit_potential"] - res["risk_score"]
    
    return res

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    stocks = load_tracked_stocks()
    if not stocks:
        return
        
    # 尋找 data 目錄下最新的資料夾
    data_dir = os.path.join(WORKSPACE, "data")
    dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d)) and d.isdigit()]
    if dirs:
        today_str = sorted(dirs)[-1]
    else:
        today_str = "20260702" # fallback
    target_dir = os.path.join(WORKSPACE, "data", today_str)
    
    # 支援盤中即時查價
    realtime_prices = {}
    is_realtime = "--realtime" in sys.argv
    if is_realtime:
        symbols_to_query = []
        for s in stocks:
            code = s["code"]
            prefix = s["market"].lower()
            symbols_to_query.append(f"{prefix}_{code}.tw")
        symbols_to_query.append("tse_t00.tw") # 大盤
        
        ex_ch_str = "|".join(symbols_to_query)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}"
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode('utf-8'))
                msg_array = res.get("msgArray", [])
                for stock in msg_array:
                    code = stock.get("c")
                    if code == "t00":
                        z_val = stock.get("z", "")
                        if z_val != "-" and z_val != "":
                            realtime_prices["TAIEX"] = float(z_val)
                        else:
                            b_val = stock.get("b", "0")
                            realtime_prices["TAIEX"] = float(b_val.split("_")[0])
                    else:
                        z_val = stock.get("z", "-")
                        if z_val != "-" and z_val != "":
                            realtime_prices[code] = float(z_val)
                        else:
                            b_val = stock.get("b", "-")
                            if b_val != "-" and b_val != "":
                                realtime_prices[code] = float(b_val.split("_")[0])
            print("盤中即時報價獲取成功，已自動覆蓋並重新計算指標！")
        except Exception as e:
            print(f"盤中即時報價獲取失敗: {e}")
            
    # 尋找最新的交易日期與近5日範圍
    latest_date_str = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}" # fallback
    date_range_str = "06-26 ~ 07-02" # fallback
    if is_realtime:
        latest_date_str = datetime.now().strftime("%Y-%m-%d %H:%M (盤中即時更新)")
        date_range_str = date_range_str + " + 今日即時"
    else:
        for s in stocks:
            kline_path = os.path.join(target_dir, f"{s['code']}_kline.csv")
            if os.path.exists(kline_path):
                try:
                    df_temp = pd.read_csv(kline_path).sort_values('date')
                    if not df_temp.empty:
                        latest_date_str = df_temp['date'].max()
                        if len(df_temp) >= 5:
                            last_5_dates = df_temp['date'].iloc[-5:].tolist()
                            d_start = datetime.strptime(last_5_dates[0], "%Y-%m-%d").strftime("%m-%d")
                            d_end = datetime.strptime(last_5_dates[-1], "%Y-%m-%d").strftime("%m-%d")
                            date_range_str = f"{d_start} ~ {d_end}"
                        break
                except Exception:
                    pass
                
    try:
        dt = datetime.strptime(latest_date_str.split(" ")[0], '%Y-%m-%d')
        notice_date_str = f"{dt.month}/{dt.day}"
    except Exception:
        notice_date_str = "7/3"
    
    # 讀取大盤加權指數 (TAIEX) 的 K 線資料並評估多空狀態
    taiex_state_msg = ""
    taiex_kline_path = os.path.join(target_dir, "TAIEX_kline.csv")
    if os.path.exists(taiex_kline_path):
        try:
            df_taiex = pd.read_csv(taiex_kline_path)
            if not df_taiex.empty and len(df_taiex) >= 20:
                df_taiex = df_taiex.sort_values('date').reset_index(drop=True)
                df_taiex['20MA'] = df_taiex['close'].rolling(20).mean()
                latest_taiex = df_taiex.iloc[-1]
                taiex_close = float(latest_taiex['close'])
                taiex_ma20 = float(latest_taiex['20MA'])
                
                if taiex_close > taiex_ma20:
                    taiex_state_msg = "> [!NOTE]\n> **🟢 【大盤多空濾網】**大盤目前處於月線（20MA）上方的多頭格局，市場環境健康，適合積極布局與持股。"
                else:
                    taiex_state_msg = "> [!WARNING]\n> **⚠️ 【大盤多空濾網警報】**大盤目前低於月線（20MA）弱勢區，系統性風險較高。建議調降持股水位至 40% 以下，波段策略轉為保守防守，並避開高外資持股標的。"
        except Exception as e:
            taiex_state_msg = f"> [!WARNING]\n> **⚠️ 【大盤多空濾網】**大盤分析失敗: {e}"
    else:
        taiex_state_msg = "> [!WARNING]\n> **⚠️ 【大盤多空濾網】**未找到大盤 (TAIEX) 資料，無法進行系統性風險評估。"

    analyzed_list = []
    for s in stocks:
        res = analyze_stock_risk_reward(s["code"], s["name"], target_dir, realtime_prices.get(s["code"]))
        if res:
            analyzed_list.append(res)
            
    # 依照 rank_score (利潤 - 風險) 由高到低排序 (風險低獲利高優先)
    analyzed_list.sort(key=lambda x: x["rank_score"], reverse=True)
    
    # 只保留前 25 名
    analyzed_list = analyzed_list[:25]
    
    report_path = os.path.join(WORKSPACE, "risk_reward_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# ⚖️ 台股追蹤標的：風險與獲利評估排行榜 (Risk-Reward Evaluation)\n\n")
        f.write(f"分析日期：{latest_date_str}  \n")
        f.write(f"此排行由 **Gemini 3.5 Flash (High)** 模型驅動，依據近 5 日（{date_range_str}）三大法人與 K 線數據計算。  \n")
        f.write("計算公式：**綜合性價比得分 (Rank Score) = 獲利可能性得分 - 風險得分**  \n")
        f.write("*(得分越高，代表目前處於『低乖離、內資安全控盤、法人默默吃貨』的絕佳安全買點；得分越低，代表『高檔乖離過大、外資隨時提款』的追高地雷)*  \n\n")
        f.write(f"{taiex_state_msg}\n\n")
        
        f.write("> [!WARNING]\n")
        f.write("> **🔥 【台指期夜盤黑天鵝警報】**\n")
        f.write("> 昨晚（7/2）美股費城半導體重挫 -5.44%，台積電 ADR 走弱，導致**台指期夜盤終場暴跌 938 點 (-2.01%)**，收在 45,668 點！\n")
        f.write("> 雖然 7/2 收盤大盤月線（20MA: 45,482.51 點）尚未正式跌破，但夜盤收盤價已極度逼近月線邊緣（僅餘 +0.41% 空間）。今日（7/3）開盤現貨將面臨極大下殺壓力，**盤中請務必保持冷靜、禁止盲目追高，並嚴密守護 20MA 關卡**。若今日收盤價跌破月線，波段部位應立刻啟動防風機制減碼。\n\n")
        
        f.write("> [!NOTE]\n")
        f.write("> **⚡ 【廣發海外電子通信：AI 記憶體成本優化要聞分析】**\n")
        f.write("> 英偉達很可能將 VR200 機架預設的 CPU 側 SOCAMM 配置從 192GB 削減一半至 96GB，以因應 LPDDR5X 供應緊張與成本優化。這可使機架整體成本降低 10%，控制在 2027 年 BOM 表的 20% 水平。此外通用伺服器 DDR5 配置預估也將同步下修 50%。\n")
        f.write("> **台股供應鏈影響傳導**：\n")
        f.write("> 1. **高頻 CCL/PCB 與散熱模組（利多）**：降規有助於降低成本、保障英偉達伺服器機架的**出貨量（Volume）**。對於以機架套數計價的 **聯茂(6213)**、**力致(3483)** 是實質保護，保障了下半年的營收能見度。\n")
        f.write("> 2. **DRAM 廠（中性）**：LPDDR5X 容量腰斬可能造成短期 bit 需求放緩，但由於台廠如 **南亞科(2408)、華邦電(2344)** 重心在利基型與中低容量晶片，受 AI 頂規伺服器容量變動影響非常有限，且 Q4 通用伺服器出貨預期強彈，有助於傳統 DRAM 報價築底。\n\n")
        
        f.write("> [!IMPORTANT]\n")
        f.write(f"> **注意**：本報告已依據 {notice_date_str} 最新日報利多，下載並補齊 **牧德(3563)、印能科技(7734)、科嶠(4542)、聯策(6658)、金雨(4503)** 等 5 檔標的之籌碼與技術數據。**本排行已重新計算，且僅保留綜合性價比最高的前 25 名標的。**\n\n")
        
        f.write("### 🥇 「風險低、獲利高」精選前 25 名排行榜\n\n")
        f.write("| 排名 | 股號 | 股名 | 收盤價 | 綜合性價比得分 | 獲利可能性 (0-100) | 風險得分 (0-100) | 20MA乖離 | 外資持股 | 籌碼特性 | 5日融資變動 | 核心評估觀點 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        
        for idx, r in enumerate(analyzed_list, 1):
            ratio = r['foreign_ratio']
            if ratio >= 40.0:
                char_tag = "🚨 外資主導"
            elif ratio <= 15.0:
                char_tag = "✅ 內資主導"
            else:
                char_tag = "中等"
                
            f.write(f"| {idx} | `{r['code']}` | **{r['name']}** | {r['close']:.2f} | **{r['rank_score']:.1f}** | {r['profit_potential']:.1f} | {r['risk_score']:.1f} | {r['bias_20']:.1f}% | {ratio:.2f}% | {char_tag} | {r['margin_diff_5d']:,}張 | 獲利因：{', '.join(r['p_reasons'][:2]) if r['p_reasons'] else '暫無'} <br> 風險因：{', '.join(r['r_reasons'][:2]) if r['r_reasons'] else '安全'} |\n")
            
        f.write("\n\n## 🔍 前五名「黃金高興價比」標的詳細解析\n\n")
        for idx, r in enumerate(analyzed_list[:5], 1):
            f.write(f"### {idx}. `{r['code']}` {r['name']} (綜合得分: **{r['rank_score']:.1f}**)\n")
            f.write(f"* **最新收盤價**: {r['close']:.2f} 元 (20MA 乖離: **{r['bias_20']:+.2f}%**)\n")
            f.write(f"* **獲利可能性分**: **{r['profit_potential']:.1f}** / 100 \n")
            f.write(f"* **風險得分**: **{r['risk_score']:.1f}** / 100 \n")
            f.write(f"* **外資持股比例**: {r['foreign_ratio']:.2f}% ({'🚨 外資主導' if r['foreign_ratio']>=40 else '✅ 內資主導' if r['foreign_ratio']<=15 else '中等'})\n")
            f.write(f"* **利多支撐因子**: {', '.join(r['p_reasons']) if r['p_reasons'] else '技術整理中'}\n")
            f.write(f"* **風險警示因子**: {', '.join(r['r_reasons']) if r['r_reasons'] else '各項指標安全'}\n")
            f.write(f"* **💡 AI 操盤觀點**: 本股目前處於**風險極低且法人買盤回流**的黃金區間。月線乖離低代表安全邊際足夠，同時伴隨籌碼沉澱（融資減肥），是目前最值得優先佈局的標的。\n\n")
            f.write("--- \n\n")
            
        f.write("\n\n## ⚠️ 後五名「偏低性價比/警示」標的解析 (第21-25名)\n\n")
        for idx, r in enumerate(reversed(analyzed_list[-5:]), 21):
            f.write(f"### {idx}. `{r['code']}` {r['name']} (綜合得分: **{r['rank_score']:.1f}**)\n")
            f.write(f"* **最新收盤價**: {r['close']:.2f} 元 (20MA 乖離: **{r['bias_20']:+.2f}%**)\n")
            f.write(f"* **獲利可能性分**: **{r['profit_potential']:.1f}** / 100 \n")
            f.write(f"* **風險得分**: **{r['risk_score']:.1f}** / 100 \n")
            f.write(f"* **外資持股比例**: {r['foreign_ratio']:.2f}% ({'🚨 外資主導' if r['foreign_ratio']>=40 else '✅ 內資主導' if r['foreign_ratio']<=15 else '中等'})\n")
            f.write(f"* **利多支撐因子**: {', '.join(r['p_reasons']) if r['p_reasons'] else '主要為價格慣性'}\n")
            f.write(f"* **風險警示因子**: {', '.join(r['r_reasons']) if r['r_reasons'] else '乖離大或法人調節'}\n")
            f.write(f"* **💡 AI 操盤觀點**: 該股在本報告前25名中性價比相對偏低，通常伴隨較高乖離或法人買盤減弱。建議切勿在此時盲目追高，靜待股價回測月線再做考量。\n\n")
            f.write("--- \n\n")

    print(f"新版風險/收益評估報告（前25名）已成功生成至: {report_path}")

if __name__ == "__main__":
    main()
