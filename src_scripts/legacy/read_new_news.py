import os
import glob
import sys

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
    txt_files = glob.glob(os.path.join(WORKSPACE, "20260701", "*.txt"))
    print(f"找到 {len(txt_files)} 個 7/1 新聞文字檔：\n")
    for tf in sorted(txt_files):
        print(f"==================== 【{os.path.basename(tf)}】 ====================")
        with open(tf, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            print(content)
        print("\n")

if __name__ == "__main__":
    main()
