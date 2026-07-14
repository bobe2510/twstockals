import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    swagger_url = "https://www.tpex.org.tw/openapi/swagger.json"
    print("下載櫃買中心 Swagger API 規格書...")
    try:
        req = urllib.request.Request(swagger_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            spec = json.loads(r.read().decode('utf-8'))
            
        paths = spec.get("paths", {})
        print(f"共發現 {len(paths)} 個 API 端點！")
        
        # 搜尋關鍵字
        keywords = ["close", "quotes", "daily", "trading", "3insti"]
        matches = []
        for path in paths:
            for kw in keywords:
                if kw in path.lower():
                    matches.append((path, paths[path]))
                    break
                    
        print("\n篩選出相關的上櫃資料 API 端點:")
        for path, info in matches[:15]:
            # 取得 description 或 summary
            get_info = info.get("get", {})
            summary = get_info.get("summary", "無摘要")
            parameters = get_info.get("parameters", [])
            param_names = [p.get("name") for p in parameters]
            print(f"  端點: {path}")
            print(f"    說明: {summary}")
            print(f"    參數: {param_names}")
            
    except Exception as e:
        print("Swagger 解析失敗:", e)

if __name__ == "__main__":
    main()
