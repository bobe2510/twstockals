import sys
import json
import urllib.request

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    swagger_url = "https://openapi.twse.com.tw/v1/swagger.json"
    print("下載證交所 Swagger API 規格書...")
    try:
        req = urllib.request.Request(swagger_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            spec = json.loads(r.read().decode('utf-8'))
            
        paths = spec.get("paths", {})
        print(f"共發現 {len(paths)} 個 API 端點！")
        
        matches = []
        for path in paths:
            if "margin" in path.lower() or "mi_margin" in path.lower() or "fund" in path.lower():
                matches.append((path, paths[path]))
                
        print("\n篩選出相關的上市信用/法人/餘額 API 端點:")
        for path, info in matches[:15]:
            get_info = info.get("get", {})
            summary = get_info.get("summary", "無摘要")
            print(f"  端點: {path}")
            print(f"    說明: {summary}")
            
    except Exception as e:
        print("Swagger 解析失敗:", e)

if __name__ == "__main__":
    main()
