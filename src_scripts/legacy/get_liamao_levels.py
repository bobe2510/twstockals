import os
import pandas as pd
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    kline_path = os.path.join(WORKSPACE, "data", "20260701", "6213_kline.csv")
    if not os.path.exists(kline_path):
        print("找不到 6213 聯茂的 K 線資料")
        return
        
    df = pd.read_csv(kline_path).sort_values('date').reset_index(drop=True)
    df['5MA'] = df['close'].rolling(5).mean()
    df['10MA'] = df['close'].rolling(10).mean()
    df['20MA'] = df['close'].rolling(20).mean()
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    print("\n==================== 【6213 聯茂】7/1 最新盤後數據 ====================")
    print(f"7/1 收盤價  : {latest['close']} 元")
    print(f"7/1 盤中最高: {latest['max']} 元")
    print(f"7/1 盤中最低: {latest['min']} 元")
    print(f"5MA  (週線) : {latest['5MA']:.2f} 元 (前一日 5MA: {prev['5MA']:.2f} 元)")
    print(f"10MA (雙週): {latest['10MA']:.2f} 元")
    print(f"20MA (月線) : {latest['20MA']:.2f} 元 (乖離率: {((latest['close']-latest['20MA'])/latest['20MA']*100):+.2f}%)")
    
    print("\n近 3 日交易明細:")
    print(df.tail(3)[['date', 'open', 'max', 'min', 'close', 'Trading_Volume']])

if __name__ == "__main__":
    main()
