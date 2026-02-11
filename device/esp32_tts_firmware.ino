/*
 * ESP32 Real-Time AI Assistant with TTS - Complete Firmware
 * 
 * Features:
 * - I2S microphone audio streaming (input)
 * - I2S speaker audio playback (output) - NEW
 * - ESP32-CAM image capture
 * - WebSocket communication
 * - Audio buffer management - NEW
 * - Auto-reconnection
 * 
 * Hardware: ESP32-CAM with I2S microphone and I2S DAC/speaker
 * 
 * Libraries required:
 * - ArduinoWebsockets
 * - ESP32 Camera (built-in)
 * - ArduinoJson
 */

#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "driver/i2s.h"
#include "base64.h"

// ===== Configuration =====
// WiFi credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Server configuration (AWS EC2)
const char* serverHost = "your-ec2-public-ip";  // e.g., "54.123.45.67"
const int serverPort = 8000;

// WebSocket paths
const char* wsAudioPath = "/ws_audio";
const char* wsCtrlPath = "/ws_ctrl";
const char* wsCameraPath = "/ws_camera";

// Audio INPUT configuration (microphone)
#define SAMPLE_RATE 16000
#define I2S_PORT_IN I2S_NUM_0
#define I2S_WS_IN 15
#define I2S_SD_IN 13
#define I2S_SCK_IN 2
#define AUDIO_BUFFER_SIZE 3200  // 100ms at 16kHz mono PCM16

// Audio OUTPUT configuration (speaker) - NEW
#define I2S_PORT_OUT I2S_NUM_1
#define I2S_BCK_OUT 26    // Bit clock
#define I2S_WS_OUT 25     // Word select (LRCLK)
#define I2S_DATA_OUT 22   // Data out
#define PLAYBACK_BUFFER_SIZE 16384  // 16KB ring buffer
#define MIN_BUFFER_THRESHOLD 8192   // Minimum buffer before playback
#define CHUNK_SIZE 4096

// Camera pins (ESP32-CAM AI-Thinker)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

using namespace websockets;

// WebSocket clients
WebsocketsClient wsAudio;
WebsocketsClient wsCtrl;
WebsocketsClient wsCamera;

// State
bool audioConnected = false;
bool ctrlConnected = false;
bool cameraConnected = false;
unsigned long lastReconnectAttempt = 0;
const unsigned long reconnectInterval = 3000;  // 3 seconds

// Audio playback state - NEW
uint8_t playbackBuffer[PLAYBACK_BUFFER_SIZE];
volatile size_t writePos = 0;
volatile size_t readPos = 0;
volatile size_t available = 0;
volatile bool isPlaying = false;
String currentRequestId = "";

// ===== Setup =====
void setup() {
  Serial.begin(115200);
  Serial.println("\n\nESP32 Real-Time AI Assistant with TTS");
  Serial.println("======================================");
  
  // Initialize camera
  if (!initCamera()) {
    Serial.println("ERROR: Camera init failed!");
    return;
  }
  Serial.println("✓ Camera initialized");
  
  // Initialize I2S microphone (input)
  if (!initMicrophone()) {
    Serial.println("ERROR: Microphone init failed!");
    return;
  }
  Serial.println("✓ Microphone initialized");
  
  // Initialize I2S speaker (output) - NEW
  if (!initSpeaker()) {
    Serial.println("ERROR: Speaker init failed!");
    return;
  }
  Serial.println("✓ Speaker initialized");
  
  // Connect to WiFi
  connectWiFi();
  
  // Connect WebSockets
  connectWebSockets();
  
  Serial.println("\n✓ Setup complete!");
  Serial.println("Streaming audio and waiting for commands...\n");
}

// ===== Main Loop =====
void loop() {
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected! Reconnecting...");
    connectWiFi();
  }
  
  // Check WebSocket connections and reconnect if needed
  if (millis() - lastReconnectAttempt > reconnectInterval) {
    if (!audioConnected || !ctrlConnected || !cameraConnected) {
      connectWebSockets();
      lastReconnectAttempt = millis();
    }
  }
  
  // Poll WebSocket messages
  if (audioConnected) wsAudio.poll();
  if (ctrlConnected) wsCtrl.poll();
  if (cameraConnected) wsCamera.poll();
  
  // Stream audio from microphone
  if (audioConnected) {
    streamAudio();
  }
  
  // Play audio from buffer - NEW
  if (isPlaying) {
    playAudio();
  }
  
  // Request more audio if buffer is low - NEW
  if (isPlaying && available < MIN_BUFFER_THRESHOLD) {
    requestMoreAudio();
  }
  
  delay(10);
}

// ===== WiFi Functions =====
void connectWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);
  
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n✗ WiFi connection failed!");
  }
}

