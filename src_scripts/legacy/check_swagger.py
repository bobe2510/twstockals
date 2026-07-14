import requests
import json

def main():
    url = "https://openapi.twse.com.tw/v1/swagger.json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            swagger = response.json()
            paths = swagger.get("paths", {})
            warrant_paths = [p for p in paths.keys() if "warrant" in p.lower() or "權證" in p]
            print(f"找到 {len(warrant_paths)} 個權證相關 API 端點:")
            for p in warrant_paths:
                summary = paths[p].get("get", {}).get("summary", "無說明")
                print(f"- {p} ({summary})")
        else:
            print(f"下載失敗: {response.status_code}")
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    main()
