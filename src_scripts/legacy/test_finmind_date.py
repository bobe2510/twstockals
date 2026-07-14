import sys
import os
import json
from FinMind.data import DataLoader

FINMIND_TOKEN = ""

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    api = DataLoader()
    if FINMIND_TOKEN:
        api.login_by_token(api_token=FINMIND_TOKEN)
        
    test_date = "2026-07-02"
    print(f"測試：下載 {test_date} 的全市場日 K 線...")
    
    # 嘗試不傳入 stock_id，只傳入日期
    try:
        df = api.taiwan_stock_daily(start_date=test_date, end_date=test_date)
        if not df.empty:
            print(f"成功！獲取到 {len(df)} 筆個股日 K 線數據！")
            print("資料欄位：", list(df.columns))
            print("前 3 筆範例：")
            print(df[['stock_id', 'close', 'Trading_Volume']].head(3))
        else:
            print("失敗：傳回空資料表")
    except Exception as e:
        print("發生異常：", e)
        
    print(f"\n測試：下載 {test_date} 的全市場三大法人買賣超...")
    try:
        df_inst = api.taiwan_stock_institutional_investors(start_date=test_date, end_date=test_date)
        if not df_inst.empty:
            print(f"成功！獲取到 {len(df_inst)} 筆個股三大法人數據！")
            print("資料欄位：", list(df_inst.columns))
            print("前 3 筆範例：")
            print(df_inst[['stock_id', 'buy', 'sell', 'name']].head(3))
        else:
            print("失敗：傳回空三大法人資料表")
    except Exception as e:
        print("發生異常：", e)

if __name__ == "__main__":
    main()
