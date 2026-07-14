import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    date_str = "20260702"
    
    # 1. 測試證交所 (TSE) 全市場收盤行情
    url_tse_price = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    print(f"嘗試抓取證交所全市場行情: {url_tse_price} ...")
    try:
        req = urllib.request.Request(url_tse_price, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            stat = data.get("stat", "")
            if stat == "OK":
                # tables are typically in fields like "tables" or "data9" (for closing prices)
                # Let's see keys
                print("  抓取成功！回傳欄位包含:", list(data.keys()))
                # MI_INDEX 的個股收盤行情通常在 data9 或 tables[8]
                data_key = "data9" if "data9" in data else "tables"
                print("  資料格式確認OK，有資料欄位。")
            else:
                print("  Stat 狀態不為 OK:", stat)
    except Exception as e:
        print("  抓取失敗:", e)

    # 2. 測試證交所 (TSE) 全市場三大法人日報
    url_tse_inst = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    print(f"\n嘗試抓取證交所三大法人買賣超日報: {url_tse_inst} ...")
    try:
        req = urllib.request.Request(url_tse_inst, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            stat = data.get("stat", "")
            if stat == "OK":
                print("  抓取成功！回傳欄位包含:", list(data.keys()))
            else:
                print("  Stat 狀態不為 OK:", stat)
    except Exception as e:
        print("  抓取失敗:", e)

if __name__ == "__main__":
    main()
