import os
import pandas as pd
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def get_details(code, name, target_dir):
    kline_path = os.path.join(target_dir, f"{code}_kline.csv")
    chips_inst_path = os.path.join(target_dir, f"{code}_chips_institutional.csv")
    chips_margin_path = os.path.join(target_dir, f"{code}_chips_margin.csv")
    
    if not os.path.exists(kline_path):
        return None
        
    # 讀取數據
    df_k = pd.read_csv(kline_path)
    df_k = df_k[df_k['date'] >= '2026-06-24'].copy()
    
    # 法人數據
    inst_data = {}
    if os.path.exists(chips_inst_path):
        df_inst = pd.read_csv(chips_inst_path)
        df_inst = df_inst[df_inst['date'] >= '2026-06-24']
        # 按日期與法人分類加總
        for date, group in df_inst.groupby('date'):
            foreign = group[group['name'] == 'Foreign_Investor']
            trust = group[group['name'] == 'Investment_Trust']
            f_net = (foreign['buy'].sum() - foreign['sell'].sum()) if not foreign.empty else 0
            t_net = (trust['buy'].sum() - trust['sell'].sum()) if not trust.empty else 0
            inst_data[date] = {"foreign_net": f_net, "trust_net": t_net}
            
    # 融資數據
    margin_data = {}
    if os.path.exists(chips_margin_path):
        df_margin = pd.read_csv(chips_margin_path)
        df_margin = df_margin[df_margin['date'] >= '2026-06-24']
        # 尋找融資餘額欄位
        balance_cols = [c for c in df_margin.columns if 'balance' in c.lower() or 'purchase' in c.lower() and 'limit' not in c.lower()]
        if balance_cols:
            col = balance_cols[0]
            for idx, row in df_margin.iterrows():
                margin_data[row['date']] = row[col]
                
    # 整合
    rows = []
    for idx, row in df_k.iterrows():
        date = row['date']
        inst = inst_data.get(date, {"foreign_net": 0, "trust_net": 0})
        margin_val = margin_data.get(date, 0)
        
        rows.append({
            "日期": date,
            "收盤價": row['close'],
            "成交量": row.get('Trading_Volume', 0),
            "外資買賣超(張)": inst["foreign_net"],
            "投信買賣超(張)": inst["trust_net"],
            "融資餘額(張)": margin_val
        })
        
    df_res = pd.DataFrame(rows)
    # 計算融資每日增減
    if not df_res.empty and '融資餘額(張)' in df_res.columns:
        df_res['融資單日增減(張)'] = df_res['融資餘額(張)'].diff().fillna(0).astype(int)
        
    return df_res

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    today_str = "20260630"
    target_dir = os.path.join(WORKSPACE, "data", today_str)
    
    # 核心分析對象
    core_stocks = [
        {"code": "6213", "name": "聯茂"},
        {"code": "3483", "name": "力致"},
        {"code": "00631L", "name": "元大台灣50正2"},
        {"code": "00632R", "name": "元大台灣50反1"}
    ]
    
    for s in core_stocks:
        print(f"\n==================== 【{s['code']} {s['name']}】近 5 日微觀數據 ====================")
        df_res = get_details(s['code'], s['name'], target_dir)
        if df_res is not None and not df_res.empty:
            # 格式化輸出
            print(df_res[['日期', '收盤價', '成交量', '外資買賣超(張)', '投信買賣超(張)', '融資單日增減(張)']].to_string(index=False))
        else:
            print("無資料或讀取失敗。")

if __name__ == "__main__":
    main()
