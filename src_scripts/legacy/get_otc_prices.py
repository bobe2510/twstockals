import urllib.request
import json
import sys

def get_realtime_prices(symbols):
    ex_ch_list = []
    for code, market in symbols:
        prefix = "tse" if market.upper() == "TSE" else "otc"
        ex_ch_list.append(f"{prefix}_{code}.tw")
        
    ex_ch_str = "|".join(ex_ch_list)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}"
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res = response.read().decode('utf-8')
            data = json.loads(res)
            return data.get("msgArray", [])
    except Exception as e:
        print(f"抓取即時報價失敗: {e}")
        return []

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    
    # 修正 力致 3483 與 國泰美債 00687B 為 OTC
    symbols = [
        ("3483", "OTC"),   # 力致 (櫃買)
        ("00687B", "OTC")  # 國泰20年美債 (櫃買)
    ]
    
    msg_array = get_realtime_prices(symbols)
    
    print("\n==================== 【7/3 09:39 OTC 標的即時報價快照】 ====================")
    for stock in msg_array:
        code = stock.get("c")
        name = stock.get("n", "").strip()
        
        try:
            prev_close = float(stock.get("y", 0.0))
            z_val = stock.get("z", "-")
            if z_val != "-" and z_val != "":
                current_price = float(z_val)
            else:
                b_val = stock.get("b", "-")
                if b_val != "-" and b_val != "":
                    current_price = float(b_val.split("_")[0])
                else:
                    current_price = prev_close
                    
            high = float(stock.get("h", 0.0))
            low = float(stock.get("l", 0.0))
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
            
            print(f"🔹 {code:7} {name:12} | 現價: {current_price:9.2f} | 漲跌: {change:+.2f} ({change_pct:+.2f}%) | 盤中最低: {low:.2f} | 昨收: {prev_close:.2f}")
        except Exception as e:
            print(f"解析 {code} 數據時出錯: {e}")

if __name__ == "__main__":
    main()
