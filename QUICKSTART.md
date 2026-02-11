# ESP32 ASR Capture Vision MVP - 快速開始

## 🚀 5 分鐘快速部署

### 1. 在 AWS EC2 上部署後端

```bash
# SSH 連線到 EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# 安裝依賴
sudo yum update -y
sudo yum install python3 python3-pip git -y

# Clone 專案
git clone <your-repo-url>
cd esp32-asr-capture-vision-mvp

# 啟動服務
chmod +x start_server.sh
./start_server.sh
```

### 2. 配置 API 金鑰

編輯 `backend/.env`：

```bash
ASR_API_KEY=your_dashscope_api_key
VISION_API_KEY=your_vision_api_key
```

### 3. 測試系統

#### 方式 A：使用 Python 模擬器（無需硬體）

```bash
# 在本機執行
cd device
python3 esp32_simulator.py --server ws://your-ec2-ip:8000 --image test.jpg
```

#### 方式 B：使用測試腳本

```bash
python test_upload.py test.jpg http://your-ec2-ip:8000
```

#### 方式 C：開啟 Web UI

瀏覽器訪問：`http://your-ec2-ip:8000/web/index.html`

### 4. 配置 ESP32（可選）

1. 開啟 Arduino IDE
2. 載入 `device/esp32_full_firmware.ino`
3. 修改配置：
   ```cpp
   const char* ssid = "你的WiFi";
   const char* password = "WiFi密碼";
   const char* serverHost = "你的EC2-IP";
   ```
4. 上傳到 ESP32-CAM

## 📋 系統需求

### 後端（AWS EC2）
- OS: Amazon Linux 2 / Ubuntu 20.04+
- Python: 3.9+
- RAM: 1GB+
- 磁碟: 10GB+
- 網路: 開放端口 8000

### ESP32 硬體（可選）
- ESP32-CAM 模組
- I2S 麥克風（INMP441 或類似）
- USB 轉 TTL 燒錄器

## 🔧 故障排除

### 後端無法啟動
```bash
# 檢查日誌
tail -f backend/server.log

# 檢查端口
sudo netstat -tulpn | grep 8000
```

### ESP32 無法連線
1. 確認 EC2 安全群組開放 8000 端口
2. 檢查 WiFi 密碼
3. 確認 EC2 公網 IP

### API 錯誤
```bash
# 驗證 API 金鑰
grep API_KEY backend/.env
```

## 📚 完整文件

- [README.md](README.md) - 完整專案說明
- [DEPLOYMENT.md](DEPLOYMENT.md) - 詳細部署指南
- [TESTING.md](TESTING.md) - 測試指南
- [API.md](API.md) - API 文件

## 🎯 MVP 成功標準

✅ 使用者說觸發詞 → 拍照 → 識別結果（10 秒內）
✅ 斷線自動重連
✅ Web UI 即時顯示
✅ API 金鑰安全儲存

## 💡 提示

- 先用 Python 模擬器測試，確認後端正常
- 再用實體 ESP32 測試完整流程
- 查看 Web UI 確認事件流程
- 檢查 `backend/images/` 目錄確認影像儲存

## 🆘 需要幫助？

1. 查看日誌：`tail -f backend/server.log`
2. 測試健康檢查：`curl http://localhost:8000/api/health`
3. 查看連線狀態：Web UI 右上角
