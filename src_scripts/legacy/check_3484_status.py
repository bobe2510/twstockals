import os
import pandas as pd
import sys

# 引入 analyze_stocks_risk_reward 裡面的分析函式
WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
sys.path.append(WORKSPACE)
from analyze_stocks_risk_reward import analyze_stock_risk_reward, load_tracked_stocks

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    target_dir = os.path.join(WORKSPACE, "data", "20260702")
    
    # 1. 跑 3484 的分析
    res = analyze_stock_risk_reward("3484", "崧騰", target_dir)
    
    if not res:
        print("錯誤：無法對 3484 進行量化分析，請確認資料完整度。")
        return
        
    # 2. 載入所有股票並做排序，找出 3484 的排名
    stocks = load_tracked_stocks()
    all_results = []
    for s in stocks:
        r = analyze_stock_risk_reward(s["code"], s["name"], target_dir)
        if r:
            all_results.append(r)
            
    all_results.sort(key=lambda x: x["rank_score"], reverse=True)
    
    rank = -1
    for idx, r in enumerate(all_results, 1):
        if r["code"] == "3484":
            rank = idx
            break
            
    print("\n==================== 【3484 崧騰】7/2 盤後量化健康診斷 ====================")
    print(f"收盤價        : {res['close']:.2f} 元")
    print(f"20MA 乖離率   : {res['bias_20']:.2f}%")
    print(f"5日法人買超   : {res['margin_diff_5d']} 張 (註: margin_diff_5d在分析腳本中用於儲存融資變動，法人買超為 inst_buy_5d)") # 修正說明
    
    # 讀取三大法人買賣超與融資數據
    df_inst = pd.read_csv(os.path.join(target_dir, "3484_chips_institutional.csv"))
    df_foreign = df_inst[df_inst['name'] == 'Foreign_Investor']
    df_trust = df_inst[df_inst['name'] == 'Investment_Trust']
    f_net = df_foreign.iloc[-5:]['buy'].sum() - df_foreign.iloc[-5:]['sell'].sum() if not df_foreign.empty else 0
    t_net = df_trust.iloc[-5:]['buy'].sum() - df_trust.iloc[-5:]['sell'].sum() if not df_trust.empty else 0
    inst_buy_5d = int((f_net + t_net) / 1000)
    
    print(f"5日法人實際買超: {inst_buy_5d} 張")
    print(f"外資持股比例  : {res['foreign_ratio']:.2f}% ({'🚨 外資主導' if res['foreign_ratio']>=40 else '✅ 內資主導' if res['foreign_ratio']<=15 else '中等'})")
    
    print("\n[量化評分]")
    print(f"1. 獲利可能性得分: {res['profit_potential']:.1f} / 100")
    print(f"2. 風險得分      : {res['risk_score']:.1f} / 100")
    print(f"3. 綜合性價比得分: {res['rank_score']:.1f} (Rank Score)")
    print(f"📊 崧騰在所有 {len(all_results)} 檔追蹤標的中的排名: 第 {rank} 名")
    
    print("\n[因子明細]")
    print(f"利多支撐因子: {res['p_reasons']}")
    print(f"風險警示因子: {res['r_reasons']}")

if __name__ == "__main__":
    main()