// ===== WebSocket Functions =====
void connectWebSockets() {
  // Connect audio WebSocket
  if (!audioConnected) {
    String audioUrl = String("ws://") + serverHost + ":" + serverPort + wsAudioPath;
    Serial.print("Connecting to audio WebSocket: ");
    Serial.println(audioUrl);
    
    audioConnected = wsAudio.connect(audioUrl);
    if (audioConnected) {
      Serial.println("✓ Audio WebSocket connected");
      
      // Set up message handler for audio chunks - NEW
      wsAudio.onMessage([](WebsocketsMessage message) {
        handleAudioChunk(message);
      });
    } else {
      Serial.println("✗ Audio WebSocket failed");
    }
  }
  
  // Connect control WebSocket
  if (!ctrlConnected) {
    String ctrlUrl = String("ws://") + serverHost + ":" + serverPort + wsCtrlPath;
    Serial.print("Connecting to control WebSocket: ");
    Serial.println(ctrlUrl);
    
    ctrlConnected = wsCtrl.connect(ctrlUrl);
    if (ctrlConnected) {
      Serial.println("✓ Control WebSocket connected");
      
      // Set up message handler for CAPTURE commands
      wsCtrl.onMessage([](WebsocketsMessage message) {
        handleCaptureCommand(message.data());
      });
    } else {
      Serial.println("✗ Control WebSocket failed");
    }
  }
  
  // Connect camera WebSocket
  if (!cameraConnected) {
    String cameraUrl = String("ws://") + serverHost + ":" + serverPort + wsCameraPath;
    Serial.print("Connecting to camera WebSocket: ");
    Serial.println(cameraUrl);
    
    cameraConnected = wsCamera.connect(cameraUrl);
    if (cameraConnected) {
      Serial.println("✓ Camera WebSocket connected");
      
      // Set up message handler for acknowledgments
      wsCamera.onMessage([](WebsocketsMessage message) {
        Serial.print("Server response: ");
        Serial.println(message.data());
      });
    } else {
      Serial.println("✗ Camera WebSocket failed");
    }
  }
}

// ===== Camera Functions =====
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Image quality settings
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;  // 640x480
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
  }
  
  // Initialize camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  
  return true;
}

void handleCaptureCommand(String message) {
  Serial.println("\n=== CAPTURE Command Received ===");
  Serial.println(message);
  
  // Parse JSON
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, message);
  
  if (error) {
    Serial.print("JSON parse failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  String reqId = doc["req_id"] | "unknown";
  Serial.print("Request ID: ");
  Serial.println(reqId);
  
  // Capture and send image
  captureAndSendImage(reqId);
}

void captureAndSendImage(String reqId) {
  Serial.println("Capturing image...");
  
  // Capture image
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("✗ Camera capture failed!");
    return;
  }
  
  Serial.printf("✓ Image captured: %d bytes\n", fb->len);
  
  // Send JSON header
  StaticJsonDocument<256> doc;
  doc["req_id"] = reqId;
  doc["size"] = fb->len;
  doc["format"] = "jpeg";
  
  String header;
  serializeJson(doc, header);
  Serial.println("Sending header: " + header);
  wsCamera.send(header);
  
  // Send binary image data
  Serial.println("Sending image data...");
  wsCamera.sendBinary((const char*)fb->buf, fb->len);
  
  Serial.println("✓ Image sent!");
  
  // Return frame buffer
  esp_camera_fb_return(fb);
}

// ===== Microphone Functions (INPUT) =====
bool initMicrophone() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK_IN,
    .ws_io_num = I2S_WS_IN,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD_IN
  };
  
  esp_err_t err = i2s_driver_install(I2S_PORT_IN, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("I2S input driver install failed: 0x%x\n", err);
    return false;
  }
  
  err = i2s_set_pin(I2S_PORT_IN, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("I2S input set pin failed: 0x%x\n", err);
    return false;
  }
  
  return true;
}

void streamAudio() {
  static uint8_t audioBuffer[AUDIO_BUFFER_SIZE];
  size_t bytesRead = 0;
  
  // Read audio data from I2S
  esp_err_t result = i2s_read(I2S_PORT_IN, audioBuffer, AUDIO_BUFFER_SIZE, &bytesRead, portMAX_DELAY);
  
  if (result == ESP_OK && bytesRead > 0) {
    // Send audio chunk via WebSocket
    wsAudio.sendBinary((const char*)audioBuffer, bytesRead);
  }
}

