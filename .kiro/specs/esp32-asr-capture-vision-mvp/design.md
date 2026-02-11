# 設計文件：ESP32 ASR 捕捉視覺 MVP

## 概述

本系統實現一個語音控制的物品識別裝置，由三個主要組件組成：

1. **ESP32 裝置**：持續採集音訊並上傳至 VPS，接收拍照指令後回傳 JPEG 影像
2. **VPS 後端**：WebSocket 閘道、ASR 橋接、觸發引擎、拍照協調器、視覺模型適配器及事件匯流排
3. **網頁 UI**：即時顯示 ASR 結果、觸發事件、快照及視覺辨識結果

系統採用事件驅動架構，所有組件透過 WebSocket 進行即時通訊，使用 req_id 關聯完整的觸發→拍照→視覺辨識流程。

## 系統架構

```
┌─────────────────┐
│  ESP32 Device   │
│  ┌───────────┐  │
│  │ I2S Mic   │  │──┐
│  └───────────┘  │  │ PCM16 Audio (WS)
│  ┌───────────┐  │  │
│  │ ESP32-CAM │  │  │
│  └───────────┘  │  │
└─────────────────┘  │
         ▲           │
         │ CAPTURE   │
         │ (WS)      │
         │           ▼
         │  ┌─────────────────────────────────────┐
         │  │       VPS Backend (FastAPI)         │
         │  │  ┌────────────────────────────────┐ │
         │  │  │      WebSocket Gateway         │ │
         │  │  │  /ws_audio  /ws_ctrl           │ │
         │  │  │  /ws_camera /ws_ui             │ │
         │  │  └────────────────────────────────┘ │
         │  │                │                     │
         │  │  ┌─────────────┴──────────────────┐ │
         │  │  │        Event Bus               │ │
         │  │  │  (asyncio Queue / PubSub)      │ │
         │  │  └─────────────┬──────────────────┘ │
         │  │                │                     │
         │  │  ┌─────────────┼──────────────────┐ │
         │  │  │  ASR Bridge │ Trigger Engine   │ │
         │  │  │             │ Capture Coord    │ │
         │  │  │             │ Vision Adapter   │ │
         │  │  └─────────────┴──────────────────┘ │
         │  └─────────────────────────────────────┘
         │                   │
         └───────────────────┘
                             │ Events (WS)
                             ▼
                    ┌─────────────────┐
                    │    Web UI       │
                    │  (Browser)      │
                    └─────────────────┘
                             │
                             │ HTTP API
                             ▼
                    ┌─────────────────┐
                    │  ASR Service    │
                    │  (Qwen3-ASR)    │
                    └─────────────────┘
                             │
                             │ HTTP/SDK
                             ▼
                    ┌─────────────────┐
                    │  Vision Model   │
                    │  (Qwen Omni)    │
                    └─────────────────┘
```

## 組件與介面

### 1. WebSocket 閘道

**職責**：
- 管理所有 WebSocket 連線（ESP32 音訊、控制、相機；Web UI）
- 路由訊息至對應的處理器
- 維護連線狀態及心跳檢測

**端點**：

#### `/ws_audio` (ESP32 → VPS)
- **協定**：WebSocket Binary
- **資料格式**：原始 PCM16 音訊資料
- **參數**：
  - `sample_rate`: 16000 Hz
  - `channels`: 1 (mono)
  - `bit_depth`: 16
- **封包大小**：建議 100ms/chunk (3200 bytes = 16000 Hz × 0.1s × 2 bytes)
- **背壓處理**：若 ASR 處理速度跟不上，丟棄舊封包保持即時性

#### `/ws_ctrl` (VPS → ESP32)
- **協定**：WebSocket Text (JSON)
- **訊息格式**：
```json
{
  "type": "CAPTURE",
  "req_id": "uuid-string",
  "timestamp": 1234567890.123
}
```

#### `/ws_camera` (ESP32 → VPS)
- **協定**：WebSocket Binary
- **資料格式**：先發送 JSON 標頭，再發送 JPEG 二進位資料
- **標頭格式**：
```json
{
  "req_id": "uuid-string",
  "size": 12345,
  "format": "jpeg"
}
```
- **流程**：
  1. ESP32 發送 JSON 標頭（文字訊息）
  2. ESP32 發送 JPEG 二進位資料（二進位訊息）
  3. VPS 根據 req_id 關聯請求

