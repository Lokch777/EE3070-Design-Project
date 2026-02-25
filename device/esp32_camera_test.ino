/*
 * ESP32 Camera Image Upload Test
 * 
 * This is a simplified test sketch to verify ESP32 can send images to EC2
 * 
 * Hardware: ESP32-CAM or similar
 * 
 * Setup:
 * 1. Install ESP32 board support in Arduino IDE
 * 2. Install ArduinoWebsockets library
 * 3. Configure WiFi credentials and server URL below
 * 4. Upload to ESP32-CAM
 */

#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include "esp_camera.h"


// WiFi credentials
const char* ssid = "***";
const char* password = "***";

// EC2 Server configuration
const char* serverHost = "***";  // e.g., "54.123.45.67"
const int serverPort = 8080;
const char* websocketPath = "/ws_camera";

// Camera pins for ESP32-CAM with OV3660 (8MB PSRAM)
// Note: OV3660 uses same pin configuration as OV2640 on ESP32-CAM AI-Thinker
#define PWDN_GPIO_NUM    -1 

#define RESET_GPIO_NUM   -1 

#define XCLK_GPIO_NUM    15 

#define SIOD_GPIO_NUM    4 

#define SIOC_GPIO_NUM    5 

#define Y9_GPIO_NUM      16 

#define Y8_GPIO_NUM      17 

#define Y7_GPIO_NUM      18 

#define Y6_GPIO_NUM      12 

#define Y5_GPIO_NUM      10 

#define Y4_GPIO_NUM      8 

#define Y3_GPIO_NUM      9 

#define Y2_GPIO_NUM      11 

#define VSYNC_GPIO_NUM   6 

#define HREF_GPIO_NUM    7 

#define PCLK_GPIO_NUM    13 

using namespace websockets;
WebsocketsClient client;

void setup() {
  Serial.begin(115200);
  delay(1000);  // Give serial time to initialize
  Serial.println("\n\nESP32 Camera Upload Test");
  
 
  
  // Initialize camera
  Serial.println("Initializing camera...");
  if (!initCamera()) {
    Serial.println("Camera init failed! Halting.");
    while(1) {
      delay(1000);  // Halt instead of continuing
    }
  }
  Serial.println("Camera initialized successfully");
  
  // Connect to WiFi
  connectWiFi();
  
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi failed! Halting.");
    while(1) {
      delay(1000);
    }
  }
  
  // Connect to WebSocket
  connectWebSocket();
  
  // Take and send test photo
  Serial.println("Waiting 3 seconds before first capture...");
  delay(3000);
  captureAndSend();
}

void loop() {
  // Keep WebSocket alive
  if (client.available()) {
    client.poll();
  } else {
    Serial.println("WebSocket disconnected, reconnecting...");
    delay(1000);
    connectWebSocket();
  }
  
  // Send image every 15 seconds for testing
  static unsigned long lastCapture = 0;
  if (millis() - lastCapture > 15000) {
    lastCapture = millis();
    captureAndSend();
  }
  
  delay(100);  // Small delay to prevent watchdog issues
}

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
  
  // Image quality settings (optimized for 8MB PSRAM + OV3660)
  if (psramFound()) {
    Serial.println("PSRAM found! Using high quality settings");
    config.frame_size = FRAMESIZE_VGA;  // 800x600 (OV3660 supports up to 3MP) CHANGE-> VGA 640x480)
    config.jpeg_quality = 10;  // Lower number = higher quality
    config.fb_count = 2;  // Double buffering with PSRAM
  } else {
    Serial.println("No PSRAM! Using conservative settings");
    config.frame_size = FRAMESIZE_VGA;  // 640x480 for no PSRAM
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }
  
  // Initialize camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return false;
  }
  
  return true;
}

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi connection failed!");
  }
}

void connectWebSocket() {
  String wsUrl = String("ws://") + serverHost + ":" + serverPort + websocketPath;
  Serial.print("Connecting to WebSocket: ");
  Serial.println(wsUrl);
  
  bool connected = client.connect(wsUrl);
  
  if (connected) {
    Serial.println("WebSocket connected!");
    
    // Set up message callback
    client.onMessage([](WebsocketsMessage message) {
      Serial.print("Received: ");
      Serial.println(message.data());
    });
  } else {
    Serial.println("WebSocket connection failed!");
  }
}

void captureAndSend() {
  if (!client.available()) {
    Serial.println("WebSocket not connected, skipping capture");
    return;
  }
  
  Serial.println("\n--- Capturing image ---");
  
  // Capture image
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed!");
    return;
  }
  
  Serial.printf("Image captured: %d bytes, %dx%d\n", fb->len, fb->width, fb->height);
  
  // Check image size (max 200KB as per spec)
  if (fb->len > 200000) {
    Serial.println("Warning: Image too large! Consider reducing quality.");
  }
  
  // Generate request ID
  String reqId = "esp32-test-" + String(millis());
  
  // Send JSON header
  String header = "{\"req_id\":\"" + reqId + "\",\"size\":" + String(fb->len) + ",\"format\":\"jpeg\"}";
  Serial.println("Sending header: " + header);
  
  bool headerSent = client.send(header);
  if (!headerSent) {
    Serial.println("Failed to send header!");
    esp_camera_fb_return(fb);
    return;
  }
  
  delay(100);  // Small delay between header and data
  
  // Send binary image data
  Serial.println("Sending image data...");
  bool dataSent = client.sendBinary((const char*)fb->buf, fb->len);
  
  if (dataSent) {
    Serial.println("Image sent successfully!");
  } else {
    Serial.println("Failed to send image data!");
  }
  
  // Return frame buffer
  esp_camera_fb_return(fb);
}