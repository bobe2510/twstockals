import os
import pandas as pd
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    data_dir = os.path.join(WORKSPACE, "data", "20260702")
    
    # 搜尋大盤相關檔案
    files = os.listdir(data_dir)
    taiex_file = None
    for f in files:
        if "taiex" in f.lower() or "t00" in f.lower() or "加權" in f.lower():
            taiex_file = f
            break
            
    if not taiex_file:
        print("錯誤：找不到大盤 TAIEX 的 K線資料檔")
        print(f"現有檔案: {files[:10]}")
        return
        
    df = pd.read_csv(os.path.join(data_dir, taiex_file)).sort_values('date').reset_index(drop=True)
    df['20MA'] = df['close'].rolling(20).mean()
    df['5MA'] = df['close'].rolling(5).mean()
    
    latest = df.iloc[-1]
    close = float(latest['close'])
    ma20 = float(latest['20MA'])
    ma5 = float(latest['5MA'])
    
    # 夜盤收盤價
    night_close = 45668.0
    
    print("\n==================== 【大盤 TAIEX】7/2 盤後與夜盤對照 ====================")
    print(f"7/2 現貨收盤價  : {close:.2f} 元")
    print(f"7/2 現貨 20MA (月線): {ma20:.2f} 元 (乖離: {((close-ma20)/ma20*100):+.2f}%)")
    print(f"7/2 現貨 5MA (週線) : {ma5:.2f} 元")
    print(f"7/2 夜盤收盤價  : {night_close:.2f} 元")
    
    # 模擬今日開盤
    sim_bias = ((night_close - ma20) / ma20) * 100
    print(f"今日 (7/3) 模擬開盤乖離: {sim_bias:+.2f}%")
    
    if night_close < ma20:
        print("\n🚨🚨🚨 警報：今日模擬開盤價 (45,668) 已正式『跌破 20MA 月線 ({ma20:.2f})』！")
        print("👉 觸發黑天鵝防衛機制！依據大盤多空濾網，建議：")
        print("   1. 將持股總成數降低至 40% 以下。")
        print("   2. 暫停所有波段/突破買進策略。")
        print("   3. 避開外資持股比大於 40% 的個股（外資逃跑地雷）。")
    else:
        print("\n🟢 大盤安全：夜盤收盤 (45,668) 仍守在 20MA 月線 ({ma20:.2f}) 之上，月線支撐尚存。")

if __name__ == "__main__":
    main()
