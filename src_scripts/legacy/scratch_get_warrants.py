import requests
import pandas as pd
import json

def main():
    # 嘗試從證交所或公開財經來源獲取權證列表
    # 我們使用一個公開且免 API key 的權證資料來源（例如鉅亨網或玩股網的公開 API）
    # 這裡我們使用鉅亨網的權證搜尋 API，它是非常穩定且公開的
    url = "https://warrant.anuehtml.com/api/v1/warrants"
    
    # 鉅亨網的權證篩選參數
    # 標的為台光電 (2383)，類型為認購 (Call)
    params = {
        "underlyingId": "2383",
        "warrantType": "1", # 1 通常代表認購
        "page": 1,
        "pageSize": 100
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            warrants = data.get("data", {}).get("items", [])
            print(f"成功取得 {len(warrants)} 檔台光電權證")
            if warrants:
                print(json.dumps(warrants[0], indent=2, ensure_ascii=False))
        else:
            print(f"請求失敗，狀態碼: {response.status_code}")
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    main()
