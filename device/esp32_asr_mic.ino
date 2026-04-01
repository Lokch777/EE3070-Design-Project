/*
 * ESP32-S3 Smart Microphone → Backend WebSocket (0.75x Speed)
 * 線性插值：1600 → 2133 samples，語音放慢至 0.75x 送去 ASR
 */

#include <WiFi.h>
#include <esp_wifi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "driver/i2s.h"

using namespace websockets;

// ===== 使用者設定區 =====
const char* WIFI_SSID     = "reallybenchan";
const char* WIFI_PASSWORD = "test1234";
const char* WS_HOST       = "72.146.235.228";
const uint16_t WS_PORT    = 8080;
const bool USE_SSL        = false;
const char* DEVICE_ID     = "default";
const char* WS_AUDIO_PATH = "/ws_audio";

// ===== 音訊參數 =====
static const uint32_t AUDIO_SAMPLE_RATE = 16000;
static const size_t   AUDIO_SAMPLES     = 1600;    // 原始 100ms chunk
#define PLAYBACK_SPEED   0.525f                      // 0.5 / 0.75 / 1.0
#define STRETCHED_SAMPLES ((int)(AUDIO_SAMPLES / PLAYBACK_SPEED))  // 2133
#define SHIFT_BITS       11
#define DMA_READ_SAMPLES 1024

// ===== INMP441 腳位 =====
#define MIC_BCK_PIN  47
#define MIC_WS_PIN   20
#define MIC_SD_PIN   21
#define I2S_PORT_IN  I2S_NUM_0

// ===== 全域變數 =====
WebsocketsClient wsAudio;
bool audioConnected               = false;
unsigned long lastReconnectAttempt = 0;
const unsigned long reconnectIntervalMs = 3000;
volatile bool need_pong           = false;

void connectWiFi();
void connectWebSockets();
bool initMicrophone();
void streamAudio();

// ========================================================
void setup() {
  Serial.begin(9600);
  delay(500);
  Serial.println("\n=== ESP32-S3 Smart Audio (0.75x Speed) ===");
  Serial.printf("    Original:  %d samples (100ms)\n", (int)AUDIO_SAMPLES);
  Serial.printf("    Stretched: %d samples (133ms @ 0.75x)\n", STRETCHED_SAMPLES);

  if (!initMicrophone()) {
    Serial.println("❌ 麥克風初始化失敗！");
    while (true) { delay(1000); }
  }
  Serial.println("✅ 麥克風就緒");

  connectWiFi();

  wsAudio.onMessage([](WebsocketsMessage message) {
    if (message.isText()) {
      StaticJsonDocument<128> doc;
      if (!deserializeJson(doc, message.data()) &&
          strcmp(doc["type"] | "", "ping") == 0) {
        need_pong = true;
      }
    }
  });

  connectWebSockets();
  Serial.println("✅ 系統啟動！開始串流...");
}

// ========================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  audioConnected = wsAudio.available();
  if (millis() - lastReconnectAttempt > reconnectIntervalMs) {
    if (!audioConnected) connectWebSockets();
    lastReconnectAttempt = millis();
  }

  if (audioConnected) {
    wsAudio.poll();
    if (need_pong) {
      wsAudio.send("{\"type\":\"pong\"}");
      need_pong = false;
    }
    streamAudio();
  }
}

// ========================================================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi connected");
  esp_wifi_set_ps(WIFI_PS_NONE);
}

// ========================================================
void connectWebSockets() {
  if (audioConnected) return;
  Serial.println("[WS] Connecting...");
  String url = String(USE_SSL ? "wss://" : "ws://")
             + WS_HOST + ":" + String(WS_PORT)
             + WS_AUDIO_PATH + "?device_id=" + String(DEVICE_ID);
  audioConnected = wsAudio.connect(url);
  if (audioConnected) Serial.println("✅ [WS] Connected!");
  else Serial.println("❌ [WS] Failed, will retry...");
}

// ========================================================
bool initMicrophone() {
  i2s_config_t i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = AUDIO_SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 512,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pin_config = {
    .bck_io_num   = MIC_BCK_PIN,
    .ws_io_num    = MIC_WS_PIN,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = MIC_SD_PIN
  };
  if (i2s_driver_install(I2S_PORT_IN, &i2s_config, 0, NULL) != ESP_OK) return false;
  if (i2s_set_pin(I2S_PORT_IN, &pin_config) != ESP_OK) return false;
  return true;
}

// ========================================================
void streamAudio() {
  static int32_t rawBuffer32[DMA_READ_SAMPLES];
  static int16_t accumBuffer[AUDIO_SAMPLES];
  static int16_t stretchBuffer[STRETCHED_SAMPLES];
  static int     accumCount = 0;

  static float dc_offset = 0.0f;
  const float alpha = 0.99f;
  const int FADE_SAMPLES = 32;

  size_t bytesRead = 0;
  if (i2s_read(I2S_PORT_IN, rawBuffer32, sizeof(rawBuffer32),
               &bytesRead, pdMS_TO_TICKS(10)) != ESP_OK) return;
  if (bytesRead == 0) return;

  int samplesRead = bytesRead / 4;

  for (int i = 0; i < samplesRead && accumCount < (int)AUDIO_SAMPLES; i += 2) {
    int32_t shifted = rawBuffer32[i] >> SHIFT_BITS;
    dc_offset = (alpha * dc_offset) + ((1.0f - alpha) * (float)shifted);
    int32_t clean = shifted - (int32_t)dc_offset;
    if (clean > 32767)  clean = 32767;
    if (clean < -32768) clean = -32768;
    accumBuffer[accumCount++] = (int16_t)clean;
  }

  if (accumCount >= (int)AUDIO_SAMPLES) {

    // ── 線性插值 1600 → 2133 ──
    for (int i = 0; i < STRETCHED_SAMPLES; i++) {
      float srcPos = i * (AUDIO_SAMPLES - 1.0f) / (STRETCHED_SAMPLES - 1.0f);
      int   srcIdx = (int)srcPos;
      float frac   = srcPos - srcIdx;
      if (srcIdx >= (int)AUDIO_SAMPLES - 1) {
        stretchBuffer[i] = accumBuffer[AUDIO_SAMPLES - 1];
      } else {
        stretchBuffer[i] = (int16_t)(
          accumBuffer[srcIdx]     * (1.0f - frac) +
          accumBuffer[srcIdx + 1] * frac
        );
      }
    }

    // ── Crossfade 消除 tick ──
    for (int i = 0; i < FADE_SAMPLES; i++) {
      float gain = (float)i / FADE_SAMPLES;
      stretchBuffer[i] = (int16_t)(stretchBuffer[i] * gain);
    }
    for (int i = 0; i < FADE_SAMPLES; i++) {
      float gain = (float)(FADE_SAMPLES - i) / FADE_SAMPLES;
      stretchBuffer[STRETCHED_SAMPLES - FADE_SAMPLES + i] =
        (int16_t)(stretchBuffer[STRETCHED_SAMPLES - FADE_SAMPLES + i] * gain);
    }

    if (!wsAudio.sendBinary((const char*)stretchBuffer, STRETCHED_SAMPLES * 2)) {
      Serial.println("❌ [WS] Send failed, reconnecting...");
      audioConnected = false;
      wsAudio.close();
    }

    accumCount = 0;
  }
}
