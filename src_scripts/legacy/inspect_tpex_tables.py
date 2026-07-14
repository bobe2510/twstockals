import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    roc_date = "115/07/02" # 2026-07-02
    
    # 1. 解讀上櫃收盤行情
    url_price = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date}&s=0,asc,0&o=json"
    try:
        req = urllib.request.Request(url_price, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            tables = res.get("tables", [])
            print(f"TPEx 收盤行情共包含 {len(tables)} 個表格:")
            for idx, t in enumerate(tables):
                title = t.get("title", "")
                fields = t.get("fields", [])
                rows = t.get("data", [])
                print(f"  表格 {idx}: {title} | 欄位數: {len(fields)} | 資料列數: {len(rows)}")
                if len(rows) > 500:
                    print("    --> 發現個股收盤行情表！")
                    print("    欄位:", fields)
                    print("    首筆範例:", rows[0])
    except Exception as e:
        print("解讀上櫃行情失敗:", e)

    # 2. 解讀上櫃三大法人
    url_inst = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date}&se=EW&t=D&o=json"
    try:
        req = urllib.request.Request(url_inst, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            tables = res.get("tables", [])
            print(f"\nTPEx 法人日報共包含 {len(tables)} 個表格:")
            for idx, t in enumerate(tables):
                title = t.get("title", "")
                fields = t.get("fields", [])
                rows = t.get("data", [])
                print(f"  表格 {idx}: {title} | 欄位數: {len(fields)} | 資料列數: {len(rows)}")
                if len(rows) > 100:
                    print("    --> 發現三大法人買賣超表！")
                    print("    欄位:", fields)
                    print("    首筆範例:", rows[0])
    except Exception as e:
        print("解讀上櫃法人失敗:", e)

if __name__ == "__main__":
    main()