#### `/ws_ui` (VPS → Browser)
- **協定**：WebSocket Text (JSON)
- **事件格式**：見「事件模型」章節

### 2. ASR 橋接器 (ASR Bridge)

**職責**：
- 建立並維護與 ASR_Service 的 WebSocket 連線
- 將 ESP32 音訊串流轉發至 ASR_Service
- 接收 ASR 轉錄結果（partial 及 final）
- 處理伺服器端 VAD 事件
- 斷線自動重連

**ASR 服務整合流程**：

1. **會話建立**：
   - 連接至 Qwen3-ASR-Flash-Realtime WebSocket 端點
   - 發送認證及配置參數（API key、語言、VAD 設定）
   - 接收會話確認

2. **音訊串流**：
   - 持續發送 PCM16 音訊封包
   - 監聽 ASR 回應事件

3. **接收轉錄**：
   - `partial_result`：部分轉錄（可選顯示）
   - `final_result`：最終轉錄（觸發引擎輸入）
   - `sentence_end`：句子結束（伺服器 VAD）

4. **錯誤處理**：
   - 連線逾時：5 秒後重連
   - 認證失敗：記錄錯誤並停止服務
   - 速率限制：實施退避重試

**介面**：
```python
class ASRBridge:
    async def connect() -> bool
    async def send_audio(audio_chunk: bytes) -> None
    async def receive_transcription() -> AsyncIterator[TranscriptionEvent]
    async def reconnect() -> bool
    async def close() -> None
```

### 3. 觸發引擎 (Trigger Engine)

**職責**：
- 監聽 ASR 最終文字
- 檢測觸發關鍵詞或語義
- 生成 CAPTURE 請求並分配 req_id
- 實施冷卻機制防止重複觸發
- 維護觸發狀態

**觸發規則**：
- **關鍵詞匹配**：「識別物品」、「認下呢個係咩」、「幫我認」、「睇下呢個」
- **語義匹配**（可選）：使用簡單的模式匹配或輕量級 NLU
- **大小寫不敏感**：統一轉換為小寫比對

**冷卻機制**：
- 成功觸發後進入 COOLDOWN 狀態
- 冷卻時間：3 秒
- 冷卻期間忽略新的觸發詞
- 冷卻結束後恢復 LISTENING 狀態

**介面**：
```python
class TriggerEngine:
    def check_trigger(text: str) -> Optional[TriggerEvent]
    def is_in_cooldown() -> bool
    def reset_cooldown() -> None
```

### 4. 拍照協調器 (Capture Coordinator)

**職責**：
- 接收觸發事件並發送 CAPTURE 指令至 ESP32
- 等待 ESP32 回傳 JPEG 影像
- 處理逾時及錯誤
- 維護 req_id 與影像的對應關係

**狀態機**：
```
IDLE → CAPTURE_REQUESTED → WAITING_IMAGE → IMAGE_RECEIVED → IDLE
                                ↓ (timeout)
                              ERROR → IDLE
```

**逾時處理**：
- CAPTURE 指令發送後等待 5 秒
- 若未收到影像，標記為 ERROR 並發送錯誤事件
- 釋放資源並返回 IDLE 狀態

**介面**：
```python
class CaptureCoordinator:
    async def request_capture(req_id: str) -> None
    async def wait_for_image(req_id: str, timeout: float = 5.0) -> Optional[bytes]
    def cancel_request(req_id: str) -> None
```

### 5. 視覺模型適配器 (VisionLLMAdapter)

**職責**：
- 提供統一的視覺模型呼叫介面
- 支援多種視覺模型後端（Qwen Omni Flash、GPT-4V 等）
- 處理影像編碼及提示詞組合
- 處理逾時及錯誤

**介面**：
```python
class VisionLLMAdapter:
    async def analyze_image(
        image_bytes: bytes,
        prompt: str,
        req_id: str
    ) -> VisionResult

class VisionResult:
    text: str
    confidence: Optional[float]
    error: Optional[str]
```

**實作範例（Qwen Omni Flash）**：
```python
class QwenOmniAdapter(VisionLLMAdapter):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = DashScopeClient(api_key)
    
    async def analyze_image(self, image_bytes, prompt, req_id):
        # 將 JPEG 編碼為 base64
        image_b64 = base64.b64encode(image_bytes).decode()
        
        # 組合提示詞
        full_prompt = f"{prompt}\n請描述圖片中的物品。"
        
        # 呼叫 API
        response = await self.client.call_multimodal(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "image": f"data:image/jpeg;base64,{image_b64}"},
                    {"type": "text", "text": full_prompt}
                ]
            }],
            timeout=15.0
        )
        
        return VisionResult(
            text=response.output.text,
            confidence=None,
            error=None
        )
```

