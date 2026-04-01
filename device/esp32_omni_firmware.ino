/*
 * ESP32-S3 Omni Realtime Firmware
 *
 * Changes from esp32_full_firmware.ino:
 *   - Removed keyword-trigger / ASR / TTS separate flows
 *   - Single WebSocket connection to backend /ws/device
 *   - Continuously streams mic audio chunks (PCM-16 base64)
 *   - Sends one image frame per CAMERA_SEND_INTERVAL_MS
 *   - VAD-based audio_commit triggers Qwen response
 *   - Plays back PCM-16 audio deltas from tts_audio_delta messages
 *
 * Backend: start_server.sh  (uvicorn backend.realtime_gateway:app)
 * Protocol: see backend/realtime_gateway.py header comment
 */

#include <WiFi.h>
#include <esp_wifi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "driver/i2s.h"
#include "freertos/semphr.h"
#include "mbedtls/base64.h"

using namespace websockets;

// ===== WiFi / Server =====
// ⚠️  CONFIGURE BEFORE FLASHING — replace the placeholder values below
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PW";
const char* WS_HOST       = "YOUR_BACKEND_IP";   // e.g. "192.168.1.100"
const uint16_t WS_PORT    = 8765;                // REALTIME_PORT in .env
const char* WS_PATH       = "/ws/device";

// ===== MIC — proven settings =====
static const uint32_t AUDIO_SAMPLE_RATE = 16000;
static const size_t   AUDIO_SAMPLES     = 320;   // 20 ms at 16 kHz
#define SHIFT_BITS     11
#define DMA_READ_SAMPLES 256
#define MIC_BCK_PIN    47
#define MIC_WS_PIN     20
#define MIC_SD_PIN     21
#define I2S_PORT_MIC   I2S_NUM_0

// ===== SPEAKER =====
#define SPK_BCK_PIN    46
#define SPK_WS_PIN      3
#define SPK_SD_PIN     14
#define I2S_PORT_SPK   I2S_NUM_1
#define SPK_SAMPLE_RATE 16000
#define SPK_VOLUME      0.4f

// ===== Camera Pins (ESP32-S3 OV2640 board) =====
#define PWDN_GPIO_NUM   -1
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM   15
#define SIOD_GPIO_NUM    4
#define SIOC_GPIO_NUM    5
#define Y9_GPIO_NUM     16
#define Y8_GPIO_NUM     17
#define Y7_GPIO_NUM     18
#define Y6_GPIO_NUM     12
#define Y5_GPIO_NUM     10
#define Y4_GPIO_NUM      8
#define Y3_GPIO_NUM      9
#define Y2_GPIO_NUM     11
#define VSYNC_GPIO_NUM   6
#define HREF_GPIO_NUM    7
#define PCLK_GPIO_NUM   13

// ===== Camera / VAD settings =====
#define CAMERA_SEND_INTERVAL_MS  1000   // send one JPEG every 1 s
#define VAD_SILENCE_CHUNKS        50    // ~1 s of silence → audio_commit
#define VAD_ENERGY_THRESHOLD     300    // RMS threshold for speech detection

// ===== Playback ring buffer =====
#define PLAYBACK_RING_BYTES     32768
#define PLAYBACK_START_THRESH    8192
#define PLAYBACK_IO_CHUNK        1024
#define DECODE_SCRATCH_BYTES    16384

// ===== Globals =====
static SemaphoreHandle_t wsMutex         = nullptr;
static portMUX_TYPE      playbackMux     = portMUX_INITIALIZER_UNLOCKED;

static volatile bool playbackActive      = false;
static volatile bool playbackStarted     = false;
static volatile bool responseDone        = false;

WebsocketsClient ws;
bool wsConnected = false;
unsigned long lastReconnectMs  = 0;
unsigned long lastCameraSendMs = 0;
volatile bool needPong = false;

// VAD state
static int  silenceChunks    = 0;
static bool speechDetected   = false;
static bool waitingForResponse = false;

