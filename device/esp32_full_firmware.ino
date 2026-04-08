/*
 * ESP32-S3-WROOM Full Firmware — Smooth TTS v3
 *
 * BASE: Working full firmware with websocket mutex + dual-core split
 *
 * NEW FIXES IN THIS BUILD:
 *  FIX 5 — PLAYBACK_RING_BUFFER_BYTES      : 32KB  → 1MB
 *  FIX 6 — PLAYBACK_DECODE_SCRATCH_BYTES   : 16KB  → 512KB
 *  FIX 7 — playbackTask uses buffer-all mode (wait playback_end before start)
 *  FIX 8 — Overflow fallback: start playback immediately at 90% ring usage
 *
 * BOARD TARGET:
 *  ESP32-S3-WROOM
 *  Speaker pins: BCK=46, WS=3, SD=14
 */

#include <WiFi.h>
#include <esp_wifi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "driver/i2s.h"
#include "freertos/semphr.h"
#include "mbedtls/base64.h"
#include <SPIFFS.h>
#include <WebServer.h>

using namespace websockets;

// ===== WiFi / Server =====
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PW";
const char* WS_HOST       = "Your_Host_IP";
const uint16_t WS_PORT    = 8080;
const char* DEVICE_ID     = "default";
const char* WS_AUDIO_PATH  = "/ws_audio";
const char* WS_CTRL_PATH   = "/ws_ctrl";
const char* WS_CAMERA_PATH = "/ws_camera";

// ===== MIC — PROVEN SETTINGS, DO NOT CHANGE =====
static const uint32_t AUDIO_SAMPLE_RATE = 16000;
static const size_t   AUDIO_SAMPLES     = 1600;
#define PLAYBACK_SPEED    0.525f
#define STRETCHED_SAMPLES ((int)(AUDIO_SAMPLES / PLAYBACK_SPEED))
#define SHIFT_BITS        11
#define DMA_READ_SAMPLES  1024
#define MIC_BCK_PIN       47
#define MIC_WS_PIN        20
#define MIC_SD_PIN        21
#define I2S_PORT_MIC      I2S_NUM_0

// ===== SPEAKER — CORRECT PINS FROM WORKING VERSION =====
#define SPK_BCK_PIN              46
#define SPK_WS_PIN               3
#define SPK_SD_PIN               14
#define I2S_PORT_SPK             I2S_NUM_1
#define SPK_SAMPLE_RATE          16000
#define SPK_DEFAULT_SAMPLE_RATE  SPK_SAMPLE_RATE
#define SPK_VOLUME               0.1f

// ===== Camera Pins =====
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

// ===== Playback Ring Buffer =====
#define PLAYBACK_RING_BUFFER_BYTES     1048576
#define PLAYBACK_START_THRESHOLD_BYTES 8192
#define PLAYBACK_IO_CHUNK_BYTES        1024
#define PLAYBACK_DECODE_SCRATCH_BYTES  524288
#define PLAYBACK_OVERFLOW_THRESHOLD_BYTES ((PLAYBACK_RING_BUFFER_BYTES * 9) / 10)

// ===== Mutex for wsAudio thread safety =====
static SemaphoreHandle_t wsAudioMutex = nullptr;
static portMUX_TYPE playbackMux = portMUX_INITIALIZER_UNLOCKED;

// ===== State =====
static volatile bool speakerSessionActive = false;
static volatile bool playbackStarted      = false;
static volatile bool playbackEndReceived  = false;
String playbackReqId = "";
String captureReqId  = "";
static uint32_t currentSpkSampleRate = SPK_DEFAULT_SAMPLE_RATE;

WebsocketsClient wsAudio;
WebsocketsClient wsCtrl;
WebsocketsClient wsCamera;
bool audioConnected = false;
bool ctrlConnected  = false;
unsigned long lastReconnectAttempt = 0;
volatile bool need_pong_audio = false;
volatile bool need_pong_ctrl  = false;

// ===== MIC buffers (PSRAM) =====
static int32_t* rawBuffer32   = nullptr;
static int16_t* accumBuffer   = nullptr;
static int16_t* stretchBuffer = nullptr;
static uint8_t* playbackRingBuffer = nullptr;
static uint8_t* playbackDecodeScratch = nullptr;
static int      accumCount    = 0;
static float    dc_offset     = 0.0f;
static volatile size_t playbackWritePos      = 0;
static volatile size_t playbackReadPos       = 0;
static volatile size_t playbackBufferedBytes = 0;

