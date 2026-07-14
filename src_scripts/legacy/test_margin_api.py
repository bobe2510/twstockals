import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    date_str = "20260702"
    roc_date = "115/07/02"
    
    # 1. 測試 TSE 融資 API
    url_tse_margin = f"https://www.twse.com.tw/exchangeReport/MI_MARGIN?response=json&date={date_str}&selectType=ALL"
    print("嘗試抓取上市融資明細...")
    try:
        req = urllib.request.Request(url_tse_margin, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            tables = res.get("tables", [])
            print(f"  TSE 融資共包含 {len(tables)} 個表格:")
            for idx, t in enumerate(tables):
                title = t.get("title", "")
                fields = t.get("fields", [])
                rows = t.get("data", [])
                print(f"    表格 {idx}: {title} | 欄位數: {len(fields)} | 資料列數: {len(rows)}")
                if len(rows) > 1000 and "融資今日餘額" in str(fields):
                    print("      --> 發現個股融資餘額表！")
                    print("      欄位:", fields)
                    print("      首筆範例:", rows[0])
    except Exception as e:
        print("  TSE 融資抓取失敗:", e)

    # 2. 測試 TPEx 融資 API
    url_tpex_margin = f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={roc_date}&f=json"
    print("\n嘗試抓取上櫃融資明細...")
    try:
        req = urllib.request.Request(url_tpex_margin, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            tables = res.get("tables", [])
            print(f"  TPEx 融資共包含 {len(tables)} 個表格:")
            for idx, t in enumerate(tables):
                title = t.get("title", "")
                fields = t.get("fields", [])
                rows = t.get("data", [])
                print(f"    表格 {idx}: {title} | 欄位數: {len(fields)} | 資料列數: {len(rows)}")
                if len(rows) > 500:
                    print("      --> 發現個股融資餘額表！")
                    print("      欄位:", fields)
                    print("      首筆範例:", rows[0])
    except Exception as e:
        print("  TPEx 融資抓取失敗:", e)

if __name__ == "__main__":
    main()
