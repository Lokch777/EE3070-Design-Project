# ESP32 ASR Capture Vision MVP + Real-Time AI Assistant - API 文件

## WebSocket 端點

### `/ws_audio` - 音訊串流

**用途**：ESP32 上傳音訊資料

**協定**：WebSocket Binary

**資料格式**：
- 原始 PCM16 音訊資料
- 取樣率：16000 Hz
- 聲道：單聲道 (mono)
- 位元深度：16 bit
- 建議封包大小：3200 bytes (100ms)

**範例**：
```python
import websockets

async with websockets.connect("ws://server:8000/ws_audio") as ws:
    # Send audio chunk (3200 bytes)
    await ws.send(audio_chunk)
```

---

### `/ws_ctrl` - 控制指令

**用途**：VPS 發送控制指令給 ESP32

**協定**：WebSocket Text (JSON)

**訊息格式**：

#### CAPTURE 指令
```json
{
  "type": "CAPTURE",
  "req_id": "uuid-string",
  "timestamp": 1234567890.123
}
```

**範例**：
```python
async with websockets.connect("ws://server:8000/ws_ctrl") as ws:
    async for message in ws:
        data = json.loads(message)
        if data["type"] == "CAPTURE":
            req_id = data["req_id"]
            # Capture and send image
```

---

### `/ws_camera` - 影像上傳

**用途**：ESP32 上傳拍攝的影像

**協定**：WebSocket (Text + Binary)

**流程**：
1. 發送 JSON 標頭（文字訊息）
2. 發送 JPEG 二進位資料（二進位訊息）
3. 接收伺服器確認

**JSON 標頭格式**：
```json
{
  "req_id": "uuid-string",
  "size": 12345,
  "format": "jpeg"
}
```

**伺服器回應**：
```json
{
  "status": "success",
  "req_id": "uuid-string",
  "filename": "req-id_timestamp.jpg",
  "size": 12345
}
```

**範例**：
```python
async with websockets.connect("ws://server:8000/ws_camera") as ws:
    # Send JSON header
    header = {"req_id": "test-123", "size": len(image_data), "format": "jpeg"}
    await ws.send(json.dumps(header))
    
    # Send binary image data
    await ws.send(image_data)
    
    # Receive acknowledgment
    response = await ws.recv()
    print(json.loads(response))
```

---

### `/ws_ui` - Web UI 事件推送

**用途**：推送事件給 Web UI

**協定**：WebSocket Text (JSON)

**事件格式**：
```json
{
  "event_type": "string",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string (optional)",
  "data": {}
}
```

**事件類型**：

#### `asr_partial` - ASR 部分結果
```json
{
  "event_type": "asr_partial",
  "timestamp": 1234567890.123,
  "data": {
    "text": "請你幫我識"
  }
}
```

#### `asr_final` - ASR 最終結果
```json
{
  "event_type": "asr_final",
  "timestamp": 1234567890.123,
  "data": {
    "text": "請你幫我識別物品"
  }
}
```

#### `trigger_fired` - 觸發事件
```json
{
  "event_type": "trigger_fired",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "trigger_text": "請你幫我識別物品",
    "matched_keyword": "識別物品"
  }
}
```

#### `capture_requested` - 拍照請求
```json
{
  "event_type": "capture_requested",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {}
}
```

#### `capture_received` - 影像接收
```json
{
  "event_type": "capture_received",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "filename": "req-id_timestamp.jpg",
    "image_size": 12345,
    "format": "jpeg"
  }
}
```

#### `vision_started` - 視覺分析開始
```json
{
  "event_type": "vision_started",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "prompt": "請你幫我識別物品"
  }
}
```

#### `vision_result` - 視覺分析結果
```json
{
  "event_type": "vision_result",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "text": "這是一個紅色的蘋果",
    "confidence": 0.95
  }
}
```

#### `question_detected` - 問題檢測（NEW!）
```json
{
  "event_type": "question_detected",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "question_text": "describe the view",
    "matched_phrase": "describe the view",
    "language": "en"
  }
}
```

#### `tts_started` - TTS 開始（NEW!）
```json
{
  "event_type": "tts_started",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "text": "這是一個紅色的蘋果",
    "voice": "zhifeng_emo"
  }
}
```

#### `audio_ready` - 音訊就緒（NEW!）
```json
{
  "event_type": "audio_ready",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "audio_size": 32000,
    "duration_seconds": 2.0,
    "format": "pcm16"
  }
}
```

#### `audio_playback_started` - 音訊播放開始（NEW!）
```json
{
  "event_type": "audio_playback_started",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "chunk_size": 4096,
    "total_chunks": 8
  }
}
```