// PSRAM buffers
static int32_t* rawBuf32      = nullptr;
static int16_t* accumBuf      = nullptr;
static int16_t* b64SrcBuf     = nullptr;
static uint8_t* playbackRing  = nullptr;
static uint8_t* decodeScratch = nullptr;
static int      accumCount    = 0;
static float    dcOffset      = 0.0f;
static volatile size_t pbWritePos    = 0;
static volatile size_t pbReadPos     = 0;
static volatile size_t pbBuffered    = 0;

// Base64 scratch (worst-case for AUDIO_SAMPLES * 2 bytes)
#define B64_OUT_MAX  ((AUDIO_SAMPLES * 2 * 4 / 3) + 8)
static char b64Out[B64_OUT_MAX + 4];

// ===== Forward declarations =====
void connectWiFi();
void connectWS();
bool initMic();
bool initSpeaker();
bool initCamera();
bool initPsram();
void streamMicChunk();
void sendCameraFrame();
void playbackTask(void* param);
void micStreamTask(void* param);
void resetPlayback();
bool writePbBytes(const uint8_t* data, size_t len);
size_t readPbBytes(uint8_t* out, size_t maxLen);
size_t getPbBuffered();

// ===== Playback ring buffer helpers =====
void resetPlayback() {
  portENTER_CRITICAL(&playbackMux);
  pbWritePos = 0; pbReadPos = 0; pbBuffered = 0;
  playbackStarted = false; playbackActive = false; responseDone = false;
  portEXIT_CRITICAL(&playbackMux);
  i2s_zero_dma_buffer(I2S_PORT_SPK);
}

bool writePbBytes(const uint8_t* data, size_t len) {
  if (!playbackRing || !data || len == 0 || len > PLAYBACK_RING_BYTES) return false;
  bool written = false;
  portENTER_CRITICAL(&playbackMux);
  if (PLAYBACK_RING_BYTES - pbBuffered >= len) {
    size_t first = min(len, PLAYBACK_RING_BYTES - pbWritePos);
    memcpy(playbackRing + pbWritePos, data, first);
    if (len > first) memcpy(playbackRing, data + first, len - first);
    pbWritePos = (pbWritePos + len) % PLAYBACK_RING_BYTES;
    pbBuffered += len;
    written = true;
  }
  portEXIT_CRITICAL(&playbackMux);
  return written;
}

size_t readPbBytes(uint8_t* out, size_t maxLen) {
  if (!playbackRing || !out || maxLen == 0) return 0;
  size_t n = 0;
  portENTER_CRITICAL(&playbackMux);
  if (pbBuffered > 0) {
    n = min(maxLen, pbBuffered);
    size_t first = min(n, PLAYBACK_RING_BYTES - pbReadPos);
    memcpy(out, playbackRing + pbReadPos, first);
    if (n > first) memcpy(out + first, playbackRing, n - first);
    pbReadPos = (pbReadPos + n) % PLAYBACK_RING_BYTES;
    pbBuffered -= n;
  }
  portEXIT_CRITICAL(&playbackMux);
  return n;
}

size_t getPbBuffered() {
  size_t v;
  portENTER_CRITICAL(&playbackMux);
  v = pbBuffered;
  portEXIT_CRITICAL(&playbackMux);
  return v;
}

