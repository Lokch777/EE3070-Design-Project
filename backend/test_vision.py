import os
import sys
import requests
import base64
from dotenv import load_dotenv, find_dotenv

# 1. 尋找並載入 .env
env_path = find_dotenv(usecwd=True) 
load_dotenv(env_path)

API_KEY = os.getenv("VISION_API_KEY")
MODEL = os.getenv("VISION_MODEL")
ENDPOINT = os.getenv("VISION_ENDPOINT")

# 自動幫國際版端點補上 /chat/completions (OpenAI 相容格式)
if ENDPOINT and not ENDPOINT.endswith("/chat/completions"):
    ENDPOINT = f"{ENDPOINT.rstrip('/')}/chat/completions"

print(f"🔑 API Key: {'✅ 已讀取' if API_KEY else '❌ 還是空的'}")
print(f"🧠 模型名稱: {MODEL}")
print(f"🌐 API 端點: {ENDPOINT}")
print("-" * 50)

if not API_KEY or not MODEL:
    print("❌ 錯誤：請確認 .env 檔案裡有 VISION_API_KEY 和 VISION_MODEL！")
    sys.exit(1)

# 2. 從終端機指令獲取圖片路徑
if len(sys.argv) < 2:
    print("❌ 錯誤：請提供圖片檔案名稱！")
    print("👉 範例用法：python3 test_vision.py 你的圖片名稱.png")
    sys.exit(1)

image_path = sys.argv[1]

if not os.path.exists(image_path):
    print(f"❌ 錯誤：找不到圖片 '{image_path}'，請檢查路徑或檔名是否正確！")
    sys.exit(1)

print(f"🖼️ 正在讀取圖片: {image_path} ...")
with open(image_path, "rb") as image_file:
    base64_image = base64.b64encode(image_file.read()).decode('utf-8')

# 3. 使用 OpenAI 相容格式打包 Request
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64_image}"
                    }
                },
                {
                    "type": "text",
                    "text": "你是一個視障人士的輔助眼鏡，請用簡短、口語的中文描述你看到了什麼。"
                }
            ]
        }
    ]
}

# 4. 發送請求
print("🚀 正在透過 API 傳送給 Qwen 模型分析中，請稍候...")
try:
    response = requests.post(ENDPOINT, headers=headers, json=payload)
    response.raise_for_status()
    result = response.json()
    
    # 解析 OpenAI 格式的回傳結果
    vision_text = result['choices'][0]['message']['content']
    print("\n✅ AI 辨識成功！結果如下：")
    print("=" * 50)
    print(vision_text)
    print("=" * 50)
    
except Exception as e:
    print(f"\n❌ API 測試失敗: {e}")
    if 'response' in locals():
        print(f"詳細錯誤訊息: {response.text}")