// ===== Speaker Functions (OUTPUT) - NEW =====
bool initSpeaker() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S_MSB,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCK_OUT,
    .ws_io_num = I2S_WS_OUT,
    .data_out_num = I2S_DATA_OUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  
  esp_err_t err = i2s_driver_install(I2S_PORT_OUT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("I2S output driver install failed: 0x%x\n", err);
    return false;
  }
  
  err = i2s_set_pin(I2S_PORT_OUT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("I2S output set pin failed: 0x%x\n", err);
    return false;
  }
  
  // Set volume (optional, depends on DAC)
  i2s_set_clk(I2S_PORT_OUT, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
  
  return true;
}

void handleAudioChunk(WebsocketsMessage message) {
  if (!message.isText()) {
    return;
  }
  
  // Parse JSON message
  StaticJsonDocument<1024> doc;
  DeserializationError error = deserializeJson(doc, message.data());
  
  if (error) {
    Serial.print("Audio chunk JSON parse failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  String type = doc["type"] | "";
  if (type != "audio_chunk") {
    return;
  }
  
  // Extract audio data
  String requestId = doc["request_id"] | "";
  String audioDataB64 = doc["audio_data"] | "";
  int sequence = doc["sequence"] | 0;
  int totalChunks = doc["total_chunks"] | 0;
  
  Serial.printf("Received audio chunk %d/%d (req_id: %s)\n", 
                sequence + 1, totalChunks, requestId.c_str());
  
  // Decode base64 audio data
  int decodedLen = base64_dec_len(audioDataB64.c_str(), audioDataB64.length());
  uint8_t* decodedData = (uint8_t*)malloc(decodedLen);
  
  if (decodedData == NULL) {
    Serial.println("Failed to allocate memory for audio decode");
    return;
  }
  
  base64_decode((char*)decodedData, audioDataB64.c_str(), audioDataB64.length());
  
  // Write to playback buffer
  writeToBuffer(decodedData, decodedLen);
  
  free(decodedData);
  
  // Start playback if buffer has enough data
  if (!isPlaying && available >= MIN_BUFFER_THRESHOLD) {
    Serial.println("Starting audio playback...");
    isPlaying = true;
    currentRequestId = requestId;
  }
  
  // Check if this is the last chunk
  if (sequence + 1 == totalChunks) {
    Serial.println("Received all audio chunks");
  }
}

void writeToBuffer(uint8_t* data, size_t length) {
  for (size_t i = 0; i < length; i++) {
    if (available < PLAYBACK_BUFFER_SIZE) {
      playbackBuffer[writePos] = data[i];
      writePos = (writePos + 1) % PLAYBACK_BUFFER_SIZE;
      available++;
    } else {
      // Buffer full, drop data
      Serial.println("Warning: Playback buffer full, dropping data");
      break;
    }
  }
}

void playAudio() {
  if (available == 0) {
    // Buffer empty, stop playback
    Serial.println("Playback buffer empty, stopping playback");
    isPlaying = false;
    
    // Send playback complete message
    sendPlaybackComplete();
    
    // Clear buffer
    writePos = 0;
    readPos = 0;
    available = 0;
    
    return;
  }
  
  // Read chunk from buffer
  size_t toRead = min((size_t)CHUNK_SIZE, available);
  uint8_t chunk[CHUNK_SIZE];
  
  for (size_t i = 0; i < toRead; i++) {
    chunk[i] = playbackBuffer[readPos];
    readPos = (readPos + 1) % PLAYBACK_BUFFER_SIZE;
  }
  
  available -= toRead;
  
  // Write to I2S
  size_t bytesWritten = 0;
  i2s_write(I2S_PORT_OUT, chunk, toRead, &bytesWritten, portMAX_DELAY);
}

void requestMoreAudio() {
  // Send request for more audio data
  static unsigned long lastRequest = 0;
  unsigned long now = millis();
  
  if (now - lastRequest > 500) {  // Request every 500ms max
    StaticJsonDocument<128> doc;
    doc["type"] = "request_more_audio";
    doc["request_id"] = currentRequestId;
    doc["buffer_available"] = available;
    
    String message;
    serializeJson(doc, message);
    
    if (audioConnected) {
      wsAudio.send(message);
    }
    
    lastRequest = now;
  }
}

void sendPlaybackComplete() {
  StaticJsonDocument<128> doc;
  doc["type"] = "playback_complete";
  doc["request_id"] = currentRequestId;
  
  String message;
  serializeJson(doc, message);
  
  Serial.println("Sending playback complete: " + message);
  
  if (audioConnected) {
    wsAudio.send(message);
  }
  
  currentRequestId = "";
}

size_t getBufferAvailable() {
  return available;
}

size_t getBufferSpace() {
  return PLAYBACK_BUFFER_SIZE - available;
}

bool needsMoreData() {
  return available < MIN_BUFFER_THRESHOLD;
}