### 6. 事件匯流排 (Event Bus)

**職責**：
- 在各組件間傳遞事件
- 支援發布/訂閱模式
- 維護事件歷史記錄（環形緩衝區）

**實作**：
- 使用 `asyncio.Queue` 或輕量級 PubSub 庫
- 記憶體環形緩衝區：保留最近 100 筆事件

**介面**：
```python
class EventBus:
    async def publish(event: Event) -> None
    async def subscribe(event_type: str) -> AsyncIterator[Event]
    def get_history(limit: int = 20) -> List[Event]
```

## 事件模型

所有事件遵循統一格式：

```json
{
  "event_type": "string",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string (optional)",
  "data": {}
}
```

### 事件類型

#### `asr_partial`
```json
{
  "event_type": "asr_partial",
  "timestamp": 1234567890.123,
  "data": {
    "text": "請你幫我識"
  }
}
```

#### `asr_final`
```json
{
  "event_type": "asr_final",
  "timestamp": 1234567890.123,
  "data": {
    "text": "請你幫我識別物品"
  }
}
```

#### `trigger_fired`
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

#### `capture_requested`
```json
{
  "event_type": "capture_requested",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {}
}
```

#### `capture_received`
```json
{
  "event_type": "capture_received",
  "timestamp": 1234567890.123,
  "req_id": "uuid-string",
  "data": {
    "image_size": 12345,
    "format": "jpeg"
  }
}
```

#### `vision_started`
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

#### `vision_result`
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

#### `error`
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

## 資料模型

### Request Context
```python
@dataclass
class RequestContext:
    req_id: str
    trigger_text: str
    trigger_time: float
    capture_time: Optional[float] = None
    image_bytes: Optional[bytes] = None
    vision_result: Optional[str] = None
    state: str = "TRIGGERED"  # TRIGGERED, CAPTURING, VISION_RUNNING, DONE, ERROR
    error: Optional[str] = None
```

### Connection State
```python
@dataclass
class ConnectionState:
    conn_id: str
    conn_type: str  # "esp32_audio", "esp32_ctrl", "esp32_camera", "web_ui"
    connected_at: float
    last_heartbeat: float
    metadata: Dict[str, Any]
```

### Event
```python
@dataclass
class Event:
    event_type: str
    timestamp: float
    req_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
```

## 狀態機

系統主要狀態機（針對每個 req_id）：

```
                    ┌──────────┐
                    │ LISTENING│
                    └────┬─────┘
                         │ trigger detected
                         ▼
                    ┌──────────┐
                    │TRIGGERED │
                    └────┬─────┘
                         │ send CAPTURE
                         ▼
                  ┌──────────────┐
                  │WAITING_IMAGE │
                  └──┬────────┬──┘
                     │        │ timeout
                     │        ▼
                     │   ┌────────┐
                     │   │ ERROR  │
                     │   └────────┘
                     │ image received
                     ▼
              ┌──────────────┐
              │VISION_RUNNING│
              └──┬────────┬──┘
                 │        │ timeout/error
                 │        ▼
                 │   ┌────────┐
                 │   │ ERROR  │
                 │   └────────┘
                 │ result received
                 ▼
            ┌────────┐
            │  DONE  │
            └────────┘
                 │
                 ▼
            ┌──────────┐
            │ COOLDOWN │ (3 seconds)
            └────┬─────┘
                 │
                 ▼
            ┌──────────┐
            │LISTENING │
            └──────────┘
```

## 佇列與節流策略

### 音訊串流背壓處理
- **問題**：ESP32 音訊產生速度可能超過 ASR 處理速度
- **策略**：
  - 使用有界佇列（max size = 50 chunks，約 5 秒音訊）
  - 佇列滿時丟棄最舊的封包
  - 優先保持即時性而非完整性

### 觸發冷卻
- **問題**：使用者可能連續說出觸發詞
- **策略**：
  - 成功觸發後進入 3 秒冷卻期
  - 冷卻期間忽略所有觸發詞
  - 避免重複拍照及視覺模型呼叫

