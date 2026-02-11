# ESP32 ASR Capture Vision MVP + Real-Time AI Assistant - 部署指南

## AWS EC2 快速部署

### 選擇作業系統

本指南支援以下 AWS EC2 作業系統：
- **Amazon Linux 2** (推薦 - AWS 優化)
- **Amazon Linux 2023** (最新版本)
- **Ubuntu 20.04/22.04 LTS** (社群支援廣泛)

---

## 部署選項 A：Amazon Linux 2 (推薦)

### 1. 準備 EC2 實例

```bash
# 連線到 EC2
ssh -i your-key.pem ec2-user@your-ec2-public-ip

# 更新系統
sudo yum update -y

# 安裝 Python 3.9+
sudo yum install python3 python3-pip git -y

# 安裝系統依賴
sudo yum install gcc python3-devel -y
```

---

## 部署選項 B：Amazon Linux 2023

### 1. 準備 EC2 實例

```bash
# 連線到 EC2
ssh -i your-key.pem ec2-user@your-ec2-public-ip

# 更新系統
sudo dnf update -y

# 安裝 Python 3.11+ (AL2023 預設)
sudo dnf install python3 python3-pip git -y

# 安裝系統依賴
sudo dnf install gcc python3-devel -y

# 驗證 Python 版本
python3 --version  # 應該是 3.11 或更高
```

---

## 部署選項 C：Ubuntu 20.04/22.04 LTS

### 1. 準備 EC2 實例

```bash
# 連線到 EC2
ssh -i your-key.pem ubuntu@your-ec2-public-ip

# 更新系統
sudo apt update && sudo apt upgrade -y

# 安裝 Python 3.9+
sudo apt install python3 python3-pip python3-venv git -y

# 安裝系統依賴
sudo apt install gcc python3-dev -y

# 驗證 Python 版本
python3 --version  # 應該是 3.8 或更高
```

---

## 通用部署步驟（所有作業系統）

### 2. 部署後端

```bash
# Clone 專案（或上傳檔案）
git clone <your-repo-url>
cd esp32-asr-capture-vision-mvp

# 進入後端目錄
cd backend

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝依賴
pip install --upgrade pip
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
nano .env
```

### 3. 配置環境變數

編輯 `.env` 檔案：

```bash
# ASR Service
ASR_API_KEY=your_dashscope_api_key_here
ASR_ENDPOINT=wss://dashscope.aliyuncs.com/api/v1/services/audio/asr

# Vision Model
VISION_API_KEY=your_vision_api_key_here
VISION_MODEL=qwen-vl-max
VISION_ENDPOINT=https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
VISION_TIMEOUT=8

# TTS Configuration
TTS_API_KEY=your_tts_api_key_here
TTS_ENDPOINT=wss://dashscope.aliyuncs.com/api/v1/services/audio/tts
TTS_VOICE=zhifeng_emo
TTS_LANGUAGE=zh-CN
TTS_SPEED=1.0
TTS_PITCH=1.0
TTS_AUDIO_FORMAT=pcm
TTS_SAMPLE_RATE=16000
TTS_TIMEOUT_SECONDS=5.0

# Trigger Configuration
TRIGGER_ENGLISH_PHRASES=describe the view,what do I see,what's in front of me,tell me what you see
TRIGGER_CHINESE_PHRASES=描述一下景象,我看到什麼,前面是什麼,告訴我你看到什麼
TRIGGER_FUZZY_THRESHOLD=0.85

# Audio Playback Configuration
AUDIO_CHUNK_SIZE=4096
AUDIO_BUFFER_SIZE=16384
AUDIO_STREAM_TIMEOUT=10.0

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# System Parameters
MAX_CONCURRENT_REQUESTS=1
COOLDOWN_SECONDS=3
CAPTURE_TIMEOUT_SECONDS=5
VISION_TIMEOUT_SECONDS=8
TTS_TIMEOUT_SECONDS=5
EVENT_BUFFER_SIZE=100

# AWS EC2
PUBLIC_URL=http://your-ec2-public-ip:8000
```

### 4. 配置安全群組

在 AWS Console 中，確保 EC2 安全群組開放：

- **端口 8000** (TCP) - 0.0.0.0/0 (HTTP/WebSocket)
- **端口 22** (TCP) - Your IP (SSH)

### 5. 啟動服務

#### 方式 A：前台執行（測試用）

```bash
cd backend
source venv/bin/activate
python main.py
```

#### 方式 B：背景執行（生產用）

```bash
cd backend
source venv/bin/activate
nohup python main.py > server.log 2>&1 &

# 查看日誌
tail -f server.log

# 停止服務
pkill -f "python main.py"
```

#### 方式 C：使用 systemd（推薦）

建立服務檔案：

```bash
sudo nano /etc/systemd/system/esp32-asr.service
```

內容（根據作業系統選擇）：

**Amazon Linux 2/2023:**

