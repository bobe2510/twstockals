import os
import sys
import pandas as pd
from FinMind.data import DataLoader

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
target_dir = os.path.join(WORKSPACE, "data", "20260630")
start_date = "2026-04-01"
end_date = "2026-06-30"

# 使用您提供的 API Token
FINMIND_TOKENS = []

NEW_STOCKS = [
    {"code": "3563", "name": "牧德"},
    {"code": "7734", "name": "印能科技"},
    {"code": "4542", "name": "科嶠"},
    {"code": "6658", "name": "聯策"},
    {"code": "4503", "name": "金雨"}
]

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("正在下載 7/1 新聞焦點個股數據...")
    api = DataLoader()
    if FINMIND_TOKENS:
        try:
            api.login_by_token(api_token=FINMIND_TOKENS[0])
            print("FinMind Token 登入成功。")
        except Exception as e:
            print(f"登入失敗: {e}，將以免費限額模式運行。")
            
    for s in NEW_STOCKS:
        stock_id = s["code"]
        name = s["name"]
        print(f"正在下載: {stock_id} {name} ({start_date} ~ {end_date})...")
        try:
            df_k = api.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
            df_inst = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
            df_margin = api.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=end_date)
            
            if not df_k.empty:
                df_k.to_csv(os.path.join(target_dir, f"{stock_id}_kline.csv"), index=False, encoding='utf-8-sig')
            if not df_inst.empty:
                df_inst.to_csv(os.path.join(target_dir, f"{stock_id}_chips_institutional.csv"), index=False, encoding='utf-8-sig')
            if not df_margin.empty:
                df_margin.to_csv(os.path.join(target_dir, f"{stock_id}_chips_margin.csv"), index=False, encoding='utf-8-sig')
            print(f"-> {stock_id} {name} 下載並儲存成功！")
        except Exception as e:
            print(f"-> {stock_id} {name} 下載失敗: {e}")

if __name__ == "__main__":
    main()