### 並發請求限制
- **問題**：多個觸發請求可能同時進行
- **策略**：
  - MVP 階段限制同時只能有 1 個活躍請求
  - 新觸發在前一個請求完成前被拒絕
  - 未來可擴展為佇列機制

### 影像大小限制
- **問題**：大型 JPEG 影像可能導致傳輸及處理延遲
- **策略**：
  - ESP32 端限制解析度為 640x480
  - VPS 端驗證影像大小不超過 200KB
  - 超過限制則拒絕並返回錯誤

## 錯誤處理

### 1. ASR 連線錯誤
- **場景**：VPS 無法連接至 ASR_Service
- **處理**：
  - 記錄錯誤事件
  - 5 秒後嘗試重連
  - 最多重試 3 次
  - 失敗後進入降級模式（停止 ASR 功能）

### 2. ESP32 斷線
- **場景**：ESP32 WebSocket 連線中斷
- **處理**：
  - 清理該連線的所有待處理請求
  - 標記所有相關 req_id 為 ERROR
  - 等待 ESP32 重連
  - ESP32 重連後恢復 LISTENING 狀態

### 3. 拍照逾時
- **場景**：ESP32 未在 5 秒內回傳影像
- **處理**：
  - 發送 `error` 事件至 Web UI
  - 標記 req_id 為 ERROR
  - 釋放資源並返回 IDLE
  - 記錄逾時統計

### 4. 視覺模型錯誤
- **場景**：視覺模型 API 呼叫失敗或逾時
- **處理**：
  - 記錄詳細錯誤訊息
  - 返回友善的錯誤訊息至 Web UI
  - 標記 req_id 為 ERROR
  - 不影響後續請求

### 5. 無效的 req_id
- **場景**：收到的影像 req_id 不匹配任何待處理請求
- **處理**：
  - 記錄警告
  - 丟棄影像
  - 不影響系統運行

### 6. API 金鑰無效
- **場景**：ASR 或視覺模型 API 金鑰認證失敗
- **處理**：
  - 記錄嚴重錯誤
  - 停止相關服務
  - 通知管理員（透過日誌）
  - 不嘗試重連（避免帳號被鎖定）

## 通訊協定細節

### WebSocket 心跳
- 每 30 秒發送 ping frame
- 60 秒未收到 pong 視為斷線
- 自動清理斷線連線

### 重連策略
- **ESP32 → VPS**：
  - 斷線後 3 秒重連
  - 指數退避：3s, 6s, 12s, 24s, 最大 60s
  - 無限重試
  
- **VPS → ASR**：
  - 斷線後 5 秒重連
  - 最多重試 3 次
  - 失敗後進入降級模式

- **Web UI → VPS**：
  - 斷線後立即顯示提示
  - 1 秒後開始重連
  - 指數退避：1s, 2s, 4s, 8s, 最大 30s
  - 無限重試

### 訊息序列化
- **JSON 訊息**：UTF-8 編碼
- **二進位訊息**：原始 bytes
- **混合訊息**（如相機上傳）：先 JSON 標頭，後二進位資料

## HTTP API 端點

### `POST /api/ask`（可選，除錯用）
手動觸發拍照及視覺辨識

**請求**：
```json
{
  "prompt": "請識別這個物品"
}
```

**回應**：
```json
{
  "req_id": "uuid-string",
  "status": "triggered"
}
```

### `GET /api/history`
取得歷史事件記錄

**參數**：
- `limit`: 返回事件數量（預設 20，最大 100）

**回應**：
```json
{
  "events": [
    {
      "event_type": "asr_final",
      "timestamp": 1234567890.123,
      "data": {...}
    },
    ...
  ]
}
```

### `GET /api/health`
健康檢查

**回應**：
```json
{
  "status": "healthy",
  "asr_connected": true,
  "esp32_connected": true,
  "uptime": 12345.67
}
```


## 正確性屬性

屬性（Property）是一種特徵或行為，應該在系統的所有有效執行中保持為真——本質上是關於系統應該做什麼的正式陳述。屬性作為人類可讀規格與機器可驗證正確性保證之間的橋樑。

### 屬性 1：音訊串流端到端處理

*對於任何*有效的 PCM16 音訊封包，當 ESP32 透過 WebSocket 發送至 VPS 後端時，該音訊應該被轉發至 ASR 服務，且 ASR 返回的最終文字應該被廣播至所有連接的 Web UI 客戶端。