```ini
[Unit]
Description=ESP32 ASR Capture Vision MVP + Real-Time AI Assistant
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/EE3070-Design-Project/backend
Environment="PATH=/home/ec2-user/EE3070-Design-Project/backend/venv/bin"
ExecStart=/home/ec2-user/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Ubuntu 20.04/22.04:**

```ini
[Unit]
Description=ESP32 ASR Capture Vision MVP + Real-Time AI Assistant
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/EE3070-Design-Project/backend
Environment="PATH=/home/ubuntu/EE3070-Design-Project/backend/venv/bin"
ExecStart=/home/ubuntu/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

啟動服務：

```bash
sudo systemctl daemon-reload
sudo systemctl enable esp32-asr
sudo systemctl start esp32-asr

# 查看狀態
sudo systemctl status esp32-asr

# 查看日誌
sudo journalctl -u esp32-asr -f
```

### 6. 驗證部署

```bash
# 測試健康檢查
curl http://localhost:8000/api/health

# 從外部測試
curl http://your-ec2-public-ip:8000/api/health
```

### 7. 配置 ESP32

在 ESP32 韌體中設定：

```cpp
const char* ssid = "Your_WiFi_SSID";
const char* password = "Your_WiFi_Password";
const char* serverHost = "your-ec2-public-ip";
const int serverPort = 8000;
```

### 8. 測試完整流程

#### 使用 Python 模擬器測試

```bash
# 在本機執行
cd device
python3 esp32_simulator.py --server ws://your-ec2-public-ip:8000 --image test.jpg
```

#### 使用測試腳本

```bash
python test_upload.py test.jpg http://your-ec2-public-ip:8000
```

#### 開啟 Web UI

瀏覽器訪問：`http://your-ec2-public-ip:8000/web/index.html`

## 故障排除

### 後端無法啟動

```bash
# 檢查端口佔用
sudo netstat -tulpn | grep 8000

# 檢查日誌
tail -f backend/server.log

# 檢查環境變數
cat backend/.env
```

### ESP32 無法連線

1. 確認安全群組開放 8000 端口
2. 檢查 EC2 公網 IP 是否正確
3. 測試 WebSocket 連線：
   ```bash
   curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     http://your-ec2-public-ip:8000/ws_camera
   ```

### 影像上傳失敗

```bash
# 檢查 images 目錄權限
ls -la backend/images/

# 檢查磁碟空間
df -h

# 查看後端日誌
tail -f backend/server.log
```

### ASR 或 Vision API 錯誤

```bash
# 驗證 API 金鑰
grep API_KEY backend/.env

# 測試 API 連線
curl -H "Authorization: Bearer your_api_key" \
  https://dashscope.aliyuncs.com/api/v1/services/audio/asr
```

## 效能優化

### 1. 增加系統資源

```bash
# 檢查記憶體使用
free -h

# 檢查 CPU 使用
top
```

### 2. 調整參數

編輯 `.env`：

```bash
# 減少事件緩衝區大小
EVENT_BUFFER_SIZE=50

# 減少超時時間
CAPTURE_TIMEOUT_SECONDS=3
VISION_TIMEOUT_SECONDS=10
```

### 3. 啟用日誌輪替

```bash
sudo nano /etc/logrotate.d/esp32-asr
```

內容：

```
/home/ec2-user/esp32-asr-capture-vision-mvp/backend/server.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

## 監控

### 查看系統狀態

```bash
# 服務狀態
sudo systemctl status esp32-asr

# 連線數
sudo netstat -an | grep 8000 | wc -l

# 儲存的影像數
ls -1 backend/images/*.jpg | wc -l
```

### 查看 API 狀態

```bash
curl http://localhost:8000/api/health | jq
```

## 備份與恢復

### 備份

```bash
# 備份影像
tar -czf images_backup_$(date +%Y%m%d).tar.gz backend/images/

# 備份配置
cp backend/.env .env.backup
```

### 恢復

```bash
# 恢復影像
tar -xzf images_backup_20240101.tar.gz

# 恢復配置
cp .env.backup backend/.env
```

## 安全建議

1. **限制安全群組**：只開放必要的 IP 範圍
2. **使用 HTTPS**：配置 SSL 憑證（Let's Encrypt）
3. **定期更新**：保持系統和依賴套件最新
4. **監控日誌**：定期檢查異常活動
5. **備份 API 金鑰**：安全儲存在密碼管理器

## 擴展

### 使用 Nginx 反向代理

```bash
sudo yum install nginx -y

sudo nano /etc/nginx/conf.d/esp32-asr.conf
```

內容：

```nginx
upstream backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 使用 Docker

```bash
# 建立 Docker 映像
docker build -t esp32-asr-backend backend/

# 執行容器
docker run -d -p 8000:8000 \
  --env-file backend/.env \
  --name esp32-asr \
  esp32-asr-backend
```
