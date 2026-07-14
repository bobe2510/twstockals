import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    date_str = "20260702"
    
    # 1. 檢查 TSE (證交所) 行情欄位
    url_tse = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    try:
        req = urllib.request.Request(url_tse, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            tables = data.get("tables", [])
            print(f"TSE MI_INDEX 有 {len(tables)} 個表格:")
            for idx, table in enumerate(tables):
                title = table.get("title", "")
                fields = table.get("fields", [])
                total_rows = len(table.get("data", []))
                print(f"  表格 {idx}: {title} | 欄位數: {len(fields)} | 資料列數: {total_rows}")
                if total_rows > 1000: # 這通常是個股收盤行情
                    print("    --> 發現個股收盤行情表！欄位如下:")
                    print("    ", fields)
                    print("    首筆範例:", table.get("data", [])[0])
    except Exception as e:
        print("TSE 欄位檢查失敗:", e)

    # 2. 檢查 TSE (證交所) 法人欄位
    url_tse_inst = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    try:
        req = urllib.request.Request(url_tse_inst, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            fields = data.get("fields", [])
            rows = data.get("data", [])
            print(f"\nTSE T86 三大法人日報 欄位數: {len(fields)} | 資料列數: {len(rows)}")
            print("  欄位如下:")
            print("  ", fields)
            if rows:
                print("  首筆範例:", rows[0])
    except Exception as e:
        print("TSE 法人欄位檢查失敗:", e)

    # 3. 檢查 TPEx (櫃買中心) 行情欄位 (7/2 為民國 115 年 7 月 2 日)
    url_tpex = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/pct_single.php?l=zh-tw&d=115/07/02&se=EW&f=json"
    try:
        req = urllib.request.Request(url_tpex, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            fields = data.get("fields", [])
            rows = data.get("aaData", [])
            print(f"\nTPEx (上櫃) 收盤行情 欄位數: {len(fields)} | 資料列數: {len(rows)}")
            print("  欄位如下:")
            print("  ", fields)
            if rows:
                print("  首筆範例:", rows[0])
    except Exception as e:
        print("TPEx 欄位檢查失敗:", e)

    # 4. 檢查 TPEx (櫃買中心) 法人欄位
    url_tpex_inst = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d=115/07/02&se=EW&f=json"
    try:
        req = urllib.request.Request(url_tpex_inst, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
            # fields can be hardcoded or parsed
            rows = data.get("aaData", [])
            print(f"\nTPEx (上櫃) 三大法人日報 資料列數: {len(rows)}")
            if rows:
                print("  首筆範例:", rows[0])
    except Exception as e:
        print("TPEx 法人欄位檢查失敗:", e)

if __name__ == "__main__":
    main()