**驗證：需求 1.1, 1.2, 1.3**

### 屬性 2：音訊格式驗證

*對於任何*音訊資料，系統應該只接受 PCM16 單聲道 16kHz 格式的音訊，並拒絕其他格式的音訊資料。

**驗證：需求 1.4**

### 屬性 3：觸發詞檢測與事件生成

*對於任何*包含觸發關鍵詞（「識別物品」、「認下呢個係咩」等）的 ASR 最終文字，系統應該生成一個具有唯一 req_id 的 CAPTURE 請求，並廣播 trigger_fired 事件至 Web UI。

**驗證：需求 2.1, 2.2, 2.5**

### 屬性 4：並發觸發控制

*對於任何*處於活躍狀態（非 IDLE）的請求，當新的觸發詞被檢測到時，系統應該拒絕新的觸發請求並記錄冷卻事件。

**驗證：需求 2.3**

### 屬性 5：拍照指令與影像接收協調

*對於任何*有效的 CAPTURE 請求，系統應該發送包含正確 req_id 的 CAPTURE_Command 至 ESP32，且當接收到 JPEG 影像時，應該驗證 req_id 匹配並記錄 capture_received 事件。

**驗證：需求 3.1, 3.3**

### 屬性 6：影像大小限制

*對於任何*從 ESP32 接收的 JPEG 影像，其解析度應該不超過 640x480，且檔案大小應該不超過 200KB，否則系統應該拒絕該影像並返回錯誤。

**驗證：需求 3.5**

### 屬性 7：視覺模型呼叫與結果處理

*對於任何*有效的 JPEG 影像及觸發指令文字，系統應該呼叫 VisionLLMAdapter 並維持 req_id 關聯，且當視覺模型返回結果時，應該廣播 vision_result 事件至 Web UI。

**驗證：需求 4.1, 4.2, 4.5**

### 屬性 8：UI 事件推送完整性

*對於任何*連接至 VPS 的 Web UI 客戶端，當觸發事件發生時，推送的事件資料應該包含 req_id、觸發時間、觸發指令及事件類型等所有必要欄位。

**驗證：需求 5.1, 5.3**

### 屬性 9：歷史事件查詢

*對於任何*歷史事件查詢請求，系統應該返回最近 N 筆事件（N 由請求指定，最大 100），且返回的事件應該按時間戳記降序排列。

**驗證：需求 5.6, 8.3**

### 屬性 10：重連後狀態恢復

*對於任何*因網路中斷而斷線的連線，當重連成功後，系統應該恢復至 LISTENING 狀態，且不應該遺失任何待處理的請求（除非已超時）。

**驗證：需求 6.4**

### 屬性 11：事件記錄完整性

*對於任何*關鍵事件（asr_final、trigger_fired、capture_requested、capture_received、vision_result、error），系統應該記錄該事件並包含時間戳記、事件類型、req_id（如適用）及相關資料等所有必要欄位。

**驗證：需求 8.1, 8.4**

### 屬性 12：環形緩衝區行為

*對於任何*事件序列，當事件數量超過 100 筆時，環形緩衝區應該保留最新的 100 筆事件，且最舊的事件應該被新事件覆蓋。

**驗證：需求 8.2**

### 屬性 13：錯誤記錄完整性

*對於任何*系統錯誤，記錄的錯誤事件應該包含錯誤類型、錯誤訊息、req_id（如適用）及堆疊追蹤（如適用）等所有必要資訊。

**驗證：需求 8.5**

### 屬性 14：req_id 唯一性

*對於任何*兩個不同的觸發請求，它們的 req_id 應該是唯一的，且在整個系統生命週期內不應該重複。

**驗證：需求 2.2**

## 錯誤處理

### 錯誤類型定義

```python
class ErrorType(Enum):
    # 連線錯誤
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_TIMEOUT = "connection_timeout"
    WEBSOCKET_CLOSED = "websocket_closed"
    
    # ASR 錯誤
    ASR_CONNECTION_FAILED = "asr_connection_failed"
    ASR_AUTH_FAILED = "asr_auth_failed"
    ASR_TIMEOUT = "asr_timeout"
    
    # 拍照錯誤
    CAPTURE_TIMEOUT = "capture_timeout"
    CAPTURE_FAILED = "capture_failed"
    INVALID_IMAGE = "invalid_image"
    IMAGE_TOO_LARGE = "image_too_large"
    
    # 視覺模型錯誤
    VISION_TIMEOUT = "vision_timeout"
    VISION_API_ERROR = "vision_api_error"
    VISION_AUTH_FAILED = "vision_auth_failed"
    
    # 系統錯誤
    INVALID_REQ_ID = "invalid_req_id"
    INVALID_FORMAT = "invalid_format"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INTERNAL_ERROR = "internal_error"
```

