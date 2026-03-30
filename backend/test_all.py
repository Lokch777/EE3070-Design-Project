import requests
import time
import os
import sys

# ===== 設定區 =====
# 假設你的 FastAPI 上傳路由是 /api/upload (若有不同請自行修改)
SERVER_URL = "http://127.0.0.1:8080/api/upload_image" 

# 請在同一個資料夾放一張真正的圖片，命名為 test.jpg
IMAGE_PATH = "test.jpg" 
# =================

def run_test():
    if not os.path.exists(IMAGE_PATH):
        print(f"⚠️ 找不到測試圖片：{IMAGE_PATH}")
        print("💡 請在資料夾中放一張真實的照片並命名為 'test.jpg'！")
        print("這樣 Qwen3-VL 視覺模型才能真的『看到』東西並描述出來。")
        sys.exit(1)

    # 🔑 產生帶有 "test-" 前綴的專屬 ID，這會觸發 app_coordinator.py 的安全捷徑！
    req_id = f"test-{int(time.time())}"
    device_id = "virtual_esp32"

    print(f"🚀 發動全功能端到端測試！")
    print(f"📸 準備傳送圖片: {IMAGE_PATH}")
    print(f"🔑 測試請求 ID: {req_id}")

    try:
        with open(IMAGE_PATH, "rb") as f:
            # 模擬 ESP32 的 multipart/form-data 上傳
            files = {"file": ("test.jpg", f, "image/jpeg")}
            data = {"req_id": req_id, "device_id": device_id}
            
            print("⏳ 正在上傳至伺服器...")
            response = requests.post(SERVER_URL, files=files, data=data)
            
            if response.status_code == 200:
                print("✅ 圖片上傳成功！")
                print(f"伺服器回應: {response.text}")
                print("\n🔥 趕快切換到 main.py 的終端機！")
                print("你應該會看到 Vision 模型開始分析，接著 TTS 開始合成語音！")
            else:
                print(f"❌ 上傳失敗，狀態碼: {response.status_code}")
                print(f"回應內容: {response.text}")
                print("💡 提示：如果出現 404 Not Found，可能是你的上傳 API 不是 /api/upload，請確認 main.py 裡的路由設定。")
                
    except requests.exceptions.ConnectionError:
        print("❌ 無法連線到伺服器！請確認 main.py 是否已經啟動並運行在 8080 port。")

if __name__ == "__main__":
    run_test()
