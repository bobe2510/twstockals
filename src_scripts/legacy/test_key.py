import sys

try:
    from google import genai
    print("成功匯入最新版 google.genai 套件！")
except ImportError as e:
    print("匯入 google.genai 失敗，請確認套件已安裝成功。")
    print(e)
    sys.exit(1)

# 填入您的金鑰進行測試
API_KEY = ""

print("正在嘗試使用新版 SDK 與 Gemini 進行連線測試...")
try:
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents='Hello! Please reply with "Success" if you can hear me.',
    )
    print("\n[測試結果] 連線成功！")
    print(f"Gemini 回應: {response.text.strip()}")
except Exception as e:
    print("\n[測試結果] 連線失敗！錯誤訊息如下:")
    print(e)
