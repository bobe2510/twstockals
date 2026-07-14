import os
import pandas as pd
import numpy as np
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

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

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    target_dir = os.path.join(WORKSPACE, "data", "20260630")
    code = "6451"
    name = "訊芯-KY"
    
    kline_path = os.path.join(target_dir, f"{code}_kline.csv")
    chips_inst_path = os.path.join(target_dir, f"{code}_chips_institutional.csv")
    chips_margin_path = os.path.join(target_dir, f"{code}_chips_margin.csv")
    
    if not os.path.exists(kline_path):
        print(f"錯誤：找不到 {code} 的 K 線資料")
        return
        
    df_k = pd.read_csv(kline_path).sort_values('date').reset_index(drop=True)
    df_k = calculate_kd(df_k)
    df_k['5MA'] = df_k['close'].rolling(5).mean()
    df_k['10MA'] = df_k['close'].rolling(10).mean()
    df_k['20MA'] = df_k['close'].rolling(20).mean()
    df_k['60MA'] = df_k['close'].rolling(60).mean()
    
    latest = df_k.iloc[-1]
    close = float(latest['close'])
    ma5 = float(latest['5MA'])
    ma10 = float(latest['10MA'])
    ma20 = float(latest['20MA'])
    ma60 = float(latest['60MA'])
    k_val = float(latest['K'])
    d_val = float(latest['D'])
    bias_20 = ((close - ma20) / ma20) * 100
    
    # 三大法人近 5 日買賣超
    inst_buy_5d = 0
    consecutive_buy = 0
    if os.path.exists(chips_inst_path):
        df_inst = pd.read_csv(chips_inst_path).sort_values('date')
        df_foreign = df_inst[df_inst['name'] == 'Foreign_Investor']
        df_trust = df_inst[df_inst['name'] == 'Investment_Trust']
        f_net = df_foreign.iloc[-5:]['buy'].sum() - df_foreign.iloc[-5:]['sell'].sum() if not df_foreign.empty else 0
        t_net = df_trust.iloc[-5:]['buy'].sum() - df_trust.iloc[-5:]['sell'].sum() if not df_trust.empty else 0
        inst_buy_5d = int((f_net + t_net) / 1000)
        
        # 連續買超天數
        df_pivot = df_inst.pivot_table(index='date', columns='name', values=['buy', 'sell'])
        if not df_pivot.empty:
            df_pivot['net_foreign'] = df_pivot[('buy', 'Foreign_Investor')] - df_pivot[('sell', 'Foreign_Investor')] if ('buy', 'Foreign_Investor') in df_pivot.columns else 0
            df_pivot['net_trust'] = df_pivot[('buy', 'Investment_Trust')] - df_pivot[('sell', 'Investment_Trust')] if ('buy', 'Investment_Trust') in df_pivot.columns else 0
            df_pivot['net_total'] = df_pivot['net_foreign'] + df_pivot['net_trust']
            for net in reversed(df_pivot['net_total'].tolist()):
                if net > 0:
                    consecutive_buy += 1
                else:
                    break

    # 融資近 5 日變動
    margin_diff_5d = 0
    if os.path.exists(chips_margin_path):
        df_margin = pd.read_csv(chips_margin_path).sort_values('date')
        balance_cols = [c for c in df_margin.columns if 'balance' in c.lower() or 'purchase' in c.lower() and 'limit' not in c.lower()]
        if balance_cols:
            col = balance_cols[0]
            margin_diff_5d = int(df_margin.iloc[-1][col] - df_margin.iloc[-5][col])

    # 輸出分析結果
    print(f"\n==================== 【{code} {name}】90天技術與籌碼數據 ====================")
    print(f"收盤價: {close:.2f} 元")
    print(f"5MA  (週線) : {ma5:.2f} 元")
    print(f"10MA (雙週): {ma10:.2f} 元")
    print(f"20MA (月線) : {ma20:.2f} 元 (乖離率: {bias_20:+.2f}%)")
    print(f"60MA (季線) : {ma60:.2f} 元")
    print(f"KD指標      : {'黃金交叉' if k_val > d_val else '死亡交叉'} (K:{k_val:.1f} / D:{d_val:.1f})")
    print(f"5日法人買超 : {inst_buy_5d} 張 | 連續買超 {consecutive_buy} 天")
    print(f"5日融資變動 : {margin_diff_5d} 張")
    print(f"外資持股比例: 63.88% (🚨 外資主導型個股)")
    
    # 評分還原
    p_score = 40.0
    if inst_buy_5d > 2000: p_score += 25
    elif inst_buy_5d > 500: p_score += 15
    elif inst_buy_5d > 0: p_score += 5
    if consecutive_buy >= 4: p_score += 15
    elif consecutive_buy >= 2: p_score += 10
    profit_potential = min(100.0, p_score)
    
    r_score = 25.0
    if bias_20 > 25.0: r_score += 45
    elif bias_20 > 15.0: r_score += 30
    elif bias_20 > 8.0: r_score += 15
    elif bias_20 <= 4.0: r_score -= 10
    
    if 63.88 >= 40.0: r_score += 15
    if margin_diff_5d > 800: r_score += 15
    elif margin_diff_5d < -500: r_score -= 10
    
    if k_val > 80: r_score += 10
    if k_val <= d_val: r_score += 10
    if close < ma20: r_score += 15
    
    risk_score = max(5.0, min(100.0, r_score))
    rank_score = profit_potential - risk_score
    
    print(f"\n==================== 量化評分計算還原 ====================")
    print(f"1. 獲利可能性得分: {profit_potential:.1f} / 100 (基礎分40 + 無法人強勢買盤)")
    print(f"2. 風險得分      : {risk_score:.1f} / 100 (基礎分25 + 外資高持股加重險15 + 股價處於月線下方轉弱15 + KD死叉10 - 安全低乖離扣減10)")
    print(f"3. 綜合性價比得分: {rank_score:.1f} (Rank Score)")

if __name__ == "__main__":
    main()
