import os
from datetime import datetime, timedelta
from FinMind.data import DataLoader

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
FINMIND_TOKEN = ""

def main():
    api = DataLoader()
    if FINMIND_TOKEN:
        api.login_by_token(api_token=FINMIND_TOKEN)
        
    today_str = "20260702"
    target_dir = os.path.join(WORKSPACE, "data", today_str)
    os.makedirs(target_dir, exist_ok=True)
    
    end_date = "2026-07-02"
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    
    code = "3484"
    name = "崧騰"
    print(f"開始單獨下載: {code} {name} 的 90天數據 ({start_date} ~ {end_date})...")
    
    # 1. K線
    try:
        df_kline = api.taiwan_stock_daily(stock_id=code, start_date=start_date, end_date=end_date)
        if not df_kline.empty:
            df_kline.to_csv(os.path.join(target_dir, f"{code}_kline.csv"), index=False, encoding='utf-8-sig')
            print("  -> K線下載成功")
    except Exception as e:
        print(f"  -> K線下載失敗: {e}")
        
    # 2. 三大法人
    try:
        df_inst = api.taiwan_stock_institutional_investors(stock_id=code, start_date=start_date, end_date=end_date)
        if not df_inst.empty:
            df_inst.to_csv(os.path.join(target_dir, f"{code}_chips_institutional.csv"), index=False, encoding='utf-8-sig')
            print("  -> 三大法人下載成功")
    except Exception as e:
        print(f"  -> 三大法人下載失敗: {e}")
        
    # 3. 融資融券
    try:
        df_margin = api.taiwan_stock_margin_purchase_short_sale(stock_id=code, start_date=start_date, end_date=end_date)
        if not df_margin.empty:
            df_margin.to_csv(os.path.join(target_dir, f"{code}_chips_margin.csv"), index=False, encoding='utf-8-sig')
            print("  -> 融資融券下載成功")
    except Exception as e:
        print(f"  -> 融資融券下載失敗: {e}")

if __name__ == "__main__":
    main()