// ===== Playback task (Core 0) =====
void playbackTask(void* param) {
  static uint8_t chunk[PLAYBACK_IO_CHUNK];
  for (;;) {
    size_t avail = getPbBuffered();
    if (!playbackStarted && avail >= PLAYBACK_START_THRESH) {
      portENTER_CRITICAL(&playbackMux);
      playbackStarted = true;
      portEXIT_CRITICAL(&playbackMux);
    }
    if (playbackStarted && avail > 0) {
      size_t n = readPbBytes(chunk, PLAYBACK_IO_CHUNK);
      if (n > 0) {
        // Apply volume
        int16_t* s = (int16_t*)chunk;
        for (size_t i = 0; i < n / 2; i++) {
          int32_t v = (int32_t)(s[i] * SPK_VOLUME);
          if (v >  32767) v =  32767;
          if (v < -32768) v = -32768;
          s[i] = (int16_t)v;
        }
        size_t written = 0;
        i2s_write(I2S_PORT_SPK, chunk, n, &written, pdMS_TO_TICKS(20));
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

// ===== Mic stream task (Core 1) =====
void micStreamTask(void* param) {
  for (;;) {
    if (wsConnected && !waitingForResponse) {
      streamMicChunk();
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

// ===== PSRAM init =====
bool initPsram() {
  if (!psramFound()) { Serial.println("❌ PSRAM not found"); return false; }
  rawBuf32      = (int32_t*)ps_malloc(DMA_READ_SAMPLES * sizeof(int32_t));
  accumBuf      = (int16_t*)ps_malloc(AUDIO_SAMPLES    * sizeof(int16_t));
  b64SrcBuf     = (int16_t*)ps_malloc(AUDIO_SAMPLES    * sizeof(int16_t));
  playbackRing  = (uint8_t*)ps_malloc(PLAYBACK_RING_BYTES);
  decodeScratch = (uint8_t*)ps_malloc(DECODE_SCRATCH_BYTES);
  return rawBuf32 && accumBuf && b64SrcBuf && playbackRing && decodeScratch;
}

// ===== WiFi =====
void connectWiFi() {
  Serial.printf("🌐 Connecting to %s ...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  esp_wifi_set_max_tx_power(68); // ~17 dBm — reduce heat
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries++ < 30) {
    delay(500); Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n✅ WiFi: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n❌ WiFi failed — retrying in loop");
  }
}

// ===== WebSocket =====
void connectWS() {
  String url = String("ws://") + WS_HOST + ":" + WS_PORT + WS_PATH;
  Serial.printf("🔌 Connecting to %s\n", url.c_str());
  if (ws.connect(url)) {
    wsConnected = true;
    Serial.println("✅ WS connected");
  } else {
    wsConnected = false;
    Serial.println("❌ WS connect failed");
  }
}

// ===== Mic → WS =====
void streamMicChunk() {
  size_t bytesRead = 0;
  if (i2s_read(I2S_PORT_MIC, rawBuf32, DMA_READ_SAMPLES * sizeof(int32_t),
               &bytesRead, pdMS_TO_TICKS(10)) != ESP_OK || bytesRead == 0) return;

  int samplesRead = bytesRead / 4;
  for (int i = 0; i < samplesRead && accumCount < (int)AUDIO_SAMPLES; i += 2) {
    int32_t shifted = rawBuf32[i] >> SHIFT_BITS;
    dcOffset = 0.99f * dcOffset + 0.01f * (float)shifted;
    int32_t clean = shifted - (int32_t)dcOffset;
    if (clean >  32767) clean =  32767;
    if (clean < -32768) clean = -32768;
    accumBuf[accumCount++] = (int16_t)clean;
  }

  if (accumCount < (int)AUDIO_SAMPLES) return;

  // Copy to b64SrcBuf for encoding
  memcpy(b64SrcBuf, accumBuf, AUDIO_SAMPLES * sizeof(int16_t));
  accumCount = 0;

  // Simple RMS-based VAD
  int64_t sumSq = 0;
  for (size_t i = 0; i < AUDIO_SAMPLES; i++) sumSq += (int64_t)b64SrcBuf[i] * b64SrcBuf[i];
  int rms = (int)sqrt((double)sumSq / AUDIO_SAMPLES);

  bool isSpeech = (rms > VAD_ENERGY_THRESHOLD);
  if (isSpeech) {
    speechDetected = true;
    silenceChunks  = 0;
  } else if (speechDetected) {
    silenceChunks++;
  }

  // Base64-encode the PCM-16 chunk
  size_t b64Len = 0;
  mbedtls_base64_encode(
    (unsigned char*)b64Out, B64_OUT_MAX, &b64Len,
    (const unsigned char*)b64SrcBuf, AUDIO_SAMPLES * sizeof(int16_t)
  );
  b64Out[b64Len] = '\0';

  // Build JSON using snprintf to avoid ArduinoJson heap allocation for large buffers
  static char jsonBuf[B64_OUT_MAX + 64];
  snprintf(jsonBuf, sizeof(jsonBuf),
           "{\"type\":\"audio_chunk\",\"pcm16_b64\":\"%s\"}", b64Out);

  if (xSemaphoreTake(wsMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
    bool ok = ws.send(jsonBuf);
    xSemaphoreGive(wsMutex);
    if (!ok) {
      wsConnected = false;
      ws.close();
      return;
    }
  }

  // VAD: enough silence after speech → commit + request response
  if (speechDetected && silenceChunks >= VAD_SILENCE_CHUNKS) {
    speechDetected = false;
    silenceChunks  = 0;
    waitingForResponse = true;

    if (xSemaphoreTake(wsMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
      ws.send("{\"type\":\"audio_commit\"}");
      xSemaphoreGive(wsMutex);
    }
    Serial.println("🎤 audio_commit sent — waiting for response");
  }
}

// ===== Camera frame → WS =====
void sendCameraFrame() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) return;

  // Base64-encode JPEG
  size_t b64Len = 0;
  size_t maxB64 = (fb->len * 4 / 3) + 8;
  uint8_t* b64Buf = (uint8_t*)ps_malloc(maxB64 + 1);
  if (!b64Buf) { esp_camera_fb_return(fb); return; }

  mbedtls_base64_encode(b64Buf, maxB64, &b64Len, fb->buf, fb->len);
  b64Buf[b64Len] = '\0';
  esp_camera_fb_return(fb);

  // Build JSON — allocate on heap to handle large base64
  size_t jsonLen = b64Len + 64;
  char* jsonBuf = (char*)ps_malloc(jsonLen);
  if (!jsonBuf) { free(b64Buf); return; }
  snprintf(jsonBuf, jsonLen, "{\"type\":\"image_frame\",\"jpeg_b64\":\"%s\"}", (char*)b64Buf);
  // ps_malloc() allocations are freed with standard free() on ESP32 — this is correct
  free(b64Buf);

  if (xSemaphoreTake(wsMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
    ws.send(jsonBuf);
    xSemaphoreGive(wsMutex);
  }
  // ps_malloc() allocations are freed with standard free() on ESP32 — this is correct
  free(jsonBuf);
  Serial.println("📷 Camera frame sent");
}

// ===== Setup =====
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== ESP32-S3 Omni Realtime Firmware ===");

  if (!initPsram()) {
    Serial.println("❌ PSRAM alloc failed — halting");
    while (true) delay(1000);
  }
  Serial.printf("✅ PSRAM: %u KB free\n", ESP.getFreePsram() / 1024);

  if (!initSpeaker()) Serial.println("❌ Speaker init failed");
  else                Serial.println("✅ Speaker ready");

  if (!initMic()) {
    Serial.println("❌ Mic init failed — halting");
    while (true) delay(1000);
  }
  Serial.println("✅ Mic ready");

  if (!initCamera()) Serial.println("❌ Camera init failed (continuing)");
  else               Serial.println("✅ Camera ready");

  wsMutex = xSemaphoreCreateMutex();

  // ── WS message callback ──
  ws.onMessage([](WebsocketsMessage msg) {
    if (!msg.isText()) return;

    // Use a filter to avoid allocating large ArduinoJson docs
    StaticJsonDocument<128> filter;
    filter["type"]      = true;
    filter["audio_b64"] = true;
    filter["text"]      = true;
    filter["message"]   = true;

    DynamicJsonDocument doc(4096);
    if (deserializeJson(doc, msg.data(), DeserializationOption::Filter(filter))) return;

    const char* type = doc["type"] | "";

    if (strcmp(type, "tts_audio_delta") == 0) {
      const char* b64 = doc["audio_b64"] | "";
      size_t b64Len   = strlen(b64);
      if (b64Len == 0) return;

      size_t decLen = 0;
      size_t maxDec = (b64Len * 3 / 4) + 4;
      if (maxDec > DECODE_SCRATCH_BYTES) {
        Serial.println("⚠️ audio delta too large — skipped");
        return;
      }
      if (mbedtls_base64_decode(decodeScratch, DECODE_SCRATCH_BYTES, &decLen,
                                (const unsigned char*)b64, b64Len) == 0 && decLen > 0) {
        if (!writePbBytes(decodeScratch, decLen)) {
          Serial.println("⚠️ playback buffer full");
        } else {
          playbackActive = true;
        }
      }
      return;
    }

    if (strcmp(type, "text_delta") == 0) {
      const char* txt = doc["text"] | "";
      if (txt[0]) Serial.printf("📝 %s", txt);
      return;
    }

    if (strcmp(type, "response_done") == 0) {
      Serial.println("\n✅ response_done — listening again");
      waitingForResponse = false;
      responseDone = true;
      return;
    }

    if (strcmp(type, "pong") == 0) {
      return;
    }

    if (strcmp(type, "error") == 0) {
      const char* err = doc["message"] | "(unknown)";
      Serial.printf("❌ Server error: %s\n", err);
      waitingForResponse = false;
      return;
    }
  });

  connectWiFi();
  connectWS();

  // Core 0: playback | Core 1: mic streaming
  xTaskCreatePinnedToCore(playbackTask,   "playback",   8192, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(micStreamTask,  "micStream",  4096, nullptr, 1, nullptr, 1);

  Serial.println("✅ System ready — speak anytime");
}

// ===== Loop =====
void loop() {
  // Reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  wsConnected = ws.available();

  // Reconnect WS every 3 s if not connected and not waiting
  if (!wsConnected && millis() - lastReconnectMs > 3000) {
    lastReconnectMs = millis();
    connectWS();
  }

  if (wsConnected) {
    if (xSemaphoreTake(wsMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
      ws.poll();
      xSemaphoreGive(wsMutex);
    }

    // Periodic ping
    if (needPong) {
      if (xSemaphoreTake(wsMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
        if (!ws.send("{\"type\":\"pong\"}")) wsConnected = false;
        xSemaphoreGive(wsMutex);
      }
      needPong = false;
    }

    // Periodic camera frame (always send, gateway will include in context)
    if (millis() - lastCameraSendMs > CAMERA_SEND_INTERVAL_MS) {
      lastCameraSendMs = millis();
      sendCameraFrame();
    }
  }

  // Clean up playback state once response is done and buffer drained
  if (responseDone && getPbBuffered() == 0 && !playbackStarted) {
    resetPlayback();
  }

  delay(5);
}

// ===== Hardware init helpers =====
bool initSpeaker() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SPK_SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 512,
    .use_apll             = false,
    .tx_desc_auto_clear   = true,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = SPK_BCK_PIN,
    .ws_io_num    = SPK_WS_PIN,
    .data_out_num = SPK_SD_PIN,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  if (i2s_driver_install(I2S_PORT_SPK, &cfg, 0, NULL) != ESP_OK) return false;
  if (i2s_set_pin(I2S_PORT_SPK, &pins) != ESP_OK) return false;
  i2s_zero_dma_buffer(I2S_PORT_SPK);
  return true;
}

bool initMic() {
  i2s_config_t cfg = {
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
  i2s_pin_config_t pins = {
    .bck_io_num   = MIC_BCK_PIN,
    .ws_io_num    = MIC_WS_PIN,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = MIC_SD_PIN
  };
  if (i2s_driver_install(I2S_PORT_MIC, &cfg, 0, NULL) != ESP_OK) return false;
  if (i2s_set_pin(I2S_PORT_MIC, &pins) != ESP_OK) return false;
  return true;
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0; config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;   config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;   config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_QVGA;          // smaller = faster for realtime
  config.jpeg_quality = 12;
  config.fb_count     = psramFound() ? 2 : 1;
  return esp_camera_init(&config) == ESP_OK;
}
