import os
import glob
import sys
import re

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
    txt_files = glob.glob(os.path.join(WORKSPACE, "20260701", "*.txt"))
    
    print("=== 7/1 新聞焦點與提及個股代號一覽 ===")
    for tf in sorted(txt_files):
        filename = os.path.basename(tf)
        with open(tf, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 提取股票代號（排除年份如2026、2027、2028）
        all_codes = re.findall(r'\b\d{4}\b', content)
        filtered_codes = list(set([c for c in all_codes if c not in ['2025', '2026', '2027', '2028', '2029', '2030']]))
        
        # 清理換行以方便閱讀摘要
        clean_content = content.strip().replace('\r\n', ' ').replace('\n', ' ')
        summary = clean_content[:300]
        
        print(f"\n[📄 {filename}] | 關係股代碼: {filtered_codes}")
        print(f"👉 內容摘要: {summary}...")
        print("-" * 80)

if __name__ == "__main__":
    main()
