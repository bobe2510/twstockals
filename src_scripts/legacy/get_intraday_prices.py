import urllib.request
import json
import sys

def get_realtime_prices(symbols):
    ex_ch_list = ["tse_t00.tw"]
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
    
    # 查詢標的 [(代號, 市場)]
    symbols = [
        ("00631L", "TSE"), # 正2
        ("00632R", "TSE"), # 反1
        ("3483", "TSE"),   # 力致
        ("6191", "TSE"),   # 精成科
        ("3706", "TSE"),   # 神達
        ("5469", "TSE"),   # 瀚宇博
        ("00687B", "TSE")  # 國泰美債
    ]
    
    msg_array = get_realtime_prices(symbols)
    
    print("\n==================== 【7/3 09:39 盤中即時報價快照】 ====================")
    for stock in msg_array:
        code = stock.get("c")
        name = stock.get("n", "").strip()
        if code == "t00":
            name = "加權指數"
            
        try:
            prev_close = float(stock.get("y", 0.0))
            z_val = stock.get("z", "-")
            if z_val != "-" and z_val != "":
                current_price = float(z_val)
            else:
                # 盤中若暫無成交，以最高買進申報價代替
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