// ===== Debug WAV =====
WebServer httpServer(80);
#define WAV_RECORD_SECONDS 10
#define WAV_TOTAL_SAMPLES  (16000 * WAV_RECORD_SECONDS)
static const char* WAV_PATH = "/debug_mic.wav";
File     wavFile;
bool     wavRecording      = false;
bool     wavSaved          = false;
uint32_t wavSamplesWritten = 0;

// ===== Declarations =====
void connectWiFi();
void connectWebSockets();
bool initMicrophone();
bool initSpeaker();
bool initCamera();
bool initPsramBuffers();
void streamAudio();
void handleCaptureCommand(const String& msg);
void captureAndSendImage(const String& reqId);
void playbackTask(void* param);
void audioStreamTask(void* param);
void initDebugWav();
void writeWavHeader(File& f, uint32_t sr, uint32_t totalSamples);
void appendToWav(const int16_t* samples, int count);
bool setSpeakerSampleRate(uint32_t sr);
uint32_t sanitizeSampleRate(uint32_t sr);
void resetPlaybackBuffer(bool clearReqId);
size_t getPlaybackBufferedBytes();
bool writePlaybackBytes(const uint8_t* data, size_t len);
size_t readPlaybackBytes(uint8_t* out, size_t maxLen);

void resetPlaybackBuffer(bool clearReqId) {
  portENTER_CRITICAL(&playbackMux);
  playbackWritePos = 0;
  playbackReadPos = 0;
  playbackBufferedBytes = 0;
  playbackStarted = false;
  playbackEndReceived = false;
  speakerSessionActive = false;
  accumCount = 0;
  portEXIT_CRITICAL(&playbackMux);

  i2s_zero_dma_buffer(I2S_PORT_SPK);

  if (clearReqId) {
    playbackReqId = "";
  }
}

size_t getPlaybackBufferedBytes() {
  size_t buffered = 0;
  portENTER_CRITICAL(&playbackMux);
  buffered = playbackBufferedBytes;
  portEXIT_CRITICAL(&playbackMux);
  return buffered;
}

bool writePlaybackBytes(const uint8_t* data, size_t len) {
  if (!playbackRingBuffer || !data || len == 0 || len > PLAYBACK_RING_BUFFER_BYTES) {
    return false;
  }

  bool written = false;
  portENTER_CRITICAL(&playbackMux);
  const size_t writePos = playbackWritePos;
  const size_t buffered = playbackBufferedBytes;
  const size_t freeBytes = PLAYBACK_RING_BUFFER_BYTES - buffered;
  if (freeBytes >= len) {
    const size_t firstCopy = min(len, PLAYBACK_RING_BUFFER_BYTES - writePos);
    memcpy(playbackRingBuffer + writePos, data, firstCopy);
    if (len > firstCopy) {
      memcpy(playbackRingBuffer, data + firstCopy, len - firstCopy);
    }
    playbackWritePos = (writePos + len) % PLAYBACK_RING_BUFFER_BYTES;
    playbackBufferedBytes = buffered + len;
    written = true;
  }
  portEXIT_CRITICAL(&playbackMux);
  return written;
}

size_t readPlaybackBytes(uint8_t* out, size_t maxLen) {
  if (!playbackRingBuffer || !out || maxLen == 0) {
    return 0;
  }

  size_t bytesRead = 0;
  portENTER_CRITICAL(&playbackMux);
  const size_t readPos = playbackReadPos;
  const size_t buffered = playbackBufferedBytes;
  if (buffered > 0) {
    bytesRead = min(maxLen, buffered);
    const size_t firstCopy = min(bytesRead, PLAYBACK_RING_BUFFER_BYTES - readPos);
    memcpy(out, playbackRingBuffer + readPos, firstCopy);
    if (bytesRead > firstCopy) {
      memcpy(out + firstCopy, playbackRingBuffer, bytesRead - firstCopy);
    }
    playbackReadPos = (readPos + bytesRead) % PLAYBACK_RING_BUFFER_BYTES;
    playbackBufferedBytes = buffered - bytesRead;
  }
  portEXIT_CRITICAL(&playbackMux);
  return bytesRead;
}

