import os
import json
from datetime import datetime, timedelta
import pandas as pd
from FinMind.data import DataLoader

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
FINMIND_TOKEN = ""

def load_portfolio():
    json_path = os.path.join(WORKSPACE, "portfolio.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("holdings", [])

def main():
    holdings = load_portfolio()
    if not holdings:
        print("庫存清單為空。")
        return
        
    api = DataLoader()
    if FINMIND_TOKEN:
        api.login_by_token(api_token=FINMIND_TOKEN)
        
    today_str = "20260702"
    target_dir = os.path.join(WORKSPACE, "data", today_str)
    os.makedirs(target_dir, exist_ok=True)
    
    end_date = "2026-07-02"
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    
    print(f"開始下載庫存股票 90 天數據 ({start_date} ~ {end_date})...")
    
    for idx, h in enumerate(holdings, 1):
        code = h["code"]
        name = h["name"]
        print(f"[{idx}/{len(holdings)}] 下載中: {code} {name}...")
        
        # 1. 日 K 線
        try:
            df_kline = api.taiwan_stock_daily(stock_id=code, start_date=start_date, end_date=end_date)
            if not df_kline.empty:
                df_kline.to_csv(os.path.join(target_dir, f"{code}_kline.csv"), index=False, encoding='utf-8-sig')
                print(f"  -> {code} K線下載成功")
        except Exception as e:
            print(f"  -> {code} K線下載失敗: {e}")
            
        # 2. 三大法人
        try:
            df_inst = api.taiwan_stock_institutional_investors(stock_id=code, start_date=start_date, end_date=end_date)
            if not df_inst.empty:
                df_inst.to_csv(os.path.join(target_dir, f"{code}_chips_institutional.csv"), index=False, encoding='utf-8-sig')
                print(f"  -> {code} 三大法人下載成功")
        except Exception as e:
            print(f"  -> {code} 三大法人下載失敗: {e}")
            
        # 3. 融資融券
        try:
            df_margin = api.taiwan_stock_margin_purchase_short_sale(stock_id=code, start_date=start_date, end_date=end_date)
            if not df_margin.empty:
                df_margin.to_csv(os.path.join(target_dir, f"{code}_chips_margin.csv"), index=False, encoding='utf-8-sig')
                print(f"  -> {code} 融資融券下載成功")
        except Exception as e:
            print(f"  -> {code} 融資融券下載失敗: {e}")
            
        # 4. 外資持股比例 (若無權限則跳過)
        try:
            df_share = api.taiwan_stock_holding_shares_per(stock_id=code, start_date=(datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d"), end_date=end_date)
            if not df_share.empty:
                df_share.to_csv(os.path.join(target_dir, f"{code}_share_ratio.csv"), index=False, encoding='utf-8-sig')
                print(f"  -> {code} 外資持股比下載成功")
        except Exception as e:
            print(f"  -> {code} 外資持股比下載跳過 (無API權限，屬正常現象)")
            
    print("庫存數據下載完成！")

if __name__ == "__main__":
    main()