### 錯誤恢復策略

| 錯誤類型 | 恢復策略 | 重試次數 | 退避時間 |
|---------|---------|---------|---------|
| CONNECTION_TIMEOUT | 自動重連 | 無限 | 指數退避（3s, 6s, 12s, ...最大 60s） |
| ASR_CONNECTION_FAILED | 自動重連 | 3 次 | 5s |
| ASR_AUTH_FAILED | 停止服務 | 0 | N/A |
| CAPTURE_TIMEOUT | 標記失敗，繼續 | 0 | N/A |
| VISION_TIMEOUT | 標記失敗，繼續 | 1 次 | 5s |
| VISION_API_ERROR | 標記失敗，繼續 | 1 次 | 5s |
| INVALID_IMAGE | 拒絕並記錄 | 0 | N/A |
| RATE_LIMIT_EXCEEDED | 退避重試 | 3 次 | 指數退避（10s, 20s, 40s） |

## 測試策略

### 單元測試

單元測試專注於特定範例、邊界條件及錯誤處理：

1. **觸發引擎測試**：
   - 測試各種觸發關鍵詞的匹配
   - 測試冷卻機制（3 秒邊界）
   - 測試並發觸發拒絕

2. **拍照協調器測試**：
   - 測試 CAPTURE 指令發送
   - 測試超時處理（5 秒邊界）
   - 測試無效 req_id 處理

3. **視覺模型適配器測試**：
   - 測試 API 呼叫成功案例
   - 測試超時處理（15 秒邊界）
   - 測試錯誤回應處理

4. **事件匯流排測試**：
   - 測試事件發布與訂閱
   - 測試環形緩衝區（100 筆邊界）
   - 測試歷史查詢

5. **WebSocket 閘道測試**：
   - 測試連線建立與關閉
   - 測試心跳機制（30 秒 ping，60 秒超時）
   - 測試訊息路由

### 屬性測試

屬性測試驗證通用屬性，每個測試至少執行 100 次迭代：

1. **屬性 1：音訊串流端到端處理**
   - 生成隨機 PCM16 音訊封包
   - 驗證音訊轉發及結果廣播
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 1: 音訊串流端到端處理**

2. **屬性 2：音訊格式驗證**
   - 生成各種格式的音訊資料（有效及無效）
   - 驗證系統只接受 PCM16 16kHz mono
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 2: 音訊格式驗證**

3. **屬性 3：觸發詞檢測與事件生成**
   - 生成包含和不包含觸發詞的文字
   - 驗證觸發行為及 req_id 唯一性
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 3: 觸發詞檢測與事件生成**

4. **屬性 4：並發觸發控制**
   - 生成並發觸發請求
   - 驗證系統正確拒絕重複觸發
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 4: 並發觸發控制**

5. **屬性 5：拍照指令與影像接收協調**
   - 生成隨機 CAPTURE 請求及 JPEG 回應
   - 驗證 req_id 匹配及事件記錄
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 5: 拍照指令與影像接收協調**

6. **屬性 6：影像大小限制**
   - 生成各種大小的 JPEG 影像
   - 驗證系統正確接受或拒絕
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 6: 影像大小限制**

7. **屬性 7：視覺模型呼叫與結果處理**
   - 生成隨機影像及提示詞
   - 驗證 req_id 維持及結果廣播
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 7: 視覺模型呼叫與結果處理**

8. **屬性 8：UI 事件推送完整性**
   - 生成隨機觸發事件
   - 驗證推送資料包含所有必要欄位
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 8: UI 事件推送完整性**

9. **屬性 9：歷史事件查詢**
   - 生成隨機數量的事件
   - 驗證查詢返回正確數量及順序
   - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 9: 歷史事件查詢**

10. **屬性 10：重連後狀態恢復**
    - 模擬斷線及重連
    - 驗證狀態正確恢復至 LISTENING
    - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 10: 重連後狀態恢復**

