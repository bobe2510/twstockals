import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
today_str = "20260702"  # 分析當天最新數據
DATA_DIR = os.path.join(WORKSPACE, "data", today_str)

# 外資持股比例對照表
FOREIGN_OWNERSHIP = {
    "2303": 40.89, "2316": 37.59, "2344": 18.94, "2383": 44.30, "2408": 14.25,
    "2467": 19.79, "3693": 6.68, "3706": 9.78, "4764": 1.50, "5243": 52.76,
    "5285": 7.20, "5469": 12.65, "6139": 31.91, "6191": 5.98, "6213": 21.63,
    "00631L": 0.50, "6291": 1.20, "6415": 79.72, "6451": 63.88, "6693": 2.10,
    "7828": 1.80, "8162": 3.20, "8996": 37.22,
    "3563": 6.64, "7734": 2.95, "4542": 10.89, "6658": 1.60, "4503": 3.79
}

def load_tracked_stocks():
    json_path = os.path.join(WORKSPACE, "tracked_stocks.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("tracked_stocks", [])

def calculate_kd(df, n=9):
    df = df.copy()
    df['Low_n'] = df['min'].rolling(window=n).min()
    df['High_n'] = df['max'].rolling(window=n).max()
    df['RSV'] = 0.0
    denom = df['High_n'] - df['Low_n']
    df.loc[denom > 0, 'RSV'] = (df['close'] - df['Low_n']) / denom * 100
    
    k = []
    d = []
    current_k = 50.0
    current_d = 50.0
    for rsv in df['RSV']:
        if pd.isna(rsv):
            k.append(np.nan)
            d.append(np.nan)
        else:
            current_k = current_k * (2/3) + rsv * (1/3)
            current_d = current_d * (2/3) + current_k * (1/3)
            k.append(current_k)
            d.append(current_d)
    df['K'] = k
    df['D'] = d
    return df

def analyze_stock(stock):
    stock_id = stock["code"]
    name = stock["name"]
    
    kline_path = os.path.join(DATA_DIR, f"{stock_id}_kline.csv")
    inst_path = os.path.join(DATA_DIR, f"{stock_id}_chips_institutional.csv")
    margin_path = os.path.join(DATA_DIR, f"{stock_id}_chips_margin.csv")
    
    if not (os.path.exists(kline_path) and os.path.exists(inst_path) and os.path.exists(margin_path)):
        return None
        
    df_k = pd.read_csv(kline_path).sort_values('date').reset_index(drop=True)
    df_i = pd.read_csv(inst_path).sort_values('date').reset_index(drop=True)
    df_m = pd.read_csv(margin_path).sort_values('date').reset_index(drop=True)
    
    if len(df_k) < 20:
        return None
        
    df_k['5MA'] = df_k['close'].rolling(5).mean()
    df_k['10MA'] = df_k['close'].rolling(10).mean()
    df_k['20MA'] = df_k['close'].rolling(20).mean()
    df_k = calculate_kd(df_k)
    
    last_idx = len(df_k) - 1
    close = df_k.loc[last_idx, 'close']
    ma5 = df_k.loc[last_idx, '5MA']
    ma10 = df_k.loc[last_idx, '10MA']
    ma20 = df_k.loc[last_idx, '20MA']
    k_val = df_k.loc[last_idx, 'K']
    d_val = df_k.loc[last_idx, 'D']
    
    # 均線排列
    ma_alignment = "整理"
    if close > ma5 > ma10 > ma20:
        ma_alignment = "多頭"
    elif close < ma5 < ma10 < ma20:
        ma_alignment = "空頭"
        
    kd_status = "金叉" if k_val > d_val else "死叉"
    bias_20 = ((close - ma20) / ma20) * 100 if ma20 else 0
    
    # 法人數據
    df_inst_pivot = df_i.pivot_table(index='date', columns='name', values=['buy', 'sell'], aggfunc='sum').fillna(0)
    foreign_net = df_inst_pivot[('buy', 'Foreign_Investor')] - df_inst_pivot[('sell', 'Foreign_Investor')] if ('buy', 'Foreign_Investor') in df_inst_pivot.columns else pd.Series([0]*len(df_inst_pivot))
    trust_net = df_inst_pivot[('buy', 'Investment_Trust')] - df_inst_pivot[('sell', 'Investment_Trust')] if ('buy', 'Investment_Trust') in df_inst_pivot.columns else pd.Series([0]*len(df_inst_pivot))
    inst_total_net = foreign_net + trust_net
    
    # 法人連續買超天數
    recent_inst = inst_total_net.tail(5).values
    consecutive_buy = 0
    for val in reversed(recent_inst):
        if val > 0:
            consecutive_buy += 1
        else:
            break
            
    # 法人買超比例
    avg_volume_5d = df_k['Trading_Volume'].tail(5).mean()
    net_buy_5d = inst_total_net.tail(5).sum()
    inst_buy_5d_shares = int(net_buy_5d / 1000) # 折算為張數
    
    # 融資變動
    df_m_sorted = df_m.sort_values('date').tail(5).reset_index(drop=True)
    margin_col = [c for c in df_m_sorted.columns if 'balance' in c.lower() or 'purchase' in c.lower() and 'limit' not in c.lower()][0]
    margin_diff_5d = int(df_m_sorted.loc[len(df_m_sorted)-1, margin_col] - df_m_sorted.loc[0, margin_col])
    
    foreign_ratio = FOREIGN_OWNERSHIP.get(stock_id, 15.0)
    
    # ==========================================================
    # 風險與獲利可能性評分
    # ==========================================================
    # 1. 獲利可能性 (0-100)
    p_score = 40.0
    p_reasons = []
    
    if inst_buy_5d_shares > 2000:
        p_score += 25
        p_reasons.append("5日法人大買(>2000張)")
    elif inst_buy_5d_shares > 500:
        p_score += 15
        p_reasons.append("5日法人買超(>500張)")
    elif inst_buy_5d_shares > 0:
        p_score += 5
        
    if consecutive_buy >= 4:
        p_score += 15
        p_reasons.append(f"法人強勢連買{consecutive_buy}天")
    elif consecutive_buy >= 2:
        p_score += 10
        p_reasons.append(f"法人連買{consecutive_buy}天")
        
    if ma_alignment == "多頭":
        p_score += 10
        p_reasons.append("均線多頭排列")
    if kd_status == "金叉":
        p_score += 10
        p_reasons.append("KD黃金交叉")
        
    profit_potential = min(100.0, p_score)
    
    # 2. 風險評分 (0-100)
    r_score = 25.0
    r_reasons = []
    
    # 月線乖離風險
    if bias_20 > 25.0:
        r_score += 45
        r_reasons.append(f"🔴 月線超高乖離({bias_20:.1f}%)")
    elif bias_20 > 15.0:
        r_score += 30
        r_reasons.append(f"🔴 月線高乖離({bias_20:.1f}%)")
    elif bias_20 > 8.0:
        r_score += 15
        r_reasons.append(f"🟡 月線中乖離({bias_20:.1f}%)")
    elif bias_20 <= 4.0:
        r_score -= 10
        r_reasons.append("🟢 安全低乖離(<4%)")
        
    # 外資主導風險
    if foreign_ratio >= 40.0:
        r_score += 15
        r_reasons.append(f"🚨 外資高持股({foreign_ratio:.1f}%)")
    elif foreign_ratio <= 15.0:
        r_score -= 10
        r_reasons.append(f"✅ 內資主導({foreign_ratio:.1f}%)")
        
    # 融資散戶過熱風險
    if margin_diff_5d > 800:
        r_score += 15
        r_reasons.append(f"🔴 融資飆升({margin_diff_5d}張)")
    elif margin_diff_5d < -500:
        r_score -= 10
        r_reasons.append(f"🟢 融資減肥({margin_diff_5d}張)")
        
    # 其他技術風險
    if k_val > 80:
        r_score += 10
        r_reasons.append("🟡 KD進入超買區")
    if kd_status == "死叉":
        r_score += 10
        r_reasons.append("🔴 KD死亡交叉")
    if close < ma20:
        r_score += 15
        r_reasons.append("🔴 股價處於月線下方")
        
    risk_score = max(5.0, min(100.0, r_score))
    
    # 綜合性價比得分 (Rank Score)
    rank_score = profit_potential - risk_score
    
    return {
        "code": stock_id,
        "name": name,
        "close": close,
        "bias_20": bias_20,
        "consecutive_buy": consecutive_buy,
        "margin_diff_5d": margin_diff_5d,
        "foreign_ratio": foreign_ratio,
        "profit_potential": profit_potential,
        "risk_score": risk_score,
        "rank_score": rank_score,
        "p_reasons": p_reasons,
        "r_reasons": r_reasons,
        "ma_alignment": ma_alignment,
        "kd_status": kd_status
    }

def main():
    stocks = load_tracked_stocks()
    results = []
    for s in stocks:
        res = analyze_stock(s)
        if res:
            results.append(res)
            
    # 依照性價比 (Rank Score) 由高到低排序 (風險低獲利高優先)
    results.sort(key=lambda x: x["rank_score"], reverse=True)
    
    # 只保留前 25 名
    results = results[:25]
    
    report_path = os.path.join(WORKSPACE, "analysis_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# 🏆 台股精選潛力股：風險與獲利評估綜合報告 (Risk-Reward Ranked)\n\n")
        f.write(f"分析日期：{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}  \n")
        f.write("此報告套用最新量化模型：**綜合性價比得分 (Rank Score) = 獲利可能性得分 - 風險得分**。  \n")
        f.write("此排行依據 **『風險最低、獲利可能性最高』** 排序，助您過濾掉過熱的追高標的，鎖定低乖離有籌碼支撐的安全買點。  \n\n")
        
        f.write("### 🥇 綜合性價比評估排行榜\n\n")
        f.write("| 排名 | 股號 | 股名 | 收盤價 | 綜合性價比得分 | 獲利可能性 (0-100) | 風險得分 (0-100) | 20MA乖離 | 外資持股 | 籌碼特性 | 法人連買 | 5日融資變動 | 核心評估觀點 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        
        for idx, r in enumerate(results, 1):
            ratio = r['foreign_ratio']
            if ratio >= 40.0:
                char_tag = "🚨 外資主導"
            elif ratio <= 15.0:
                char_tag = "✅ 內資主導"
            else:
                char_tag = "中等"
                
            p_res_str = r['p_reasons'][0] if r['p_reasons'] else "籌碼整理"
            r_res_str = r['r_reasons'][0] if r['r_reasons'] else "指標安全"
            f.write(f"| {idx} | `{r['code']}` | **{r['name']}** | {r['close']:.2f} | **{r['rank_score']:.1f}** | {r['profit_potential']:.1f} | {r['risk_score']:.1f} | {r['bias_20']:.1f}% | {ratio:.2f}% | {char_tag} | {r['consecutive_buy']}天 | {r['margin_diff_5d']:.0f}張 | 獲利：{p_res_str}<br>風險：{r_res_str} |\n")
            
        f.write("\n\n### 🔍 追蹤標的穿透診斷細節\n\n")
        for idx, r in enumerate(results, 1):
            ratio = r['foreign_ratio']
            if ratio >= 40.0:
                char_tag = "🚨 外資主導 (易受匯率及美股被動提款影響)"
            elif ratio <= 15.0:
                char_tag = "✅ 內資主導 (本土法人控盤，籌碼防禦力強)"
            else:
                char_tag = "中等屬性"
                
            f.write(f"#### {idx}. `{r['code']}` {r['name']} (性價比得分: **{r['rank_score']:.1f}**)\n")
            f.write(f"* **收盤價 / 20MA乖離**: {r['close']:.2f} 元 / **{r['bias_20']:+.1f}%**\n")
            f.write(f"* **資金分類**: **{ratio:.2f}%** ({char_tag})\n")
            f.write(f"* **獲利可能性得分**: **{r['profit_potential']:.1f}** / 100\n")
            f.write(f"  * 利多支撐: {', '.join(r['p_reasons']) if r['p_reasons'] else '技術築底中'}\n")
            f.write(f"* **風險評估得分**: **{r['risk_score']:.1f}** / 100\n")
            f.write(f"  * 風險警示: {', '.join(r['r_reasons']) if r['r_reasons'] else '指標安全'}\n")
            f.write(f"--- \n\n")
            
        # ==========================================================
        # 額外補充：7/1 最新日報利多與設備股焦點
        # ==========================================================
        f.write("## 🗞️ 補充資訊：2026-07-01 最新日報利多與設備股焦點\n\n")
        f.write("> [!TIP]\n")
        f.write("> 以下是 2026-07-01 工商時報最新 OCR 解析出的高成長設備與半導體利多股，可作為近期超前部署之名單：\n\n")
        
        f.write("### 1. ⚙️ AI 檢測與先進封裝設備股特搜\n")
        f.write("*   **`3563` 牧德 (Machvision)**\n")
        f.write("    *   *利多情報*：30日舉行法說，執行長宣布**訂單能見度已看至 2027 年**，AI 伺服器、HPC 及光模組檢測需求極強，高階 IC 載板已正式下單。公司更自 5 月起**調漲設備報價 8% 至 15%**以反映材料成本上漲。\n")
        f.write("    *   *營運數字*：Q1 營收 8.63 億，毛利率 60.6%，EPS 達 4.61 元，前五月累計營收持續雙位數年增。\n")
        f.write("*   **`7734` 印能科技**\n")
        f.write("    *   *利多情報*：應用於台積電 SoIC 製程的 Pro 機型、EvoRTS 及**面板級封裝 (PLP) 防翹曲 WSAS 設備**驗證順利，最快第四季開始認列營收，預期 2027 年爆發。Q2 單季營收有望突破 10 億元創歷史新高。\n")
        f.write("*   **`4542` 科嶠 / `6658` 聯策**\n")
        f.write("    *   *利多情報*：兩家設備廠聯手美國半導體自動化設備龍頭 Brooks Automation，授權金達 1,600 萬美元（約 5.1 億新台幣），全力強攻 AI 先進製程與 3D 先進封裝的微污染控制及晶圓載具清洗設備。\n\n")
        
        f.write("### 2. 🚆 智慧零售與軌道車廂大單\n")
        f.write("*   **`4503` 金雨**\n")
        f.write("    *   *利多情報*：奪下台灣某軌道車廂自動販賣機百台大單，且與多家大型半導體廠進行智慧零售合作，**客戶預視訂單需求看到 2028 年**。越南廠業務規模亦同步翻倍擴編。\n\n")
        f.write("### 3. 💵 總體經濟與資金行情\n")
        f.write("*   **新台幣匯率**：6/30 新台幣收在 31.837 元。央行阻貶守穩 31.8 元大關。下半年新台幣走勢與美股為外資持股走向的關鍵。\n")
        f.write("*   **ETF 狂潮**：截至 6/30 台股 ETF 規模正式衝破 7.2 兆元大關，0050 規模突破 2 兆元，正 2（00631L）規模大增 1,843 億元，台股市場「超額儲蓄 9 兆元」資金極度充沛，愈跌愈買效應顯著。\n")
        
    print(f"綜合報告分析完成並寫入: {report_path}")

if __name__ == "__main__":
    main()
