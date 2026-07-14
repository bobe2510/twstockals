import os
import pandas as pd
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def print_kline_levels(code, name):
    kline_path = os.path.join(WORKSPACE, "data", "20260630", f"{code}_kline.csv")
    if not os.path.exists(kline_path):
        print(f"找不到 {code} 的 K 線資料")
        return
        
    df = pd.read_csv(kline_path).sort_values('date').reset_index(drop=True)
    df['5MA'] = df['close'].rolling(5).mean()
    df['10MA'] = df['close'].rolling(10).mean()
    df['20MA'] = df['close'].rolling(20).mean()
    df['60MA'] = df['close'].rolling(60).mean()
    
    df_recent = df.tail(5)
    
    print(f"\n==================== 【{code} {name}】最新均線價格 ====================")
    latest = df.iloc[-1]
    print(f"最新收盤價: {latest['close']} 元")
    print(f"5MA  (週線) : {latest['5MA']:.2f} 元")
    print(f"10MA (雙週): {latest['10MA']:.2f} 元")
    print(f"20MA (月線) : {latest['20MA']:.2f} 元")
    print(f"60MA (季線) : {latest['60MA']:.2f} 元")
    
    print("\n近期 K 線交易明細 (K線高低點與成交量):")
    print(df_recent[['date', 'open', 'max', 'min', 'close', 'Trading_Volume']].to_string(index=False))

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print_kline_levels("3706", "神達")

if __name__ == "__main__":
    main()