// ========================================================
void setup() {
  Serial.begin(9600);
  delay(500);
  Serial.println("\n=== ESP32-S3 Firmware (Working Base + Overheat + Mutex) ===");
  Serial.printf("MIC: ONLY_LEFT + i+=2 + PLAYBACK_SPEED=%.3f  STRETCHED=%d\n",
                PLAYBACK_SPEED, STRETCHED_SAMPLES);

  if (psramFound()) Serial.printf("✅ PSRAM: %u KB\n", ESP.getFreePsram() / 1024);
  else              Serial.println("⚠️ PSRAM NOT detected!");

  if (!SPIFFS.begin(true)) Serial.println("❌ SPIFFS mount failed");
  else Serial.printf("✅ SPIFFS OK  total=%u used=%u\n", SPIFFS.totalBytes(), SPIFFS.usedBytes());

  if (!initSpeaker())    Serial.println("❌ Speaker init failed");
  else                   Serial.println("✅ Speaker ready");

  if (!initPsramBuffers()) {
    Serial.println("❌ PSRAM alloc failed! Halting.");
    while (true) delay(1000);
  }

  // ✅ Mutex before tasks
  wsAudioMutex = xSemaphoreCreateMutex();

  // playbackTask → Core 0 | audioStreamTask → Core 1
  xTaskCreatePinnedToCore(playbackTask,    "playback",    8192, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(audioStreamTask, "audioStream", 4096, nullptr, 1, nullptr, 1);

  if (!initCamera())     Serial.println("❌ Camera init failed");
  else                   Serial.println("✅ Camera ready");

  if (!initMicrophone()) {
    Serial.println("❌ MIC init failed! Halting.");
    while (true) delay(1000);
  }
  Serial.println("✅ Microphone ready");

  connectWiFi();
  initDebugWav();

  // ── HTTP debug WAV ──
  httpServer.on("/debug_mic.wav", HTTP_GET, []() {
    if (!SPIFFS.exists(WAV_PATH)) {
      httpServer.send(404, "text/plain",
        wavRecording ? "Recording in progress..." : "Not recorded yet.");
      return;
    }
    File f = SPIFFS.open(WAV_PATH, FILE_READ);
    if (!f) { httpServer.send(500, "text/plain", "File open failed"); return; }
    httpServer.streamFile(f, "audio/wav");
    f.close();
  });
  httpServer.on("/wav_reset", HTTP_GET, []() {
    if (wavRecording) { httpServer.send(400, "text/plain", "Recording in progress"); return; }
    initDebugWav();
    httpServer.send(200, "text/plain", "OK — recording 10s...");
  });
  httpServer.begin();
  Serial.printf("🌐 WAV: http://%s/debug_mic.wav\n", WiFi.localIP().toString().c_str());

  // ── WS callbacks ──
  wsAudio.onMessage([](WebsocketsMessage message) {
    if (!message.isText()) return;

    StaticJsonDocument<256> filter;
    filter["type"] = true; filter["request_id"] = true;
    filter["audio_data"] = true; filter["sample_rate"] = true;

    DynamicJsonDocument doc(4096);
    if (deserializeJson(doc, message.data(), DeserializationOption::Filter(filter))) return;

    const char* type = doc["type"];
    if (!type) return;

    if (strcmp(type, "ping") == 0) { need_pong_audio = true; return; }

    if (strcmp(type, "audio_chunk") == 0) {
      const char* reqId = doc["request_id"];
      if (!reqId || reqId[0] == '\0') return;
      if (playbackReqId != reqId) {
        resetPlaybackBuffer(false);
        playbackReqId = String(reqId);
      }

      uint32_t sr = sanitizeSampleRate(doc["sample_rate"] | SPK_DEFAULT_SAMPLE_RATE);
      setSpeakerSampleRate(sr);

      const char* b64 = doc["audio_data"];
      if (!b64) return;
      size_t b64_len = strlen(b64);
      if (b64_len == 0) return;

      size_t output_len = 0;
      size_t max_len = (b64_len * 3) / 4;
      if (max_len == 0 || max_len > PLAYBACK_DECODE_SCRATCH_BYTES || !playbackDecodeScratch) {
        Serial.println("audio chunk too large for decode scratch");
        return;
      }

      if (mbedtls_base64_decode(playbackDecodeScratch, PLAYBACK_DECODE_SCRATCH_BYTES, &output_len,
                                (const unsigned char*)b64, b64_len) == 0
          && output_len > 0) {
        if (!writePlaybackBytes(playbackDecodeScratch, output_len)) {
          Serial.println("playback ring buffer full");
          return;
        }
        speakerSessionActive = true;
        playbackEndReceived = false;
      }
      return;
    }

    if (strcmp(type, "playback_end") == 0) { playbackEndReceived = true; }
  });

  wsCtrl.onMessage([](WebsocketsMessage message) {
    if (message.isText()) handleCaptureCommand(message.data());
  });

  connectWebSockets();
  Serial.println("✅ System ready");
}

// ========================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  httpServer.handleClient();

  audioConnected = wsAudio.available();
  ctrlConnected  = wsCtrl.available();

  if (!audioConnected && speakerSessionActive) {
    resetPlaybackBuffer(true);
  }

  if (millis() - lastReconnectAttempt > 3000) {
    if (!audioConnected || !ctrlConnected) connectWebSockets();
    lastReconnectAttempt = millis();
  }

  // ✅ poll protected by mutex
  if (audioConnected) {
    if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
      wsAudio.poll();
      xSemaphoreGive(wsAudioMutex);
    }
  }
  if (ctrlConnected) wsCtrl.poll();

  // ✅ pong protected by mutex
  if (need_pong_audio && audioConnected) {
    if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
      bool ok = wsAudio.send("{\"type\":\"pong\"}");
      xSemaphoreGive(wsAudioMutex);
      if (ok) need_pong_audio = false;
      else {
        audioConnected = false;
        wsAudio.close();
      }
    }
  }
  if (need_pong_ctrl && ctrlConnected) {
    if (wsCtrl.send("{\"type\":\"pong\"}")) need_pong_ctrl = false;
    else {
      ctrlConnected = false;
      wsCtrl.close();
    }
  }

  // ✅ playback_complete protected by mutex
  if (playbackEndReceived && !playbackStarted && getPlaybackBufferedBytes() == 0) {
    if (playbackReqId != "" && audioConnected) {
      if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
        bool ok = wsAudio.send("{\"type\":\"playback_complete\",\"request_id\":\"" + playbackReqId + "\"}");
        xSemaphoreGive(wsAudioMutex);
        if (ok) {
          resetPlaybackBuffer(true);
        } else {
          audioConnected = false;
          wsAudio.close();
        }
      }
    } else {
      resetPlaybackBuffer(true);
    }
  }

  delay(5);
}

