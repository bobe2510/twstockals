import os
import json
import sys
from datetime import datetime, timedelta
import pandas as pd
from FinMind.data import DataLoader

# ==========================================
# 設定區
# ==========================================
WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def load_api_keys():
    config_path = os.path.join(WORKSPACE, "config", "api_keys.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"載入 API 密鑰設定檔失敗: {e}")
    return {}

API_KEYS = load_api_keys()
FINMIND_TOKENS = API_KEYS.get("FINMIND_TOKENS", [])

# ==========================================
# Token 輪替管理器
# ==========================================
class TokenRotator:
    def __init__(self, tokens):
        self.tokens = [t for t in tokens if t.strip()]
        self.current_idx = 0
        self.api = DataLoader()
        self.login_current()
        
    def login_current(self):
        if not self.tokens:
            print("未設定任何 Token，將以免費限制模式運行。")
            return
        token = self.tokens[self.current_idx]
        masked = token[:12] + "..." + token[-12:] if len(token) > 24 else token
        try:
            self.api.login_by_token(api_token=token)
            print(f"FinMind Token 登入成功 [{self.current_idx + 1}/{len(self.tokens)}]: {masked}")
        except Exception as e:
            print(f"Token 登入失敗: {e}")
            self.rotate()

    def rotate(self):
        if not self.tokens or len(self.tokens) <= 1:
            return False
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
        print(f"\n⚠️ 偵測到額度上限或登入失效，自動輪替至第 {self.current_idx + 1} 組 Token...")
        self.login_current()
        return True

    def get_api(self):
        return self.api

# 初始化輪替器
rotator = TokenRotator(FINMIND_TOKENS)

def fetch_with_rotation(rotator, func_name, *args, **kwargs):
    max_retries = max(1, len(rotator.tokens))
    for attempt in range(max_retries):
        try:
            api_func = getattr(rotator.get_api(), func_name)
            return api_func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            if "limit" in err_msg.lower() or "reach the upper limit" in err_msg.lower() or "illegal" in err_msg.lower():
                print(f"-> 目前 Token 發生錯誤 (額度已滿或無效): {err_msg}")
                if rotator.rotate():
                    print("-> 已切換 Token，重新嘗試下載...")
                    continue
            raise e

def get_target_stocks():
    """從 my_targets.json 和 social_picks.json 讀取所有需下載的個股清單"""
    stocks = []
    seen = set()
    
    # 1. 載入個人持股與觀察股
    targets_path = os.path.join(WORKSPACE, "config", "my_targets.json")
    if os.path.exists(targets_path):
        try:
            with open(targets_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data.get("portfolio", []):
                code = item["code"]
                if code not in seen:
                    seen.add(code)
                    stocks.append({"code": code, "name": item.get("name", ""), "market": "TSE"})
            for item in data.get("watchlist", []):
                code = item["code"]
                if code not in seen:
                    seen.add(code)
                    stocks.append({"code": code, "name": item.get("name", ""), "market": "TSE"})
        except Exception as e:
            print("讀取 my_targets.json 失敗:", e)
            
    # 2. 載入社群追蹤股
    social_picks_path = os.path.join(WORKSPACE, "config", "social_picks.json")
    if os.path.exists(social_picks_path):
        try:
            with open(social_picks_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data.get("tracked_stocks", []):
                code = item["code"]
                if code not in seen:
                    seen.add(code)
                    stocks.append({"code": code, "name": item.get("name", ""), "market": item.get("market", "TSE")})
        except Exception as e:
            print("讀取 social_picks.json 失敗:", e)
            
    return stocks

def main():
    # 1. 取得需要下載的個股列表
    stocks = get_target_stocks()
    if not stocks:
        print("沒有設定任何追蹤或社群個股。")
        return
        
    # 2. 判定日期：支援傳參，如 python fetch_stock_data.py 20260703
    if len(sys.argv) > 1 and len(sys.argv[1]) == 8 and sys.argv[1].isdigit():
        today_str = sys.argv[1]
        end_date = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}"
    else:
        now = datetime.now()
        today_str = now.strftime("%Y%m%d")
        end_date = now.strftime("%Y-%m-%d")
        
    target_dir = os.path.join(WORKSPACE, "market_crawled_cache", today_str)
    os.makedirs(target_dir, exist_ok=True)
    
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    
    print("=" * 60)
    print(f"  台股數據自動收集工具 (FinMind)")
    print("=" * 60)
    print(f"目標資料夾: {target_dir}")
    print(f"抓取區間  : {start_date} ~ {end_date}")
    print(f"個股總數  : {len(stocks)} 檔")
    print("=" * 60)
    
    success_count = 0
    
    # 下載大盤指數 (TAIEX) 的 K 線資料
    print("正在下載大盤加權指數 (TAIEX) 資料...")
    try:
        start_date_taiex = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=360)).strftime("%Y-%m-%d")
        df_taiex = fetch_with_rotation(
            rotator, 'taiwan_stock_daily',
            stock_id='TAIEX',
            start_date=start_date_taiex,
            end_date=end_date
        )
        if not df_taiex.empty:
            df_taiex.to_csv(os.path.join(target_dir, "TAIEX_kline.csv"), index=False, encoding="utf-8-sig")
            print("大盤加權指數 (TAIEX) 資料下載成功。")
    except Exception as e:
        print(f"警告: 大盤加權指數 (TAIEX) 資料下載失敗: {e}")

    # 3. 逐一抓取股票數據
    for idx, stock in enumerate(stocks, 1):
        stock_id = stock["code"]
        stock_name = stock["name"]
        market = stock["market"]
        
        if market == "US":
            continue
            
        # 檢查是否已存在快取檔案
        kline_path = os.path.join(target_dir, f"{stock_id}_kline.csv")
        inst_path = os.path.join(target_dir, f"{stock_id}_chips_institutional.csv")
        margin_path = os.path.join(target_dir, f"{stock_id}_chips_margin.csv")
        
        if os.path.exists(kline_path) and os.path.exists(inst_path) and os.path.exists(margin_path):
            print(f"[{idx}/{len(stocks)}] 跳過: {stock_id} {stock_name} (已存在快取資料)")
            success_count += 1
            continue
            
        print(f"[{idx}/{len(stocks)}] 正在下載: {stock_id} {stock_name}...")
        
        try:
            # A. 下載日 K 線價格資料
            df_kline = fetch_with_rotation(
                rotator, 'taiwan_stock_daily',
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # B. 下載三大法人買賣超
            df_inst = fetch_with_rotation(
                rotator, 'taiwan_stock_institutional_investors',
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # C. 下載融資融券餘額
            df_margin = fetch_with_rotation(
                rotator, 'taiwan_stock_margin_purchase_short_sale',
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # 儲存為 CSV
            if not df_kline.empty:
                df_kline.to_csv(os.path.join(target_dir, f"{stock_id}_kline.csv"), index=False, encoding='utf-8-sig')
            if not df_inst.empty:
                df_inst.to_csv(os.path.join(target_dir, f"{stock_id}_chips_institutional.csv"), index=False, encoding='utf-8-sig')
            if not df_margin.empty:
                df_margin.to_csv(os.path.join(target_dir, f"{stock_id}_chips_margin.csv"), index=False, encoding='utf-8-sig')
                
            success_count += 1
            
        except Exception as e:
            print(f"-> 下載 {stock_id} 失敗: {e}")
            
    print("\n" + "=" * 60)
    print(f"數據收集完畢！成功下載 {success_count} 檔台股的最新 K線與籌碼數據。")
    print(f"快取路徑: {target_dir}")
    print("=" * 60)

if __name__ == "__main__":
    main()
