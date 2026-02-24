# ESP32 影像上傳測試指南

## 目標
測試 ESP32 能否將影像傳送到 AWS EC2 並儲存

## 測試方案

### 方案 A：使用 Python 測試腳本（推薦先測試）

這個方法可以快速驗證後端是否正常運作，不需要 ESP32 硬體。

#### 1. 啟動 EC2 後端

```bash
# SSH 連線到 EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# 進入專案目錄
cd backend

# 啟動服務
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

#### 2. 在本機執行測試腳本

```bash
# 安裝依賴
pip install requests websocket-client

# 測試上傳（使用任意 JPG 圖片）
python test_upload.py test.jpg http://your-ec2-ip:8000
```

測試腳本會：
1. 檢查伺服器健康狀態
2. 透過 HTTP POST 上傳影像
3. 透過 WebSocket 上傳影像
4. 顯示上傳結果

### 方案 B：使用 ESP32 實際測試

#### 1. 準備 ESP32-CAM

硬體需求：
- ESP32-CAM 模組
- USB 轉 TTL 燒錄器
- 杜邦線

#### 2. 配置韌體

編輯 `device/esp32_camera_test.ino`：

```cpp
// WiFi 設定
const char* ssid = "你的WiFi名稱";
const char* password = "你的WiFi密碼";

// EC2 伺服器設定
const char* serverHost = "你的EC2公網IP";  // 例如 "54.123.45.67"
const int serverPort = 8000;
```

#### 3. 上傳韌體

1. 開啟 Arduino IDE
2. 安裝 ESP32 板子支援
3. 安裝 ArduinoWebsockets 函式庫
4. 選擇板子：ESP32 Wrover Module
5. 上傳韌體

#### 4. 監控輸出

開啟序列埠監視器（115200 baud），你會看到：
```
ESP32 Camera Upload Test
Camera initialized
WiFi connected!
IP address: 192.168.1.100
WebSocket connected!
--- Capturing image ---
Image captured: 12345 bytes
Sending header: {"req_id":"esp32-12345","size":12345,"format":"jpeg"}
Sending image data...
Image sent!
```

## 驗證結果

### 1. 檢查 EC2 儲存的影像

```bash
# SSH 到 EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# 查看儲存的影像
cd backend/images
ls -lh

# 應該會看到類似：
# esp32-12345_1234567890.jpg
# test-1234567890_1234567891.jpg
```

### 2. 透過 API 查看

```bash
curl http://your-ec2-ip:8000/api/images
```

回應：
```json
{
  "images": [
    {
      "filename": "esp32-12345_1234567890.jpg",
      "size": 12345,
      "created": 1234567890.123
    }
  ],
  "count": 1
}
```

### 3. 在 Web UI 查看

開啟瀏覽器：`http://your-ec2-ip:8000/web/index.html`

應該會看到：
- 連線狀態：已連線
- 觸發事件列表會顯示收到的影像

## 故障排除

### 後端無法啟動
```bash
# 檢查端口是否被佔用
sudo netstat -tulpn | grep 8000

# 檢查防火牆
sudo firewall-cmd --list-all
```

### ESP32 無法連線
1. 檢查 WiFi 密碼是否正確
2. 確認 EC2 安全群組開放 8000 端口
3. 檢查 EC2 公網 IP 是否正確
4. 嘗試 ping EC2 IP

### 影像上傳失敗
1. 檢查影像大小（應 < 200KB）
2. 查看後端日誌：`tail -f server.log`
3. 檢查 WebSocket 連線狀態

## 測試清單

- [ ] 後端服務啟動成功
- [ ] `/api/health` 端點回應正常
- [ ] Python 測試腳本 HTTP 上傳成功
- [ ] Python 測試腳本 WebSocket 上傳成功
- [ ] 影像儲存在 `backend/images/` 目錄
- [ ] `/api/images` 端點列出影像
- [ ] ESP32 WiFi 連線成功
- [ ] ESP32 WebSocket 連線成功
- [ ] ESP32 影像上傳成功
- [ ] Web UI 顯示收到的影像事件

## 下一步

測試成功後，可以繼續實作：
1. ASR 語音辨識整合
2. 觸發詞檢測
3. 視覺模型整合
