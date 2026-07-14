import sys
import json
import urllib.request
import os

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
sys.path.append(WORKSPACE)
from analyze_stocks_risk_reward import load_tracked_stocks

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    stocks = load_tracked_stocks()
    symbols_to_query = []
    for s in stocks:
        code = s["code"]
        prefix = s["market"].lower()
        symbols_to_query.append(f"{prefix}_{code}.tw")
    symbols_to_query.append("tse_t00.tw")
    
    ex_ch_str = "|".join(symbols_to_query)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}"
    
    print(f"查詢 URL 長度: {len(url)}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            msg_array = res.get("msgArray", [])
            print(f"API 回傳標的數量: {len(msg_array)}")
            
            realtime_prices = {}
            for stock in msg_array:
                code = stock.get("c")
                if code == "t00":
                    z_val = stock.get("z", "")
                    realtime_prices["TAIEX"] = float(z_val) if z_val != "-" and z_val != "" else float(stock.get("b", "0").split("_")[0])
                else:
                    z_val = stock.get("z", "-")
                    if z_val != "-" and z_val != "":
                        realtime_prices[code] = float(z_val)
                    else:
                        b_val = stock.get("b", "-")
                        if b_val != "-" and b_val != "":
                            realtime_prices[code] = float(b_val.split("_")[0])
            
            print("\n對接結果：")
            for s in stocks[:5]:
                print(f"  股號: {s['code']} {s['name']} -> 即時價: {realtime_prices.get(s['code'])}")
            print(f"  股號: 3484 崧騰 -> 即時價: {realtime_prices.get('3484')}")
            print(f"  大盤 TAIEX -> 即時價: {realtime_prices.get('TAIEX')}")
            
    except Exception as e:
        print("查詢發生異常:", e)

if __name__ == "__main__":
    main()
