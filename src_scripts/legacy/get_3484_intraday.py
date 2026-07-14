import urllib.request
import json
import sys

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_3484.tw"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res = response.read().decode('utf-8')
            data = json.loads(res)
            stock = data.get("msgArray", [])[0]
            prev = float(stock.get("y", 0.0))
            z_val = stock.get("z", "-")
            if z_val != "-" and z_val != "":
                current = float(z_val)
            else:
                b_val = stock.get("b", "-")
                current = float(b_val.split("_")[0]) if b_val != "-" and b_val != "" else prev
                
            print(f"\n==================== 【3484 崧騰】7/3 盤中即時查價 ====================")
            print(f"現價: {current:.2f} 元")
            print(f"昨收: {prev:.2f} 元")
            print(f"漲跌: {current - prev:+.2f} ({((current - prev)/prev*100):+.2f}%)")
            print(f"最低: {stock.get('l')}")
            print(f"最高: {stock.get('h')}")
    except Exception as e:
        print(f"查詢失敗: {e}")

if __name__ == "__main__":
    main()
