/*
 * ESP32-S3 Full Firmware — Smooth TTS v3.2
 *
 * BASE: Fixed v2 (Fix 1–4 fully kept) + v3 (Fix 5–10)
 *
 * FIXES 5-10: (from v3)
 *  FIX 5  — PLAYBACK_RING_BUFFER_BYTES  : 32KB → 1MB (1048576)
 *  FIX 6  — PLAYBACK_DECODE_SCRATCH_BYTES: 16KB → 512KB (524288)
 *  FIX 7  — playbackTask: Buffer-All mode (wait for playback_end)
 *  FIX 8  — Overflow safety: start if ring buffer ≥ 90%
 *  FIX 9  — Camera CAMERA_GRAB_LATEST + PSRAM placement
 *  FIX 10 — captureAndSendImage drains stale frame
 *
 * NEW IN v3.1 — TTS Audio Truncation Fixes:
 *  FIX 11 — playbackTask: I2S DMA drain grace period
 *           After ring buffer empties, continue feeding DMA for 300ms
 *           to ensure I2S hardware finishes outputting queued samples.
 *           Without this, the last 2-4 DMA buffers (up to 512 samples
 *           = 32ms per buffer × 8 buffers = 256ms) are silently lost.
 *
 *  FIX 12 — initSpeaker: tx_desc_auto_clear = false
 *           With true, the I2S driver auto-zeroes DMA descriptors the
 *           instant i2s_write() stops feeding data, cutting off trailing
 *           audio still queued in the DMA chain. Setting false lets the
 *           last buffer play to completion. We manually zero in
 *           resetPlaybackBuffer() when session ends.
 *
 *  FIX 13 — loop(): playback_complete waits for I2S drain flag
 *           Previously, loop() sent playback_complete as soon as
 *           playbackEndReceived && !playbackStarted && buffered==0.
 *           But playbackTask sets playbackStarted=false BEFORE the
 *           I2S DMA has finished draining. Now we use a new flag
 *           'i2sDrainComplete' that playbackTask sets AFTER the
 *           300ms grace period, so loop() only fires playback_complete
 *           when the speaker has truly finished.
 *
 *  FIX 15 — Debug hooks: chunk counter, I2S drain timing, buffer %
 *
 * NEW IN v3.2 — Microphone Audio Fixes (Delay, Noise, Chopping):
 *  FIX 16 — Remove PLAYBACK_SPEED time-stretch entirely.
 *           The 0.525× factor expanded 1600 samples into ~3047 samples,
 *           sending 1.9× more data than real-time at the same 16kHz rate.
 *           This created a permanent ~1s cumulative lag. MIC audio should
 *           be sent as raw PCM at native sample rate with no stretching.
 *
 *  FIX 17 — Remove i+=2 decimation in accumulation loop.
 *           The `i += 2` step skipped every other I2S sample, discarding
 *           50% of audio data. This caused aliasing artifacts (noise) and
 *           word chopping since half the speech signal was thrown away.
 *           Now processes every sample (i += 1).
 *
 *  FIX 18 — Correct SHIFT_BITS from 11 to 8 for INMP441 mic.
 *           INMP441 outputs 24-bit data MSB-aligned in a 32-bit I2S word.
 *           The correct shift to extract a 24-bit signed value is >>8.
 *           >>11 threw away the 3 lowest significant bits of real data
 *           AND left the value ~8× too small (2^(11-8) = 8), raising
 *           the noise floor relative to signal (worse SNR).
 *           After >>8, we take the upper 16 bits via >>8 again
 *           (total >>16) for int16_t output.
 *
 *  FIX 19 — Tune DC offset filter: alpha 0.99 → 0.995.
 *           alpha=0.99 creates a high-pass with ~160Hz cutoff at 16kHz,
 *           which eats into the fundamental frequency of adult speech
 *           (85-255Hz). alpha=0.995 gives ~50Hz cutoff — removes DC
 *           drift without cutting speech energy.
 *
 *  FIX 21 — MIC debug hooks: sample stats, send timing, level meter.
 *
 * PSRAM BUDGET: REDUCED — stretchBuffer no longer needed (~1543KB)
 *
 * KEPT FROM v2:
 *  FIX 1 — Core 分離: audioStreamTask → Core 0, playbackTask → Core 1
 *  FIX 2 — Post-speaker grace period (200ms), no speakerSessionActive gate on MIC
 *  FIX 3 — resetPlaybackBuffer() resets accumCount + speakerEndedMs
 *  FIX 4 — wsAudio.poll() mutex timeout 3ms
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
const char* WIFI_SSID      = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD  = "YOUR_WIFI_PW";
const char* WS_HOST        = "Your_Host_IP";
const uint16_t WS_PORT     = 8080;
const char* DEVICE_ID      = "default";
const char* WS_AUDIO_PATH  = "/ws_audio";
const char* WS_CTRL_PATH   = "/ws_ctrl";
const char* WS_CAMERA_PATH = "/ws_camera";

// ===== MIC =====
static const uint32_t AUDIO_SAMPLE_RATE = 16000;
static const size_t   AUDIO_SAMPLES     = 1600;  // 100ms frame at 16kHz
// [FIX 16] PLAYBACK_SPEED removed — no time-stretch, send raw PCM
// [FIX 17] No decimation — process every I2S sample
// [FIX 18] INMP441: 24-bit data MSB-aligned in 32-bit word → >>8 for 24-bit, then >>8 for 16-bit = >>16 total
#define SHIFT_BITS        16
#define DMA_READ_SAMPLES  1024
#define MIC_BCK_PIN       47
#define MIC_WS_PIN        20
#define MIC_SD_PIN        21
#define I2S_PORT_MIC      I2S_NUM_0

// ===== SPEAKER =====
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

// ===== [FIX 5] Playback Ring Buffer — 1MB = ~32s at 16kHz 16-bit =====
#define PLAYBACK_RING_BUFFER_BYTES     1048576   // [FIX 5] 1MB   (was 32KB)

// ===== [FIX 6] Decode Scratch — 512KB = handles very large base64 chunks =====
#define PLAYBACK_DECODE_SCRATCH_BYTES  524288    // [FIX 6] 512KB (was 16KB)

// I/O chunk for playbackTask DMA writes (larger = fewer i2s_write calls)
#define PLAYBACK_IO_CHUNK_BYTES        4096

// [FIX 8] Overflow safety: start playing early if buffer reaches this % full
#define PLAYBACK_OVERFLOW_THRESHOLD    0.90f

// [FIX 11] I2S DMA drain grace period — after ring buffer empties,
// keep the playback loop alive for this long to let I2S hardware
// finish outputting samples already queued in DMA descriptors.
// At 16kHz 16-bit mono with dma_buf_count=8 × dma_buf_len=512,
// the DMA pipeline holds 8×512×2 = 8192 bytes = 256ms of audio.
// 300ms provides a safe margin.
#define I2S_DRAIN_GRACE_MS             300

// ===== [FIX 2] Post-speaker grace period =====
#define MIC_RESUME_GRACE_MS           200
static volatile uint32_t speakerEndedMs = 0;

// ===== Mutex =====
static SemaphoreHandle_t wsAudioMutex = nullptr;
static portMUX_TYPE playbackMux = portMUX_INITIALIZER_UNLOCKED;

// ===== State =====
static volatile bool speakerSessionActive = false;
static volatile bool playbackStarted      = false;
static volatile bool playbackEndReceived  = false;
static volatile bool i2sDrainComplete     = false;  // [FIX 13] set by playbackTask after drain
static volatile uint32_t chunksReceived   = 0;       // [FIX 15] debug counter
static volatile uint32_t totalPcmReceived = 0;       // [FIX 15] debug counter
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
static int32_t* rawBuffer32           = nullptr;
static int16_t* accumBuffer           = nullptr;
// [FIX 16] stretchBuffer removed — no time-stretch needed
static uint8_t* playbackRingBuffer    = nullptr;
static uint8_t* playbackDecodeScratch = nullptr;

// [FIX 21] MIC debug counters
static volatile uint32_t micFramesSent      = 0;
static volatile uint32_t micFramesMuted     = 0;
static volatile uint32_t micTotalSamplesSent = 0;
static uint32_t          micLastStatMs       = 0;
static int      accumCount    = 0;   // [FIX 3]
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

// ===== Forward Declarations =====
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

// ============================================================
// [FIX 3] resetPlaybackBuffer — clears all state atomically
void resetPlaybackBuffer(bool clearReqId) {
  portENTER_CRITICAL(&playbackMux);
  playbackWritePos      = 0;
  playbackReadPos       = 0;
  playbackBufferedBytes = 0;
  playbackStarted       = false;
  playbackEndReceived   = false;
  speakerSessionActive  = false;
  i2sDrainComplete      = false;  // [FIX 13]
  portEXIT_CRITICAL(&playbackMux);

  chunksReceived   = 0;           // [FIX 15]
  totalPcmReceived = 0;           // [FIX 15]
  speakerEndedMs   = millis();    // [FIX 2] start grace period timer
  accumCount       = 0;           // [FIX 3] discard partial MIC accumulation

  i2s_zero_dma_buffer(I2S_PORT_SPK);
  if (clearReqId) playbackReqId = "";
}

// ============================================================
size_t getPlaybackBufferedBytes() {
  size_t b = 0;
  portENTER_CRITICAL(&playbackMux);
  b = playbackBufferedBytes;
  portEXIT_CRITICAL(&playbackMux);
  return b;
}

bool writePlaybackBytes(const uint8_t* data, size_t len) {
  if (!playbackRingBuffer || !data || len == 0 || len > PLAYBACK_RING_BUFFER_BYTES) return false;
  bool written = false;
  portENTER_CRITICAL(&playbackMux);
  const size_t writePos  = playbackWritePos;
  const size_t buffered  = playbackBufferedBytes;
  const size_t freeBytes = PLAYBACK_RING_BUFFER_BYTES - buffered;
  if (freeBytes >= len) {
    const size_t firstCopy = min(len, PLAYBACK_RING_BUFFER_BYTES - writePos);
    memcpy(playbackRingBuffer + writePos, data, firstCopy);
    if (len > firstCopy) memcpy(playbackRingBuffer, data + firstCopy, len - firstCopy);
    playbackWritePos      = (writePos + len) % PLAYBACK_RING_BUFFER_BYTES;
    playbackBufferedBytes = buffered + len;
    written = true;
  }
  portEXIT_CRITICAL(&playbackMux);
  return written;
}

size_t readPlaybackBytes(uint8_t* out, size_t maxLen) {
  if (!playbackRingBuffer || !out || maxLen == 0) return 0;
  size_t bytesRead = 0;
  portENTER_CRITICAL(&playbackMux);
  const size_t readPos  = playbackReadPos;
  const size_t buffered = playbackBufferedBytes;
  if (buffered > 0) {
    bytesRead = min(maxLen, buffered);
    const size_t firstCopy = min(bytesRead, PLAYBACK_RING_BUFFER_BYTES - readPos);
    memcpy(out, playbackRingBuffer + readPos, firstCopy);
    if (bytesRead > firstCopy) memcpy(out + firstCopy, playbackRingBuffer, bytesRead - firstCopy);
    playbackReadPos       = (readPos + bytesRead) % PLAYBACK_RING_BUFFER_BYTES;
    playbackBufferedBytes = buffered - bytesRead;
  }
  portEXIT_CRITICAL(&playbackMux);
  return bytesRead;
}

// ============================================================
void setup() {
  Serial.begin(9600);
  delay(500);
  Serial.println("\n=== ESP32-S3 Smooth TTS v3.2 ===");
  Serial.printf("Ring buffer : %u KB (%u s at 16kHz)\n",
                PLAYBACK_RING_BUFFER_BYTES / 1024,
                PLAYBACK_RING_BUFFER_BYTES / (16000 * 2));
  Serial.printf("Decode scratch: %u KB\n", PLAYBACK_DECODE_SCRATCH_BYTES / 1024);

  if (psramFound())
    Serial.printf("OK PSRAM: %u KB free\n", ESP.getFreePsram() / 1024);
  else {
    Serial.println("ERR PSRAM required! Halting.");
    while (true) delay(1000);
  }

  if (!SPIFFS.begin(true)) Serial.println("WARN SPIFFS mount failed");
  else Serial.printf("OK SPIFFS total=%u used=%u\n", SPIFFS.totalBytes(), SPIFFS.usedBytes());

  if (!initSpeaker()) Serial.println("ERR Speaker init failed");
  else                Serial.println("OK Speaker ready");

  if (!initPsramBuffers()) {
    Serial.println("ERR PSRAM alloc failed! Halting.");
    while (true) delay(1000);
  }
  Serial.printf("OK Buffers allocated (PSRAM used: ~%u KB)\n",
                (PLAYBACK_RING_BUFFER_BYTES + PLAYBACK_DECODE_SCRATCH_BYTES) / 1024 + 16);

  wsAudioMutex = xSemaphoreCreateMutex();

  // [FIX 1] Core 分離
  xTaskCreatePinnedToCore(playbackTask,    "playback",    8192, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(audioStreamTask, "audioStream", 4096, nullptr, 3, nullptr, 0);

  if (!initCamera()) Serial.println("WARN Camera init failed");
  else               Serial.println("OK Camera ready");

  if (!initMicrophone()) {
    Serial.println("ERR MIC init failed! Halting.");
    while (true) delay(1000);
  }
  Serial.println("OK Microphone ready");

  connectWiFi();
  initDebugWav();

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
    httpServer.send(200, "text/plain", "OK - recording 10s...");
  });
  httpServer.begin();
  Serial.printf("WAV: http://%s/debug_mic.wav\n", WiFi.localIP().toString().c_str());

  // ── Audio WebSocket callback ──────────────────────────────
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
        Serial.printf("[TTS] New session: %.8s...\n", reqId);
      }

      uint32_t sr = sanitizeSampleRate(doc["sample_rate"] | SPK_DEFAULT_SAMPLE_RATE);
      setSpeakerSampleRate(sr);

      const char* b64 = doc["audio_data"];
      if (!b64) return;
      size_t b64_len = strlen(b64);
      if (b64_len == 0) return;

      // [FIX 6] 512KB scratch handles very large chunks from backend
      size_t output_len = 0;
      size_t max_decoded = (b64_len * 3) / 4;
      if (max_decoded == 0 || max_decoded > PLAYBACK_DECODE_SCRATCH_BYTES || !playbackDecodeScratch) {
        Serial.printf("ERR chunk too large: %u bytes b64, %u bytes decoded (scratch=%u KB)\n",
                      b64_len, max_decoded, PLAYBACK_DECODE_SCRATCH_BYTES / 1024);
        return;
      }

      if (mbedtls_base64_decode(playbackDecodeScratch, PLAYBACK_DECODE_SCRATCH_BYTES,
                                &output_len, (const unsigned char*)b64, b64_len) == 0
          && output_len > 0) {

        // [FIX 15] Track received chunks and PCM bytes
        chunksReceived++;
        totalPcmReceived += output_len;

        if (!writePlaybackBytes(playbackDecodeScratch, output_len)) {
          // [FIX 8] Ring buffer full — force start to drain (1MB should rarely overflow)
          const size_t buffered = getPlaybackBufferedBytes();
          Serial.printf("WARN ring buffer full! %u KB buffered. Forcing playback start.\n",
                        buffered / 1024);
          speakerSessionActive = true;
          playbackStarted = true;
        } else {
          speakerSessionActive = true;
          playbackEndReceived  = false;

          // [FIX 15] Log buffered % every 10th chunk to reduce serial spam
          if (chunksReceived % 10 == 0 || chunksReceived == 1) {
            const size_t buffered = getPlaybackBufferedBytes();
            Serial.printf("[TTS] chunk#%u pcm=%uB buffered=%uKB/%uKB (%.0f%%)\n",
                          chunksReceived, output_len,
                          buffered / 1024,
                          PLAYBACK_RING_BUFFER_BYTES / 1024,
                          100.0f * buffered / PLAYBACK_RING_BUFFER_BYTES);
          }
        }
      }
      return;
    }

    if (strcmp(type, "playback_end") == 0) {
      playbackEndReceived = true;
      // [FIX 15] Log total received stats at end-of-stream
      Serial.printf("[TTS] playback_end received. chunks=%u total_pcm=%u bytes "
                    "buffered=%u KB → starting playback\n",
                    chunksReceived, totalPcmReceived,
                    getPlaybackBufferedBytes() / 1024);
    }
  });

  wsCtrl.onMessage([](WebsocketsMessage message) {
    if (message.isText()) handleCaptureCommand(message.data());
  });

  connectWebSockets();
  Serial.println("OK System ready");
}

// ============================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  httpServer.handleClient();

  audioConnected = wsAudio.available();
  ctrlConnected  = wsCtrl.available();

  if (!audioConnected && speakerSessionActive) resetPlaybackBuffer(true);

  if (millis() - lastReconnectAttempt > 3000) {
    if (!audioConnected || !ctrlConnected) connectWebSockets();
    lastReconnectAttempt = millis();
  }

  // [FIX 4] poll mutex timeout 3ms
  if (audioConnected) {
    if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(3)) == pdTRUE) {
      wsAudio.poll();
      xSemaphoreGive(wsAudioMutex);
    }
  }
  if (ctrlConnected) wsCtrl.poll();

  if (need_pong_audio && audioConnected) {
    if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
      bool ok = wsAudio.send("{\"type\":\"pong\"}");
      xSemaphoreGive(wsAudioMutex);
      if (ok) need_pong_audio = false;
      else { audioConnected = false; wsAudio.close(); }
    }
  }

  if (need_pong_ctrl && ctrlConnected) {
    if (wsCtrl.send("{\"type\":\"pong\"}")) need_pong_ctrl = false;
    else { ctrlConnected = false; wsCtrl.close(); }
  }

  // [FIX 13] Only send playback_complete AFTER playbackTask confirms I2S drain.
  // Old: checked playbackEndReceived && !playbackStarted && buffered==0
  //      → fired BEFORE I2S DMA finished outputting last samples.
  // New: wait for i2sDrainComplete flag set by playbackTask after 300ms grace.
  if (i2sDrainComplete) {
    if (playbackReqId != "" && audioConnected) {
      if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
        bool ok = wsAudio.send(
          "{\"type\":\"playback_complete\",\"request_id\":\"" + playbackReqId + "\"}");
        xSemaphoreGive(wsAudioMutex);
        if (ok) {
          Serial.printf("[SPK] playback_complete sent (chunks_rx=%u pcm_rx=%u)\n",
                        chunksReceived, totalPcmReceived);
          resetPlaybackBuffer(true);
        }
        else { audioConnected = false; wsAudio.close(); }
      }
    } else {
      resetPlaybackBuffer(true);
    }
  }

  delay(5);
}

// ============================================================
// [FIX 1] Core 0 — MIC dedicated task
void audioStreamTask(void* param) {
  for (;;) {
    if (audioConnected) streamAudio();
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

// ============================================================
// [FIX 7] playbackTask — Buffer-All Mode
// Waits for playback_end before starting output.
// This ensures all audio is in the ring buffer → zero stutter.
// [FIX 8] Overflow safety: starts early if buffer ≥ 90% full.
// [FIX 11] After ring buffer drains, wait I2S_DRAIN_GRACE_MS to let
//          the I2S DMA hardware finish playing queued samples.
// [FIX 13] Set i2sDrainComplete flag AFTER grace period so loop()
//          only sends playback_complete when speaker is truly done.
void playbackTask(void* param) {  // Core 1
  uint8_t ioChunk[PLAYBACK_IO_CHUNK_BYTES];
  uint32_t totalI2sWritten = 0;  // [FIX 15] debug: total bytes pushed to I2S

  while (true) {
    if (!speakerSessionActive) {
      vTaskDelay(pdMS_TO_TICKS(2));
      continue;
    }

    if (!playbackStarted) {
      const size_t buffered = getPlaybackBufferedBytes();

      // [FIX 7] Primary condition: all audio received
      const bool allReceived = playbackEndReceived && buffered > 0;

      // [FIX 8] Safety: start if ring buffer is 90% full (prevent overflow drop)
      const bool overflowRisk = buffered >= (size_t)(PLAYBACK_RING_BUFFER_BYTES * PLAYBACK_OVERFLOW_THRESHOLD);

      if (allReceived || overflowRisk) {
        playbackStarted  = true;
        i2sDrainComplete = false;  // [FIX 13] reset drain flag at start
        totalI2sWritten  = 0;     // [FIX 15]
        Serial.printf("[SPK] Playback START: %u KB buffered "
                      "(allReceived=%d overflow=%d chunks_rx=%u pcm_rx=%u)\n",
                      buffered / 1024, allReceived, overflowRisk,
                      chunksReceived, totalPcmReceived);
      } else {
        vTaskDelay(pdMS_TO_TICKS(2));
        continue;
      }
    }

    // ---- Main drain loop: read from ring buffer → I2S ----
    const size_t chunkLen = readPlaybackBytes(ioChunk, sizeof(ioChunk));
    if (chunkLen == 0) {
      if (playbackEndReceived) {
        // [FIX 11] Ring buffer is empty AND all chunks received.
        // But I2S DMA still has up to 8×512×2 = 8192 bytes queued.
        // Wait I2S_DRAIN_GRACE_MS to let hardware finish outputting.
        Serial.printf("[SPK] Ring buffer empty. I2S drain grace %dms "
                      "(total_i2s_written=%u)\n",
                      I2S_DRAIN_GRACE_MS, totalI2sWritten);

        vTaskDelay(pdMS_TO_TICKS(I2S_DRAIN_GRACE_MS));

        // [FIX 13] Now I2S hardware has finished. Signal to loop().
        playbackStarted  = false;
        i2sDrainComplete = true;
        Serial.println("[SPK] I2S drain complete. Playback DONE.");
      }
      vTaskDelay(pdMS_TO_TICKS(2));
      continue;
    }

    // Apply volume
    int16_t* samples    = (int16_t*)ioChunk;
    int      numSamples = chunkLen / 2;
    for (int i = 0; i < numSamples; i++) {
      int32_t v = (int32_t)(samples[i] * SPK_VOLUME);
      if (v >  32767) v =  32767;
      if (v < -32768) v = -32768;
      samples[i] = (int16_t)v;
    }

    size_t total_written = 0, bytes_written = 0;
    int retry = 0;
    while (total_written < chunkLen) {
      if (i2s_write(I2S_PORT_SPK, ioChunk + total_written,
                    chunkLen - total_written, &bytes_written,
                    pdMS_TO_TICKS(100)) == ESP_OK && bytes_written > 0) {
        total_written += bytes_written;
        retry = 0;
      } else {
        if (++retry > 5) {
          Serial.println("ERR speaker i2s_write failed");
          resetPlaybackBuffer(true);
          break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
      }
    }
    totalI2sWritten += total_written;  // [FIX 15]
  }
}

// ============================================================
bool initPsramBuffers() {
  rawBuffer32           = (int32_t*)ps_malloc(DMA_READ_SAMPLES  * sizeof(int32_t));
  accumBuffer           = (int16_t*)ps_malloc(AUDIO_SAMPLES     * sizeof(int16_t));
  // [FIX 16] stretchBuffer removed — no time-stretch
  playbackRingBuffer    = (uint8_t*)ps_malloc(PLAYBACK_RING_BUFFER_BYTES);
  playbackDecodeScratch = (uint8_t*)ps_malloc(PLAYBACK_DECODE_SCRATCH_BYTES);

  if (!rawBuffer32 || !accumBuffer ||
      !playbackRingBuffer || !playbackDecodeScratch) return false;

  memset(rawBuffer32,           0, DMA_READ_SAMPLES  * sizeof(int32_t));
  memset(accumBuffer,           0, AUDIO_SAMPLES     * sizeof(int16_t));
  memset(playbackRingBuffer,    0, PLAYBACK_RING_BUFFER_BYTES);
  memset(playbackDecodeScratch, 0, PLAYBACK_DECODE_SCRATCH_BYTES);
  return true;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nOK WiFi: " + WiFi.localIP().toString());
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_max_tx_power(68);
}

void connectWebSockets() {
  String base = String("ws://") + WS_HOST + ":" + String(WS_PORT);
  if (!audioConnected)
    audioConnected = wsAudio.connect(base + WS_AUDIO_PATH + "?device_id=" + DEVICE_ID);
  if (!ctrlConnected)
    ctrlConnected  = wsCtrl.connect(base + WS_CTRL_PATH  + "?device_id=" + DEVICE_ID);
}

// ============================================================
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
    .tx_desc_auto_clear   = false,   // [FIX 12] was true — auto-clear kills trailing DMA audio
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
  i2s_set_clk(I2S_PORT_SPK, SPK_DEFAULT_SAMPLE_RATE,
              I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
  i2s_zero_dma_buffer(I2S_PORT_SPK);
  currentSpkSampleRate = SPK_DEFAULT_SAMPLE_RATE;
  return true;
}

bool setSpeakerSampleRate(uint32_t sr) {
  if (sr == 0 || sr == currentSpkSampleRate) return true;
  if (i2s_set_clk(I2S_PORT_SPK, sr,
                  I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO) != ESP_OK) {
    Serial.printf("ERR SPK rate set failed: %u\n", sr);
    return false;
  }
  currentSpkSampleRate = sr;
  Serial.printf("SPK rate -> %u Hz\n", sr);
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

// ============================================================
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

// ============================================================
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
  config.grab_mode    = CAMERA_GRAB_LATEST;       // [FIX 9] always return newest frame
  config.fb_location  = CAMERA_FB_IN_PSRAM;        // [FIX 9] explicit PSRAM placement
  return esp_camera_init(&config) == ESP_OK;
}

// ============================================================
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

  // [FIX 10] Drain any stale frame sitting in the DMA buffer
  camera_fb_t* stale = esp_camera_fb_get();
  if (stale) {
    Serial.printf("[CAM] Drained stale frame (%u bytes)\n", stale->len);
    esp_camera_fb_return(stale);
  }

  // Now capture the fresh, current frame
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { wsCamera.close(); return; }

  String header = "{\"req_id\":\"" + reqId + "\",\"size\":"
                + String(fb->len) + ",\"format\":\"jpeg\"}";
  wsCamera.send(header); delay(50);
  wsCamera.sendBinary((const char*)fb->buf, fb->len);

  esp_camera_fb_return(fb);
  wsCamera.close();  // [FIX 10] removed delay(100) — no benefit
}

// ============================================================
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
  Serial.println("Recording debug WAV (10s)...");
}

void appendToWav(const int16_t* samples, int count) {
  if (!wavRecording || wavSaved || !wavFile) return;
  int n = min(count, (int)(WAV_TOTAL_SAMPLES - wavSamplesWritten));
  wavFile.write((const uint8_t*)samples, n * 2);
  wavSamplesWritten += n;
  if (wavSamplesWritten >= WAV_TOTAL_SAMPLES) {
    wavFile.close();
    wavRecording = false; wavSaved = true;
    Serial.printf("WAV saved -> http://%s/debug_mic.wav\n",
                  WiFi.localIP().toString().c_str());
  }
}

// ============================================================
// streamAudio() — runs on Core 0 via audioStreamTask
//
// [FIX 2]  DMA must drain at ALL times (even during speaker playback).
//          shouldSend gate: suppress sending during speaker + grace.
// [FIX 3]  accumCount = 0 always (outside shouldSend branch).
// [FIX 16] Time-stretch REMOVED — send raw 1600-sample frames (100ms)
//          at native 16kHz. No more 0.525× expansion that doubled
//          the data rate and caused cumulative 1-2s lag.
// [FIX 17] Decimation REMOVED — process every I2S sample (i += 1).
//          The old i += 2 threw away 50% of audio, causing aliasing
//          noise and dropped speech segments.
// [FIX 18] SHIFT_BITS corrected to 16 (was 11).
//          INMP441: 24-bit data left-aligned in 32-bit word → >>16
//          extracts the top 16 bits as int16_t directly.
// [FIX 19] DC offset alpha: 0.99 → 0.995 (~50Hz cutoff vs old ~160Hz).
//          Preserves low-frequency speech energy.
// [FIX 21] Debug: periodic sample stats and level meter.
void streamAudio() {
  const float alpha        = 0.995f;   // [FIX 19] was 0.99
  const int   FADE_SAMPLES = 32;

  size_t bytesRead = 0;
  if (i2s_read(I2S_PORT_MIC, rawBuffer32, DMA_READ_SAMPLES * sizeof(int32_t),
               &bytesRead, pdMS_TO_TICKS(10)) != ESP_OK) return;
  if (bytesRead == 0) return;

  int samplesRead = bytesRead / 4;

  // [FIX 17] Process every sample — no decimation
  for (int i = 0; i < samplesRead && accumCount < (int)AUDIO_SAMPLES; i++) {
    // [FIX 18] >>16 gives upper 16 bits of INMP441's 24-bit-in-32-bit word
    int16_t shifted = (int16_t)(rawBuffer32[i] >> SHIFT_BITS);
    // [FIX 19] DC offset removal with gentler filter
    dc_offset = (alpha * dc_offset) + ((1.0f - alpha) * (float)shifted);
    int32_t clean = (int32_t)shifted - (int32_t)dc_offset;
    if (clean >  32767) clean =  32767;
    if (clean < -32768) clean = -32768;
    accumBuffer[accumCount++] = (int16_t)clean;
  }

  if (accumCount >= (int)AUDIO_SAMPLES) {
    // [FIX 16] No time-stretch — send accumBuffer directly as 1600 samples (100ms)

    // Fade in/out to remove click at frame boundaries
    for (int i = 0; i < FADE_SAMPLES; i++) {
      accumBuffer[i] =
        (int16_t)(accumBuffer[i] * ((float)i / FADE_SAMPLES));
      accumBuffer[AUDIO_SAMPLES - FADE_SAMPLES + i] =
        (int16_t)(accumBuffer[AUDIO_SAMPLES - FADE_SAMPLES + i]
                  * ((float)(FADE_SAMPLES - i) / FADE_SAMPLES));
    }

    // [FIX 2] Gate: mute MIC during speaker + grace period
    bool shouldSend = true;
    if (speakerSessionActive) {
      shouldSend = false;
    } else if (speakerEndedMs > 0 &&
               (millis() - speakerEndedMs) < MIC_RESUME_GRACE_MS) {
      shouldSend = false;
    }

    if (shouldSend) {
      // [FIX 16] Send raw accumBuffer (1600 samples × 2 bytes = 3200 bytes)
      appendToWav(accumBuffer, AUDIO_SAMPLES);
      if (xSemaphoreTake(wsAudioMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        bool ok = wsAudio.sendBinary((const char*)accumBuffer, AUDIO_SAMPLES * 2);
        xSemaphoreGive(wsAudioMutex);
        if (!ok) { audioConnected = false; wsAudio.close(); }
      }
      micFramesSent++;
      micTotalSamplesSent += AUDIO_SAMPLES;
    } else {
      micFramesMuted++;
    }

    // [FIX 21] Periodic MIC stats every 5 seconds
    if (millis() - micLastStatMs >= 5000) {
      // Compute peak amplitude of this frame for level meter
      int16_t peakAbs = 0;
      for (int i = 0; i < (int)AUDIO_SAMPLES; i++) {
        int16_t a = accumBuffer[i] < 0 ? -accumBuffer[i] : accumBuffer[i];
        if (a > peakAbs) peakAbs = a;
      }
      float peakDb = (peakAbs > 0) ? 20.0f * log10f((float)peakAbs / 32768.0f) : -96.0f;
      Serial.printf("[MIC] frames_sent=%u muted=%u total_samples=%u "
                    "peak=%d (%.1f dBFS) dc_offset=%.1f\n",
                    micFramesSent, micFramesMuted, micTotalSamplesSent,
                    peakAbs, peakDb, dc_offset);
      micLastStatMs = millis();
    }

    // [FIX 3] Always reset — DMA drain must continue regardless
    accumCount = 0;
  }
}
