import os
import time
import glob
import sys
import json
from PIL import Image
from google import genai
from google.genai.errors import APIError

# ==========================================
# 設定區
# ==========================================
WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"

def load_api_keys():
    config_path = os.path.join(WORKSPACE, "config", "api_keys.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"載入 API 密鑰設定檔失敗: {e}")
    return {}

API_KEYS = load_api_keys()
GEMINI_API_KEY = API_KEYS.get("GEMINI_API_KEY", "")

# ==========================================
# 初始化 Gemini API (使用新版 google-genai SDK)
# ==========================================
if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("YOUR_"):
    print("錯誤: 找不到有效的 GEMINI_API_KEY，請確認 config/api_keys.json 是否正確設定！")
    sys.exit(1)

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"初始化 Gemini 用戶端失敗: {e}")
    sys.exit(1)

# 使用當前主流且具備免費額度的 gemini-2.5-flash
MODEL_NAME = 'gemini-2.5-flash'

# 報紙多欄位 OCR 提示詞
PROMPT = (
    "這是一張報紙新聞的截圖。由於報紙是多欄位（直欄）分欄排版，請仔細按閱讀順序"
    "（從右到左、從上到下，或依段落邏輯）辨識出完整的文字內容。"
    "請直接輸出整篇新聞的完整文字內容，保留原本的段落結構，不要加入任何額外的解釋、問候語 or Markdown 語法。"
)

def process_image(img_path):
    """將單張圖片發送給 Gemini 進行 OCR 辨識，包含自動重試機制"""
    max_retries = 5
    base_delay = 15  # 第一次重試等 15 秒，第二次等 30 秒，依此類推
    
    for attempt in range(1, max_retries + 1):
        try:
            img = Image.open(img_path)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[PROMPT, img]
            )
            return response.text
        except APIError as ae:
            # 判斷是否為暫時性錯誤 (503 忙碌 或 429 頻率限制)
            is_transient = ae.code in [503, 429] or "high demand" in str(ae).lower() or "resource exhausted" in str(ae).lower()
            
            if is_transient and attempt < max_retries:
                delay = base_delay * attempt
                print(f"\n[API 暫時忙碌] 伺服器回應: {ae.message or ae}")
                print(f"-> 將在 {delay} 秒後進行第 {attempt} 次重試...")
                time.sleep(delay)
                continue
            else:
                print(f"\n[API 錯誤] 處理 {os.path.basename(img_path)} 失敗 (已重試 {attempt} 次): {ae}")
                return None
        except Exception as e:
            print(f"\n[系統錯誤] 處理 {os.path.basename(img_path)} 時發生意外錯誤: {e}")
            return None
    return None

def main():
    workspace = WORKSPACE
    news_dir = os.path.join(workspace, "raw_collected_news")
    
    # 支援透過命令列引數指定特定資料夾，例如 python src_scripts/ocr_helper.py 20260706
    if len(sys.argv) > 1:
        target_dirs = [sys.argv[1]]
    else:
        # 如果未指定，則掃描 raw_collected_news 下的所有子資料夾
        if os.path.exists(news_dir):
            target_dirs = [d for d in os.listdir(news_dir) if os.path.isdir(os.path.join(news_dir, d))]
            target_dirs.sort()
        else:
            target_dirs = []
            
    total_processed = 0
    total_skipped = 0
    
    print("=" * 60)
    print("  台股新聞圖片 OCR 自動辨識工具 (Gemini 2.5-Flash 重試版)")
    print("=" * 60)
    print(f"新聞快取目錄: {news_dir}")
    
    # 收集所有待處理的圖片
    all_tasks = []
    for d in target_dirs:
        dir_path = os.path.join(news_dir, d)
        if not os.path.isdir(dir_path):
            continue
        jpg_files = glob.glob(os.path.join(dir_path, "*.jpg"))
        for f in jpg_files:
            txt_file = os.path.splitext(f)[0] + ".txt"
            all_tasks.append((f, txt_file, d))
            
    print(f"共找到 {len(all_tasks)} 張圖片。")
    
    # 開始執行
    for idx, (img_path, txt_path, folder_name) in enumerate(all_tasks, 1):
        filename = os.path.basename(img_path)
        print(f"\n[{idx}/{len(all_tasks)}] 正在處理: {folder_name}/{filename}")
        
        # 檢查是否已處理過
        if os.path.exists(txt_path):
            print(f"-> 跳過 (已存在文字檔: {os.path.basename(txt_path)})")
            total_skipped += 1
            continue
            
        # 進行 OCR
        start_time = time.time()
        text = process_image(img_path)
        
        if text and text.strip():
            # 寫入檔案
            with open(txt_path, 'w', encoding='utf-8') as f_out:
                f_out.write(text.strip())
            elapsed = time.time() - start_time
            print(f"-> 成功！文字已儲存至 {os.path.basename(txt_path)} (耗時 {elapsed:.1f} 秒)")
            total_processed += 1
            
            # 防爆免費額度限制 (15 RPM -> 每 5 秒最多 1 次請求)
            print("等待 5 秒以防超出免費 API 頻率限制...")
            time.sleep(5)
        else:
            print("-> 失敗：連續重試後仍無法取得辨識文字。程式終止。")
            sys.exit(1)
            
    print("\n" + "=" * 60)
    print("  任務執行完畢！")
    print("=" * 60)
    print(f"新處理圖片: {total_processed} 張")
    print(f"已跳過圖片: {total_skipped} 張")
    print("=" * 60)

if __name__ == "__main__":
    main()
