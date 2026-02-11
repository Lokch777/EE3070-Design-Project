# ESP32 ASR Capture Vision MVP

語音控制的物品識別系統，使用 ESP32 裝置進行持續音訊採集，透過 ASR 辨識觸發詞後拍照，並使用視覺模型進行物品識別。

## 系統架構

```
ESP32 Device (麥克風 + 相機)
    ↓ WebSocket
AWS EC2 Backend (FastAPI)
    ↓ API
ASR Service (Qwen3-ASR) + Vision Model (Qwen Omni)
    ↓ WebSocket
Web UI (瀏覽器)
```

## 快速開始

### 1. 設定後端環境

```bash
# 建立虛擬環境
cd backend
python -m venv venv

# 啟動虛擬環境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的 API 金鑰
```

### 2. 啟動後端服務

```bash
# 開發模式（自動重載）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 生產模式
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. 開啟 Web UI

在瀏覽器開啟：
- 本機：`http://localhost:8000/web/index.html`
- AWS EC2：`http://your-ec2-public-ip:8000/web/index.html`

### 4. 配置 ESP32

在 ESP32 韌體中設定：
```cpp
const char* WS_HOST = "your-ec2-public-ip";
const int WS_PORT = 8000;
const bool USE_SSL = false;  // AWS EC2 測試環境先用 HTTP
```

## AWS EC2 部署

### 安全群組設定

確保 EC2 安全群組開放以下端口：
- **8000** (TCP) - 後端 API 及 WebSocket
- **22** (TCP) - SSH（管理用）

### 快速部署腳本

```bash
# SSH 連線到 EC2
ssh -i your-key.pem ec2-user@your-ec2-public-ip

# 安裝 Python 3.9+
sudo yum update -y
sudo yum install python3 python3-pip git -y

# Clone 專案
git clone <your-repo-url>
cd esp32-asr-capture-vision-mvp

# 設定並啟動
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
nano .env  # 填入 API 金鑰

# 啟動服務（背景執行）
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
```

## 專案結構

```
esp32-asr-capture-vision-mvp/
├── backend/              # Python 後端
│   ├── main.py          # FastAPI 應用程式入口
│   ├── models.py        # 資料模型
│   ├── config.py        # 配置管理
│   ├── requirements.txt # Python 依賴
│   └── .env.example     # 環境變數範本
├── web/                 # 網頁 UI
│   ├── index.html       # 主頁面
│   ├── style.css        # 樣式
│   └── app.js           # 前端邏輯
├── tests/               # 測試
│   ├── conftest.py      # Pytest 配置
│   └── test_models.py   # 模型測試
├── device/              # ESP32 韌體（待實作）
├── docs/                # 文件
└── README.md            # 本文件
```

## 開發指南

### 執行測試

```bash
cd backend
pytest tests/ -v
```

### 程式碼風格

```bash
# 安裝開發工具
pip install black flake8 mypy

# 格式化程式碼
black backend/

# 檢查程式碼
flake8 backend/
mypy backend/
```

## API 端點

### HTTP API
- `GET /` - 健康檢查
- `GET /api/health` - 系統狀態
- `GET /api/history?limit=20` - 歷史事件

### WebSocket 端點
- `/ws_audio` - ESP32 音訊上傳
- `/ws_ctrl` - ESP32 控制指令
- `/ws_camera` - ESP32 影像上傳
- `/ws_ui` - Web UI 事件推送

## 觸發詞

系統會辨識以下中文觸發詞：
- 「請你幫我識別物品」
- 「幫我認下呢個係咩」
- 「幫我認」
- 「睇下呢個」

## 故障排除

### 後端無法啟動
- 檢查 `.env` 檔案是否正確設定
- 確認 API 金鑰有效
- 查看 `server.log` 錯誤訊息

### ESP32 無法連線
- 確認 EC2 安全群組開放 8000 端口
- 檢查 ESP32 韌體中的 IP 位址
- 確認 WiFi 連線正常

### Web UI 無法連線
- 確認後端服務正在執行
- 檢查瀏覽器控制台錯誤訊息
- 確認 WebSocket 連線 URL 正確

## 授權

MIT License

## 貢獻

歡迎提交 Issue 和 Pull Request！
