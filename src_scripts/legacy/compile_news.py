import os
import glob

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
target_dirs = ['20260625', '20260626', '20260628', '20260629', '20260630', '20260701']
output_file = os.path.join(WORKSPACE, "compiled_news.txt")

def main():
    print("正在整合所有新聞文字檔...")
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for d in target_dirs:
            dir_path = os.path.join(WORKSPACE, d)
            if not os.path.isdir(dir_path):
                continue
                
            out_f.write(f"\n============================================================\n")
            out_f.write(f"  📅 日期資料夾: {d}\n")
            out_f.write(f"============================================================\n\n")
            
            # 先寫入 news.txt (LINE 訊息摘要)
            news_txt = os.path.join(dir_path, "news.txt")
            if os.path.exists(news_txt):
                out_f.write(f"--- 📌 [LINE 訊息摘要] news.txt ---\n")
                with open(news_txt, 'r', encoding='utf-8', errors='ignore') as nf:
                    out_f.write(nf.read())
                out_f.write("\n\n")
                
            # 寫入其他圖片轉出來的 txt
            txt_files = glob.glob(os.path.join(dir_path, "*.txt"))
            for tf in sorted(txt_files):
                if os.path.basename(tf) == "news.txt" or os.path.basename(tf) == "compiled_news.txt":
                    continue
                out_f.write(f"--- 📄 [圖片新聞/圖表] {os.path.basename(tf)} ---\n")
                try:
                    with open(tf, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        # 限制長度或直接寫入
                        out_f.write(content if content else "(無內容)")
                except Exception as e:
                    out_f.write(f"(讀取失敗: {e})")
                out_f.write("\n\n")
                
    print(f"整合完成！檔案已儲存至: {output_file}")

if __name__ == "__main__":
    main()
