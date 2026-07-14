import pandas as pd
import sys

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    file_path = r"g:\我的雲端硬碟\dev\twstockals\WarInfo_20260630_165432.csv"
    
    # 讀取第一行並用 Big5 解碼
    with open(file_path, 'rb') as f:
        first_line = f.readline()
        try:
            headers = first_line.decode('big5').strip().split(',')
            print("=== 解碼後的原始欄位名稱 ===")
            for idx, h in enumerate(headers):
                print(f"欄位 {idx}: {h}")
        except Exception as e:
            print(f"解碼失敗: {e}")

if __name__ == "__main__":
    main()
