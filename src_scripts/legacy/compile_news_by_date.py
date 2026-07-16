import os
import glob
import sys
from datetime import datetime

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def compile_news_for_date(date_str):
    news_dir = os.path.join(WORKSPACE, "raw_collected_news", date_str)
    if not os.path.isdir(news_dir):
        print(f"錯誤: 找不到資料夾 {news_dir}")
        return False
        
    output_local = os.path.join(news_dir, "compiled_news.txt")
    output_root = os.path.join(WORKSPACE, "compiled_news.txt")
    
    # 讀取 news.txt (LINE 訊息摘要)
    lines = []
    lines.append("============================================================")
    lines.append(f"  📅 日期資料夾: {date_str}")
    lines.append("============================================================\n")
    
    news_txt_path = os.path.join(news_dir, "news.txt")
    if os.path.exists(news_txt_path):
        lines.append("--- 📌 [LINE 訊息摘要] news.txt ---")
        try:
            with open(news_txt_path, 'r', encoding='utf-8', errors='ignore') as nf:
                lines.append(nf.read().strip())
        except Exception as e:
            lines.append(f"(讀取 news.txt 失敗: {e})")
        lines.append("\n")
        
    # 讀取其他圖片轉出來的 txt
    txt_files = glob.glob(os.path.join(news_dir, "*.txt"))
    for tf in sorted(txt_files):
        basename = os.path.basename(tf)
        if basename in ["news.txt", "compiled_news.txt"]:
            continue
        lines.append(f"--- 📄 [圖片新聞/圖表] {basename} ---")
        try:
            with open(tf, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().strip()
                lines.append(content if content else "(無內容)")
        except Exception as e:
            lines.append(f"(讀取 {basename} 失敗: {e})")
        lines.append("\n")
        
    compiled_content = "\n".join(lines) + "\n"
    
    # 寫入本機資料夾的 compiled_news.txt
    try:
        with open(output_local, 'w', encoding='utf-8') as f:
            f.write(compiled_content)
        print(f"本地整合完成！已儲存至: raw_collected_news/{date_str}/compiled_news.txt")
    except Exception as e:
        print(f"寫入本地整合檔案失敗: {e}")
        return False
        
    # 附加至根目錄的 compiled_news.txt
    try:
        # 先檢查是否已經附加過 (防重覆)
        already_appended = False
        if os.path.exists(output_root):
            with open(output_root, 'r', encoding='utf-8', errors='ignore') as f:
                root_content = f.read()
                if f"📅 日期資料夾: {date_str}" in root_content:
                    already_appended = True
                    
        if already_appended:
            print(f"提示: 根目錄 compiled_news.txt 中已存在 {date_str} 的整合資料，跳過附加以免重覆。")
        else:
            with open(output_root, 'a', encoding='utf-8') as f:
                # 確保前有換行
                f.write("\n" + compiled_content)
            print(f"根目錄整合成功！已附加至: compiled_news.txt")
    except Exception as e:
        print(f"附加至根目錄 compiled_news.txt 失敗: {e}")
        return False
        
    return True

def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        
    print(f"開始整合 {date_str} 的新聞文字檔案...")
    compile_news_for_date(date_str)

if __name__ == "__main__":
    main()