11. **屬性 11：事件記錄完整性**
    - 生成各種類型的事件
    - 驗證記錄包含所有必要欄位
    - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 11: 事件記錄完整性**

12. **屬性 12：環形緩衝區行為**
    - 生成超過 100 筆事件
    - 驗證舊事件被正確覆蓋
    - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 12: 環形緩衝區行為**

13. **屬性 13：錯誤記錄完整性**
    - 觸發各種錯誤情況
    - 驗證錯誤記錄包含完整資訊
    - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 13: 錯誤記錄完整性**

14. **屬性 14：req_id 唯一性**
    - 生成大量觸發請求
    - 驗證所有 req_id 都是唯一的
    - **標籤：Feature: esp32-asr-capture-vision-mvp, Property 14: req_id 唯一性**

### 整合測試

1. **完整流程測試**：
   - 使用 ESP32 模擬器發送音訊
   - 模擬 ASR 服務返回觸發詞
   - 驗證拍照指令發送
   - 模擬 ESP32 返回 JPEG
   - 模擬視覺模型返回結果
   - 驗證 Web UI 接收所有事件

2. **斷線恢復測試**：
   - 模擬各種斷線情況
   - 驗證自動重連
   - 驗證狀態恢復

3. **錯誤處理測試**：
   - 模擬各種錯誤情況
   - 驗證錯誤記錄及恢復策略

### ESP32 模擬器

為了測試而不需要實體硬體，開發 Python 模擬器：

**功能**：
- 播放預錄的 PCM16 音訊檔案
- 模擬 WebSocket 連線至 VPS
- 接收 CAPTURE 指令
- 上傳預先準備的 JPEG 影像
- 模擬斷線及重連

**使用範例**：
```bash
python esp32_simulator.py \
  --audio test_audio.pcm \
  --image test_image.jpg \
  --server ws://localhost:8000
```

### 測試工具選擇

- **後端測試框架**：pytest
- **屬性測試庫**：Hypothesis（Python）
- **WebSocket 測試**：pytest-asyncio + websockets
- **模擬工具**：unittest.mock / pytest-mock
- **測試覆蓋率**：pytest-cov（目標：80% 以上）

### 測試配置

- 屬性測試最小迭代次數：100
- 單元測試超時：5 秒
- 整合測試超時：30 秒
- 持續整合：每次 commit 自動執行所有測試

## 部署考量

### Cloudflare Tunnel 整合

本系統使用 **Cloudflare Tunnel** 來安全地暴露本機服務至公網，無需開放防火牆端口或設定複雜的 NAT 穿透。

**優勢**：
- 本機開發即可測試完整流程（ESP32 → Cloudflare → 本機 VPS 後端）
- 自動 HTTPS/WSS 加密，無需手動配置 SSL 憑證
- 無需公網 IP 或 VPS，可在本機運行後端
- 支援 WebSocket 長連線
- 免費方案即可使用

**架構**：
```
ESP32 Device ──┐
               ├──> Cloudflare Tunnel ──> 本機後端 (localhost:8000)
Web Browser ───┘
```

**設定步驟**：

1. **安裝 Cloudflare Tunnel (cloudflared)**：
```bash
# Windows
winget install --id Cloudflare.cloudflared

# macOS
brew install cloudflare/cloudflare/cloudflared

# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

2. **登入 Cloudflare**：
```bash
cloudflared tunnel login
```

3. **建立 Tunnel**：
```bash
cloudflared tunnel create esp32-asr-mvp
```

4. **配置 Tunnel** (`~/.cloudflared/config.yml`)：
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /path/to/<TUNNEL_ID>.json

ingress:
  - hostname: esp32-asr.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

5. **設定 DNS**：
```bash
cloudflared tunnel route dns esp32-asr-mvp esp32-asr.yourdomain.com
```

6. **啟動 Tunnel**：
```bash
cloudflared tunnel run esp32-asr-mvp
```

**ESP32 連線配置**：
```cpp
// ESP32 韌體中的伺服器位址
const char* WS_HOST = "esp32-asr.yourdomain.com";
const int WS_PORT = 443;  // HTTPS/WSS
const bool USE_SSL = true;

