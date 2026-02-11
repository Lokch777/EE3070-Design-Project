# 需求文件：ESP32 ASR 捕捉視覺 MVP

## 簡介

本系統為一個「永遠聆聽」的 ESP32 眼鏡/裝置，透過持續音訊串流、自動語音辨識（ASR）、觸發詞檢測、按需拍照及視覺模型分析，實現語音控制的物品識別功能。系統由 ESP32 裝置、VPS 後端服務及網頁 UI 組成，支援中文語音指令觸發視覺辨識。

## 術語表

- **ESP32_Device**：搭載 I2S 麥克風及 ESP32-CAM 的硬體裝置
- **VPS_Backend**：運行於 VPS 的後端服務，負責 WebSocket 閘道、ASR 橋接、觸發引擎、拍照協調、視覺模型呼叫
- **ASR_Service**：DashScope/Model Studio Qwen3-ASR-Flash-Realtime 即時語音辨識服務
- **VisionLLMAdapter**：視覺模型適配器介面，可連接 Qwen Omni Flash 或其他多模態模型
- **Web_UI**：瀏覽器端使用者介面，顯示 ASR 結果、觸發事件、快照及視覺辨識結果
- **Trigger_Command**：觸發詞指令，例如「請你幫我識別物品」、「幫我認下呢個係咩」
- **CAPTURE_Command**：VPS 發送給 ESP32 的拍照指令
- **req_id**：請求識別碼，用於關聯完整的觸發→拍照→視覺辨識流程

## 需求

### 需求 1：持續音訊串流與 ASR

**使用者故事：** 作為使用者，我希望系統能持續接收我的語音並提供即時文字轉錄，以便我可以透過語音與系統互動。

#### 驗收標準

1. WHEN ESP32_Device 連接到 VPS_Backend THEN THE VPS_Backend SHALL 建立 WebSocket 連線並開始接收音訊串流
2. WHEN VPS_Backend 接收到音訊資料 THEN THE VPS_Backend SHALL 將音訊轉發至 ASR_Service 並接收轉錄結果
3. WHEN ASR_Service 返回最終文字（final text）THEN THE VPS_Backend SHALL 將結果廣播至 Web_UI
4. THE VPS_Backend SHALL 支援 PCM16 單聲道 16kHz 音訊格式
5. WHEN 音訊串流中斷超過 5 秒 THEN THE VPS_Backend SHALL 記錄錯誤事件並嘗試重新建立 ASR 連線

### 需求 2：觸發詞檢測與事件生成

**使用者故事：** 作為使用者，我希望說出特定指令時系統能自動觸發拍照，以便進行物品識別。

#### 驗收標準

1. WHEN ASR_Service 返回最終文字包含觸發關鍵詞（「識別物品」、「認下呢個係咩」或語義等價詞）THEN THE VPS_Backend SHALL 生成 CAPTURE 請求
2. WHEN 生成 CAPTURE 請求 THEN THE VPS_Backend SHALL 分配唯一的 req_id 並記錄觸發時間
3. WHEN 上一個 CAPTURE 請求尚未完成 THEN THE VPS_Backend SHALL 拒絕新的觸發請求並記錄冷卻事件
4. THE VPS_Backend SHALL 在成功觸發後設定至少 3 秒的冷卻時間，防止重複觸發
5. WHEN 觸發事件生成 THEN THE VPS_Backend SHALL 廣播 trigger_fired 事件至 Web_UI

### 需求 3：按需拍照與影像接收

**使用者故事：** 作為系統，我需要在觸發時向 ESP32 請求單張照片，以便進行視覺分析。

#### 驗收標準

1. WHEN CAPTURE 請求生成 THEN THE VPS_Backend SHALL 透過 WebSocket 發送 CAPTURE_Command 至 ESP32_Device，包含 req_id
2. WHEN ESP32_Device 接收到 CAPTURE_Command THEN THE ESP32_Device SHALL 在 2 秒內拍攝一張 JPEG 影像並上傳至 VPS_Backend
3. WHEN VPS_Backend 接收到 JPEG 影像 THEN THE VPS_Backend SHALL 驗證 req_id 匹配並記錄 capture_received 事件
4. IF ESP32_Device 在 5 秒內未回應 JPEG THEN THE VPS_Backend SHALL 記錄超時錯誤並將該 req_id 標記為失敗
5. THE ESP32_Device SHALL 上傳解析度不超過 640x480 的 JPEG 影像

### 需求 4：視覺模型呼叫與結果返回

**使用者故事：** 作為系統，我需要將拍攝的影像及使用者指令發送至視覺模型進行分析，以便提供物品識別結果。

#### 驗收標準

1. WHEN VPS_Backend 接收到有效的 JPEG 影像 THEN THE VPS_Backend SHALL 呼叫 VisionLLMAdapter 並傳入影像及觸發指令文字
2. WHEN VisionLLMAdapter 返回文字結果 THEN THE VPS_Backend SHALL 記錄 vision_result 事件並廣播至 Web_UI
3. IF VisionLLMAdapter 呼叫失敗或超時（15 秒）THEN THE VPS_Backend SHALL 記錄錯誤事件並返回錯誤訊息至 Web_UI
4. THE VisionLLMAdapter SHALL 支援可抽換的視覺模型後端（例如 Qwen Omni Flash）
5. THE VPS_Backend SHALL 在視覺模型呼叫期間維持 req_id 關聯

### 需求 5：網頁 UI 即時顯示

**使用者故事：** 作為使用者，我希望在網頁上即時看到語音轉錄、觸發事件、快照及識別結果，以便了解系統狀態。

#### 驗收標準

