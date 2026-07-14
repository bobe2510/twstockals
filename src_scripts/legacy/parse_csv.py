import pandas as pd
import sys

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    file_path = r"g:\我的雲端硬碟\dev\twstockals\WarInfo_20260630_165432.csv"
    
    try:
        df = pd.read_csv(file_path, encoding='big5')
    except Exception as e:
        print(f"讀取失敗: {e}")
        return
        
    new_cols = [
        "權證代碼", "權證名稱", "權證成交價", "權證漲跌", "權證漲跌幅", "權證成交量", 
        "履約價", "行使比例", "距到期天數", "價內外程度", "買賣價差比", "實質槓桿", 
        "成交價隱波(%)", "流通在外比率(%)", "到期日期", "THETA", "買價隱波(%)", "賣價隱波(%)", "其他"
    ]
    
    if len(df.columns) <= len(new_cols):
        df.columns = new_cols[:len(df.columns)]
        
    df['距到期天數'] = pd.to_numeric(df['距到期天數'], errors='coerce')
    df['買價隱波(%)'] = pd.to_numeric(df['買價隱波(%)'], errors='coerce')
    df['賣價隱波(%)'] = pd.to_numeric(df['賣價隱波(%)'], errors='coerce')
    df['權證成交量'] = pd.to_numeric(df['權證成交量'], errors='coerce').fillna(0)
    df['買賣價差比'] = pd.to_numeric(df['買賣價差比'], errors='coerce').fillna(999.0)
    df['流通在外比率(%)'] = pd.to_numeric(df['流通在外比率(%)'], errors='coerce').fillna(0.0)
    
    # === 篩選條件 ===
    # 1. 剩餘天數 >= 120 天
    df_filtered = df[df['距到期天數'] >= 120].copy()
    
    # 2. 確保有在造市 (隱波有數字)
    df_filtered = df_filtered[(df_filtered['買價隱波(%)'] > 10) & (df_filtered['賣價隱波(%)'] > 10)]
    
    # 3. 排除流動性鎖死：流通在外比例 < 80%
    df_filtered = df_filtered[df_filtered['流通在外比率(%)'] < 80.0]
    
    # 4. 排除隱波價差過大的剝皮權證
    df_filtered['隱波價差'] = df_filtered['賣價隱波(%)'] - df_filtered['買價隱波(%)']
    
    # 5. 強制條件：今日必須有實際成交量 (成交量 >= 1)
    df_volume = df_filtered[df_filtered['權證成交量'] >= 1.0].copy()
    
    # 依「隱波價差」由低到高排序 (越低越公道)，再依「買價隱波」排序
    df_volume_sorted = df_volume.sort_values(by=['隱波價差', '買價隱波(%)'], ascending=[True, True])
    
    print("\n" + "="*110)
    print("🎯 台光電 (2383) 認購權證篩選（條件：天期 >= 120天、今日有成交量、排除隱波剝皮陷阱）")
    print("="*110)
    
    cols_show = ["權證代碼", "權證名稱", "權證成交價", "權證成交量", "買價隱波(%)", "賣價隱波(%)", "隱波價差", "買賣價差比", "流通在外比率(%)", "履約價", "距到期天數", "到期日期"]
    print(df_volume_sorted[cols_show].to_string(index=False))

if __name__ == "__main__":
    main()