// WebSocket 端點
const char* WS_AUDIO_PATH = "/ws_audio";
const char* WS_CTRL_PATH = "/ws_ctrl";
const char* WS_CAMERA_PATH = "/ws_camera";
```

**Web UI 連線配置**：
```javascript
// Web UI 中的 WebSocket 連線
const WS_URL = 'wss://esp32-asr.yourdomain.com/ws_ui';
const API_BASE = 'https://esp32-asr.yourdomain.com/api';
```

### 環境變數

```bash
# ASR 服務
ASR_API_KEY=your_dashscope_api_key
ASR_ENDPOINT=wss://dashscope.aliyuncs.com/api/v1/services/audio/asr

# 視覺模型
VISION_API_KEY=your_vision_api_key
VISION_MODEL=qwen-vl-plus
VISION_ENDPOINT=https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation

# 伺服器配置
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# Cloudflare Tunnel（可選，用於本機開發）
CLOUDFLARE_TUNNEL_ENABLED=true
PUBLIC_URL=https://esp32-asr.yourdomain.com

# 系統參數
MAX_CONCURRENT_REQUESTS=1
COOLDOWN_SECONDS=3
CAPTURE_TIMEOUT_SECONDS=5
VISION_TIMEOUT_SECONDS=15
EVENT_BUFFER_SIZE=100
```

### Docker Compose（可選）

**方案 A：使用 Cloudflare Tunnel（推薦用於本機開發）**

```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - ASR_API_KEY=${ASR_API_KEY}
      - VISION_API_KEY=${VISION_API_KEY}
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8000
    volumes:
      - ./logs:/app/logs

  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - backend
    restart: unless-stopped
```

**方案 B：傳統 Nginx + SSL（用於 VPS 部署）**

```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - ASR_API_KEY=${ASR_API_KEY}
      - VISION_API_KEY=${VISION_API_KEY}
    volumes:
      - ./logs:/app/logs

  web:
    build: ./web
    ports:
      - "3000:80"
    depends_on:
      - backend

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - backend
      - web
```

### 效能考量

- **預期負載**：1 個 ESP32 裝置，1-5 個 Web UI 客戶端
- **音訊頻寬**：16kHz × 2 bytes × 1 channel = 32 KB/s
- **記憶體使用**：
  - 音訊緩衝區：~160 KB（5 秒）
  - 事件緩衝區：~100 KB（100 筆事件）
  - 影像緩衝區：~200 KB（1 張 JPEG）
  - 總計：~500 KB（不含框架開銷）
- **CPU 使用**：主要為 I/O 密集，CPU 使用率應低於 10%

### 監控指標

- WebSocket 連線數
- ASR 延遲（音訊發送至文字返回）
- 觸發頻率
- 拍照成功率
- 視覺模型延遲
- 錯誤率（按類型分類）
- 重連次數

## 本機開發工作流程

使用 Cloudflare Tunnel 的完整開發流程：

1. **啟動後端服務**（本機）：
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

2. **啟動 Cloudflare Tunnel**（另一個終端）：
```bash
cloudflared tunnel run esp32-asr-mvp
```

3. **開啟 Web UI**（瀏覽器）：
```
https://esp32-asr.yourdomain.com
```

4. **配置 ESP32**（燒錄韌體前）：
```cpp
const char* WS_HOST = "esp32-asr.yourdomain.com";
const int WS_PORT = 443;
const bool USE_SSL = true;
```

5. **測試完整流程**：
   - ESP32 連線至 Cloudflare Tunnel
   - 說出觸發詞
   - 觀察 Web UI 顯示結果

**優勢**：
- 無需 VPS，本機即可完整測試
- 自動 HTTPS/WSS 加密
- ESP32 可從任何網路連線（無需在同一區網）
- 方便展示及遠端除錯

## 未來擴展

MVP 完成後可考慮的擴展：

1. **多裝置支援**：支援多個 ESP32 同時連線
2. **使用者帳號**：新增身份驗證及多使用者支援
3. **語音回饋**：TTS 結果回傳至 ESP32
4. **持久化儲存**：事件及影像儲存至資料庫
5. **進階觸發**：使用 NLU 模型進行語義理解
6. **視覺模型切換**：UI 支援選擇不同的視覺模型
7. **導航功能**：整合 IMU 及導航狀態機
8. **影片錄製**：支援短影片錄製及分析
9. **Cloudflare Access**：整合 Cloudflare Access 進行身份驗證
10. **邊緣運算**：使用 Cloudflare Workers 進行預處理
