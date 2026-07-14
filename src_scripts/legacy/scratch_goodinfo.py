import requests
import pandas as pd
import sys
import time

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    all_dfs = []
    page = 1
    
    # 1. 循環抓取所有分頁 (直到沒有資料或重複為止)
    while True:
        url = f"https://histock.tw/stock/warrant.aspx?no=2383&p={page}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://histock.tw/stock/2383"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'utf-8'
            if response.status_code != 200:
                break
            
            tables = pd.read_html(response.text)
            if not tables or len(tables[0]) == 0:
                break
            
            df = tables[0]
            # 檢查是否重複
            if page > 1 and all_dfs and df.iloc[0]['代號'] == all_dfs[0].iloc[0]['代號']:
                break
                
            all_dfs.append(df)
            
            # 如果單頁數量太少，說明是最後一頁
            if len(df) < 15:
                break
                
            page += 1
            time.sleep(0.5)
        except Exception as e:
            break
            
    if not all_dfs:
        print("未取得任何權證資料。")
        return
        
    df_all = pd.concat(all_dfs, ignore_index=True)
    
    # 2. 篩選認購權證 (名稱含 '購')
    df_filtered = df_all[df_all['權證'].str.contains('購')].copy()
    
    # 3. 轉換數值型態
    df_filtered['剩餘 天數'] = pd.to_numeric(df_filtered['剩餘 天數'], errors='coerce')
    df_filtered['買價'] = pd.to_numeric(df_filtered['買價'], errors='coerce')
    df_filtered['賣價'] = pd.to_numeric(df_filtered['賣價'], errors='coerce')
    
    # 4. 篩選剩餘天數 > 120 天
    df_filtered = df_filtered[df_filtered['剩餘 天數'] >= 120]
    
    # 5. 篩選有積極造市的 (買賣價不能為 0)
    df_filtered = df_filtered[(df_filtered['買價'] > 0) & (df_filtered['賣價'] > 0)]
    
    # 6. 計算「買賣價差比」: (賣價 - 買價) / 賣價
    # 價差比越低，代表造市商開的買賣價越接近，摩擦成本越小
    df_filtered['價差比(%)'] = ((df_filtered['賣價'] - df_filtered['買價']) / df_filtered['賣價']) * 100
    
    # 7. 篩選優質發行商 (元大、統一、凱基、群益、富邦、國票)
    # 這些發行商造市較有保障
    reputable_issuers = ['元大', '統一', '凱基', '群益', '富邦', '國票', '元富']
    pattern = '|'.join(reputable_issuers)
    df_filtered = df_filtered[df_filtered['權證'].str.contains(pattern)]
    
    # 8. 依「價差比」升序排序 (越小越好)
    df_sorted = df_filtered.sort_values(by='價差比(%)', ascending=True)
    
    print(f"=== 台光電 (2383) 認購權證篩選結果 (剩餘天數 >= 120天，發行商優良，造市積極) ===")
    print(f"總共找到 {len(df_sorted)} 檔符合條件的權證：\n")
    
    # 挑選前 10 檔印出
    cols_to_show = ['權證', '代號', '價格', '買價', '賣價', '價差比(%)', '履約價', '價內外程度', '剩餘 天數']
    print(df_sorted[cols_to_show].head(10).to_string(index=False))

if __name__ == "__main__":
    main()
