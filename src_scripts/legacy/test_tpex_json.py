import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    roc_date = "115/07/02" # 2026-07-02
    
    # 測試 1: 上櫃收盤行情結果
    url_price = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date}&s=0,asc,0&o=json"
    print(f"嘗試抓取上櫃歷史收盤行情 JSON: {url_price} ...")
    try:
        req = urllib.request.Request(url_price, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            print("  [成功] 欄位包括:", list(res.keys()))
            rows = res.get("aaData", [])
            print(f"  [成功] 資料筆數: {len(rows)}")
            if rows:
                print("  [成功] 首筆範例:", rows[0])
    except Exception as e:
        print("  [失敗]:", e)

    # 測試 2: 上櫃三大法人買賣超
    url_inst = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date}&se=EW&t=D&o=json"
    print(f"\n嘗試抓取上櫃歷史三大法人日報 JSON: {url_inst} ...")
    try:
        req = urllib.request.Request(url_inst, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
            print("  [成功] 欄位包括:", list(res.keys()))
            rows = res.get("aaData", [])
            print(f"  [成功] 資料筆數: {len(rows)}")
            if rows:
                print("  [成功] 首筆範例:", rows[0])
    except Exception as e:
        print("  [失敗]:", e)

if __name__ == "__main__":
    main()