// ========================================================
void audioStreamTask(void* param) {
  for (;;) {
    if (audioConnected && !speakerSessionActive) {
      streamAudio();
    }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

// ========================================================
void playbackTask(void* param) {
  uint8_t ioChunk[PLAYBACK_IO_CHUNK_BYTES];
  while (true) {
    if (!speakerSessionActive) {
      vTaskDelay(pdMS_TO_TICKS(2));
      continue;
    }

    const size_t buffered = getPlaybackBufferedBytes();
    if (!playbackStarted) {
      const bool bufferAllReady = playbackEndReceived && buffered > 0;
      const bool overflowFallback = buffered >= PLAYBACK_OVERFLOW_THRESHOLD_BYTES;
      if (bufferAllReady || overflowFallback) {
        playbackStarted = true;
      } else {
        vTaskDelay(pdMS_TO_TICKS(2));
        continue;
      }
    }

    const size_t chunkLen = readPlaybackBytes(ioChunk, sizeof(ioChunk));
    if (chunkLen == 0) {
      if (playbackEndReceived) playbackStarted = false;
      vTaskDelay(pdMS_TO_TICKS(2));
      continue;
    }

    int16_t* samples = (int16_t*)ioChunk;
    int numSamples = chunkLen / 2;

    for (int i = 0; i < numSamples; i++) {
      int32_t v = (int32_t)(samples[i] * SPK_VOLUME);
      if (v >  32767) v =  32767;
      if (v < -32768) v = -32768;
      samples[i] = (int16_t)v;
    }

    size_t total_written = 0, bytes_written = 0;
    int retry = 0;
    while (total_written < chunkLen) {
      if (i2s_write(I2S_PORT_SPK,
                    ioChunk + total_written,
                    chunkLen - total_written,
                    &bytes_written, pdMS_TO_TICKS(100)) == ESP_OK
          && bytes_written > 0) {
        total_written += bytes_written;
        retry = 0;
      } else {
        if (++retry > 5) {
          Serial.println("speaker i2s_write failed");
          resetPlaybackBuffer(true);
          break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
      }
    }
  }
}

// ========================================================
bool initPsramBuffers() {
  rawBuffer32   = (int32_t*)ps_malloc(DMA_READ_SAMPLES  * sizeof(int32_t));
  accumBuffer   = (int16_t*)ps_malloc(AUDIO_SAMPLES     * sizeof(int16_t));
  stretchBuffer = (int16_t*)ps_malloc(STRETCHED_SAMPLES * sizeof(int16_t));
  playbackRingBuffer = (uint8_t*)ps_malloc(PLAYBACK_RING_BUFFER_BYTES);
  playbackDecodeScratch = (uint8_t*)ps_malloc(PLAYBACK_DECODE_SCRATCH_BYTES);
  if (!rawBuffer32 || !accumBuffer || !stretchBuffer ||
      !playbackRingBuffer || !playbackDecodeScratch) return false;
  memset(rawBuffer32,   0, DMA_READ_SAMPLES  * sizeof(int32_t));
  memset(accumBuffer,   0, AUDIO_SAMPLES     * sizeof(int16_t));
  memset(stretchBuffer, 0, STRETCHED_SAMPLES * sizeof(int16_t));
  memset(playbackRingBuffer, 0, PLAYBACK_RING_BUFFER_BYTES);
  memset(playbackDecodeScratch, 0, PLAYBACK_DECODE_SCRATCH_BYTES);
  return true;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\n✅ WiFi: " + WiFi.localIP().toString());
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_max_tx_power(68); // 17dBm — reduces heat
}

void connectWebSockets() {
  String base = String("ws://") + WS_HOST + ":" + String(WS_PORT);
  if (!audioConnected)
    audioConnected = wsAudio.connect(base + WS_AUDIO_PATH + "?device_id=" + DEVICE_ID);
  if (!ctrlConnected)
    ctrlConnected  = wsCtrl.connect(base + WS_CTRL_PATH  + "?device_id=" + DEVICE_ID);
}

// ========================================================
bool initSpeaker() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SPK_DEFAULT_SAMPLE_RATE,
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
  i2s_set_clk(I2S_PORT_SPK, SPK_DEFAULT_SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
  i2s_zero_dma_buffer(I2S_PORT_SPK);
  currentSpkSampleRate = SPK_DEFAULT_SAMPLE_RATE;
  return true;
}

bool setSpeakerSampleRate(uint32_t sr) {
  if (sr == 0 || sr == currentSpkSampleRate) return true;
  if (i2s_set_clk(I2S_PORT_SPK, sr, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO) != ESP_OK) {
    Serial.printf("❌ SPK rate set failed: %u\n", sr); return false;
  }
  currentSpkSampleRate = sr;
  Serial.printf("🔊 SPK rate → %u Hz\n", sr);
  return true;
}

uint32_t sanitizeSampleRate(uint32_t sr) {
  switch (sr) {
    case 8000: case 11025: case 12000: case 16000:
    case 22050: case 24000: case 32000: case 44100: case 48000:
      return sr;
    default: return SPK_DEFAULT_SAMPLE_RATE;
  }
}

// ========================================================
bool initMicrophone() {
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

// ========================================================
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
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = psramFound() ? 10 : 12;
  config.fb_count     = psramFound() ?  2 :  1;
  return esp_camera_init(&config) == ESP_OK;
}

// ========================================================
void handleCaptureCommand(const String& msg) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, msg)) return;
  const char* type = doc["type"];
  if (!type || strcmp(type, "CAPTURE") != 0) {
    if (type && strcmp(type, "ping") == 0) need_pong_ctrl = true;
    return;
  }
  const char* idPtr = doc["req_id"];
  captureReqId = idPtr ? String(idPtr) : "unknown";
  captureAndSendImage(captureReqId);
}