#### `audio_playback_complete` - 音訊播放完成（NEW!）
```json
{
  "event_type": "audio_playback_complete",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "chunks_sent": 8,
    "duration_seconds": 2.0
  }
}
```

#### `error` - 錯誤事件
```json
{
  "event_type": "error",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string (optional)",
  "data": {
    "error_type": "capture_timeout",
    "message": "ESP32 未在 5 秒內回應影像",
    "details": {}
  }
}
```

---

## HTTP API 端點

### `GET /` - 根端點

**回應**：
```json
{
  "message": "ESP32 ASR Capture Vision MVP Backend",
  "status": "running"
}
```

---

### `GET /api/health` - 健康檢查

**回應**：
```json
{
  "status": "healthy",
  "esp32_audio_connected": true,
  "esp32_camera_connected": true,
  "web_ui_connected": true,
  "total_connections": 3,
  "images_stored": 10,
  "event_bus_stats": {
    "history_size": 50,
    "buffer_size": 100,
    "subscriber_count": 2,
    "event_types": ["*", "asr_final"]
  }
}
```

---

### `GET /api/history` - 歷史事件

**參數**：
- `limit` (optional): 返回事件數量（預設 20，最大 100）
- `event_type` (optional): 過濾事件類型

**範例**：
```
GET /api/history?limit=10&event_type=asr_final
```

**回應**：
```json
{
  "events": [
    {
      "event_type": "asr_final",
      "timestamp": 1234567890.123,
      "data": {"text": "請你幫我識別物品"}
    }
  ],
  "count": 1
}
```

---

### `GET /api/images` - 影像列表

**回應**：
```json
{
  "images": [
    {
      "filename": "req-123_1234567890.jpg",
      "size": 12345,
      "created": 1234567890.123
    }
  ],
  "count": 1
}
```

---

### `POST /api/upload_image` - 影像上傳（測試用）

**Content-Type**: `multipart/form-data`

**參數**：
- `file`: JPEG 影像檔案
- `req_id` (optional): 請求 ID

**回應**：
```json
{
  "success": true,
  "filename": "test-123_1234567890.jpg",
  "size": 12345,
  "path": "images/test-123_1234567890.jpg"
}
```

**範例**：
```bash
curl -X POST http://server:8000/api/upload_image \
  -F "file=@test.jpg" \
  -F "req_id=test-123"
```

---

## 錯誤碼

### WebSocket 錯誤

| 錯誤類型 | 說明 |
|---------|------|
| `connection_failed` | 連線失敗 |
| `connection_timeout` | 連線超時 |
| `websocket_closed` | WebSocket 關閉 |

### ASR 錯誤

| 錯誤類型 | 說明 |
|---------|------|
| `asr_connection_failed` | ASR 服務連線失敗 |
| `asr_auth_failed` | ASR 認證失敗 |
| `asr_timeout` | ASR 超時 |

### 拍照錯誤

| 錯誤類型 | 說明 |
|---------|------|
| `capture_timeout` | 拍照超時（5 秒） |
| `capture_failed` | 拍照失敗 |
| `invalid_image` | 無效影像 |
| `image_too_large` | 影像過大（>200KB） |

### 視覺模型錯誤

| 錯誤類型 | 說明 |
|---------|------|
| `vision_timeout` | 視覺模型超時（8 秒） |
| `vision_api_error` | 視覺模型 API 錯誤 |
| `vision_auth_failed` | 視覺模型認證失敗 |

### TTS 錯誤（NEW!）

| 錯誤類型 | 說明 |
|---------|------|
| `tts_timeout` | TTS 超時（5 秒） |
| `tts_connection_failed` | TTS 服務連線失敗 |
| `tts_api_error` | TTS API 錯誤 |
| `audio_playback_failed` | 音訊播放失敗 |

---

## 限制

- **音訊格式**：僅支援 PCM16 單聲道 16kHz
- **影像格式**：僅支援 JPEG
- **影像大小**：最大 200KB
- **影像解析度**：最大 640x480
- **並發請求**：同時最多 1 個活躍請求
- **冷卻時間**：觸發後 3 秒冷卻期
- **超時設定**：
  - 拍照超時：5 秒
  - 視覺模型超時：8 秒
  - TTS 超時：5 秒
  - 音訊播放超時：10 秒
  - WebSocket 心跳：30 秒 ping，60 秒超時

---

## 安全性

- ✅ API 金鑰僅存放於 VPS 後端
- ✅ 前端和 ESP32 無法存取 API 金鑰
- ✅ WebSocket 支援心跳檢測
- ✅ 自動重連機制
- ⚠️ MVP 版本未啟用 HTTPS/WSS（生產環境需啟用）