1. WHEN Web_UI 連接到 VPS_Backend THEN THE VPS_Backend SHALL 透過 WebSocket 推送即時事件
2. WHEN ASR 最終文字產生 THEN THE Web_UI SHALL 顯示最新的轉錄文字
3. WHEN 觸發事件發生 THEN THE Web_UI SHALL 顯示 req_id、觸發時間及觸發指令
4. WHEN JPEG 影像接收 THEN THE Web_UI SHALL 顯示最新的快照影像
5. WHEN 視覺模型結果返回 THEN THE Web_UI SHALL 顯示識別結果文字
6. THE Web_UI SHALL 支援載入最近 N 筆（至少 20 筆）歷史事件記錄

### 需求 6：網路斷線自動重連

**使用者故事：** 作為系統，我需要在網路中斷時自動重新連線，以確保服務的可靠性。

#### 驗收標準

1. WHEN ESP32_Device 與 VPS_Backend 的 WebSocket 連線中斷 THEN THE ESP32_Device SHALL 在 3 秒內嘗試重新連線
2. WHEN VPS_Backend 與 ASR_Service 的連線中斷 THEN THE VPS_Backend SHALL 在 5 秒內嘗試重新建立 ASR 會話
3. WHEN Web_UI 與 VPS_Backend 的 WebSocket 連線中斷 THEN THE Web_UI SHALL 顯示斷線狀態並自動嘗試重連
4. THE VPS_Backend SHALL 在重連成功後恢復至 LISTENING 狀態
5. IF 重連嘗試連續失敗 3 次 THEN THE System SHALL 記錄嚴重錯誤並通知使用者

### 需求 7：API 金鑰安全管理

**使用者故事：** 作為系統管理員，我需要確保雲端 API 金鑰僅存放於 VPS 後端，以防止金鑰洩露。

#### 驗收標準

1. THE VPS_Backend SHALL 從環境變數或安全配置檔讀取 ASR_Service 及 VisionLLMAdapter 的 API 金鑰
2. THE Web_UI SHALL NOT 包含任何 API 金鑰或敏感憑證
3. THE ESP32_Device SHALL NOT 儲存或傳輸任何雲端 API 金鑰
4. WHEN VPS_Backend 啟動 THEN THE VPS_Backend SHALL 驗證所有必要的 API 金鑰已正確配置
5. IF API 金鑰缺失或無效 THEN THE VPS_Backend SHALL 拒絕啟動並記錄錯誤

### 需求 8：基礎日誌與事件追蹤

**使用者故事：** 作為開發者，我需要系統記錄關鍵事件及錯誤，以便除錯及監控系統運行狀態。

#### 驗收標準

1. THE VPS_Backend SHALL 記錄所有關鍵事件（asr_final、trigger_fired、capture_requested、capture_received、vision_result、error）
2. THE VPS_Backend SHALL 維護至少最近 100 筆事件的記憶體環形緩衝區
3. WHEN Web_UI 請求歷史記錄 THEN THE VPS_Backend SHALL 返回最近 N 筆事件（可配置，預設 20）
4. THE VPS_Backend SHALL 為每個事件記錄時間戳記、事件類型、req_id（如適用）及相關資料
5. WHEN 發生錯誤 THEN THE VPS_Backend SHALL 記錄錯誤類型、錯誤訊息及堆疊追蹤（如適用）

## 假設

1. ESP32_Device 的麥克風輸出為 PCM16 單聲道 16kHz 格式
2. ESP32_Device 的相機可輸出 JPEG 格式，解析度為 640x480 或更低
3. VPS 具備穩定的網路連線及足夠的頻寬處理即時音訊串流
4. ASR_Service（Qwen3-ASR-Flash-Realtime）支援 WebSocket 連線及伺服器端 VAD（語音活動檢測）
5. VisionLLMAdapter 可透過 HTTP API 或 SDK 呼叫，回應時間在 15 秒內
6. 使用者主要使用中文（粵語或普通話）進行語音指令
7. MVP 階段不需要使用者帳號系統或身份驗證
8. MVP 階段不需要 TTS（文字轉語音）或音訊回饋至 ESP32

## 開放問題

1. ESP32 硬體型號及具體的麥克風/相機模組規格為何？
2. VPS 的網路環境及預期的並發連線數為何？
3. 觸發詞檢測是使用簡單關鍵詞匹配還是需要語義理解（例如使用 NLU 模型）？
4. 視覺模型的具體選擇為何（Qwen Omni Flash 或其他）？是否需要支援多個模型切換？
5. 是否需要支援多個 ESP32 裝置同時連線？
6. 歷史事件記錄是否需要持久化至資料庫，還是記憶體環形緩衝區即可？
7. 是否需要支援手動觸發拍照（透過 Web_UI 或 ESP32 按鈕）？
8. 音訊串流的延遲要求為何（例如端到端延遲需在 X 秒內）？
9. 是否需要支援 HTTPS/WSS（TLS 加密）連線？
10. MVP 完成後的部署環境為何（Docker、裸機、雲端服務）？

## MVP 成功定義

系統達成以下目標即視為 MVP 成功：

1. **完整流程驗證**：使用者說出觸發指令 → 系統拍攝快照 → 視覺模型返回識別結果（文字），整個流程在 10 秒內完成
2. **斷線恢復**：ESP32 或 VPS 網路中斷後，系統能自動重連並恢復至 LISTENING 狀態
3. **即時顯示**：Web_UI 能即時顯示 ASR 文字、觸發事件、快照及視覺辨識結果
4. **安全性**：所有 API 金鑰僅存放於 VPS 後端，前端及 ESP32 無法存取