void captureAndSendImage(const String& reqId) {
  String url = String("ws://") + WS_HOST + ":" + String(WS_PORT)
             + WS_CAMERA_PATH + "?device_id=" + DEVICE_ID;
  if (!wsCamera.connect(url)) return;
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { wsCamera.close(); return; }
  String header = "{\"req_id\":\"" + reqId + "\",\"size\":"
                + String(fb->len) + ",\"format\":\"jpeg\"}";
  wsCamera.send(header); delay(50);
  wsCamera.sendBinary((const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb); delay(100); wsCamera.close();
}

// ========================================================
void writeWavHeader(File& f, uint32_t sr, uint32_t totalSamples) {
  uint32_t dataSize = totalSamples * 2, fileSize = dataSize + 36;
  uint16_t audioFmt = 1, channels = 1, blockAlign = 2, bitsPS = 16;
  uint32_t byteRate = sr * 2, fmtSize = 16;
  f.write((uint8_t*)"RIFF", 4); f.write((uint8_t*)&fileSize,  4);
  f.write((uint8_t*)"WAVE", 4); f.write((uint8_t*)"fmt ",     4);
  f.write((uint8_t*)&fmtSize,   4); f.write((uint8_t*)&audioFmt,  2);
  f.write((uint8_t*)&channels,  2); f.write((uint8_t*)&sr,         4);
  f.write((uint8_t*)&byteRate,  4); f.write((uint8_t*)&blockAlign, 2);
  f.write((uint8_t*)&bitsPS,    2); f.write((uint8_t*)"data",      4);
  f.write((uint8_t*)&dataSize,  4);
}

void initDebugWav() {
  if (!SPIFFS.totalBytes()) return;
  SPIFFS.remove(WAV_PATH);
  wavFile = SPIFFS.open(WAV_PATH, FILE_WRITE);
  if (!wavFile) return;
  writeWavHeader(wavFile, 16000, WAV_TOTAL_SAMPLES);
  wavRecording = true; wavSaved = false; wavSamplesWritten = 0;
  Serial.println("🎤 Recording debug WAV (10s)...");
}

void appendToWav(const int16_t* samples, int count) {
  if (!wavRecording || wavSaved || !wavFile) return;
  int n = min(count, (int)(WAV_TOTAL_SAMPLES - wavSamplesWritten));
  wavFile.write((const uint8_t*)samples, n * 2);
  wavSamplesWritten += n;
  if (wavSamplesWritten >= WAV_TOTAL_SAMPLES) {
    wavFile.close();
    wavRecording = false; wavSaved = true;
    Serial.println("✅ WAV saved!");
    Serial.printf("🌐 http://%s/debug_mic.wav\n", WiFi.localIP().toString().c_str());
  }
}

// ========================================================
void streamAudio() {
  const float alpha = 0.99f;
  const int FADE_SAMPLES = 32;

  size_t bytesRead = 0;
  if (i2s_read(I2S_PORT_MIC, rawBuffer32, DMA_READ_SAMPLES * sizeof(int32_t),
               &bytesRead, pdMS_TO_TICKS(10)) != ESP_OK) return;
  if (bytesRead == 0) return;

  int samplesRead = bytesRead / 4;

  for (int i = 0; i < samplesRead && accumCount < (int)AUDIO_SAMPLES; i += 2) {
    int32_t shifted = rawBuffer32[i] >> SHIFT_BITS;
    dc_offset = (alpha * dc_offset) + ((1.0f - alpha) * (float)shifted);
    int32_t clean = shifted - (int32_t)dc_offset;
    if (clean >  32767) clean =  32767;
    if (clean < -32768) clean = -32768;
    accumBuffer[accumCount++] = (int16_t)clean;
  }

  if (accumCount >= (int)AUDIO_SAMPLES) {
    for (int i = 0; i < STRETCHED_SAMPLES; i++) {
      float srcPos = i * (AUDIO_SAMPLES - 1.0f) / (STRETCHED_SAMPLES - 1.0f);
      int   srcIdx = (int)srcPos;
      float frac   = srcPos - srcIdx;
      stretchBuffer[i] = (srcIdx >= (int)AUDIO_SAMPLES - 1)
        ? accumBuffer[AUDIO_SAMPLES - 1]
        : (int16_t)(accumBuffer[srcIdx] * (1.0f - frac) + accumBuffer[srcIdx + 1] * frac);
    }
    for (int i = 0; i < FADE_SAMPLES; i++) {
      stretchBuffer[i] =
        (int16_t)(stretchBuffer[i] * ((float)i / FADE_SAMPLES));
      stretchBuffer[STRETCHED_SAMPLES - FADE_SAMPLES + i] =
        (int16_t)(stretchBuffer[STRETCHED_SAMPLES - FADE_SAMPLES + i]
                  * ((float)(FADE_SAMPLES - i) / FADE_SAMPLES));
    }

    appendToWav(stretchBuffer, STRETCHED_SAMPLES);

    // ✅ sendBinary protected by mutex
    if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
      bool ok = wsAudio.sendBinary((const char*)stretchBuffer, STRETCHED_SAMPLES * 2);
      xSemaphoreGive(wsAudioMutex);
      if (!ok) {
        audioConnected = false;
        wsAudio.close();
      }
    }

    accumCount = 0;
  }
}
