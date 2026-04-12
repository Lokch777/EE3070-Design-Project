# 🎙️ ESP32 ASR Capture Vision MVP + Real-Time AI Assistant

<div align="center">

![ESP32](https://img.shields.io/badge/ESP32-CAM-blue?style=for-the-badge&logo=espressif)
![Python](https://img.shields.io/badge/Python-3.8+-green?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal?style=for-the-badge&logo=fastapi)

**Voice-Controlled Object Recognition System with Text-to-Speech**

A real-time IoT system that uses ESP32 devices for continuous audio capture, triggers image capture via ASR (Automatic Speech Recognition), performs object identification using vision AI models, and provides spoken responses through text-to-speech for visually impaired users.

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-system-architecture) • [Deployment](#-aws-ec2-deployment) • [Documentation](#-documentation)

</div>

---

## 📖 Project Overview

### Objectives

This project implements an **always-listening voice-controlled object recognition system with audio feedback** designed for wearable devices (smart glasses) or IoT applications. The system enables hands-free interaction where users can simply speak questions to capture and hear descriptions of objects in their environment.

**Primary Goals:**

1. **Continuous Voice Monitoring**: Enable 24/7 audio streaming from ESP32 devices with real-time speech-to-text transcription
2. **Voice-Activated Capture**: Trigger image capture through natural Chinese voice commands without manual button presses
3. **AI-Powered Recognition**: Leverage state-of-the-art vision models to identify and describe objects in captured images
4. **Spoken Responses**: Convert AI descriptions to speech and play through ESP32 speaker for visually impaired users
5. **Real-Time Feedback**: Provide instant visual feedback through a web dashboard showing transcriptions, images, and AI responses
6. **Robust Connectivity**: Ensure reliable operation with automatic reconnection and error recovery mechanisms
7. **Security First**: Protect API credentials by keeping them exclusively on the backend server

**Target Use Cases:**

- 🕶️ **Smart Glasses for Visually Impaired**: Assistive technology to identify objects through voice questions and hear spoken descriptions
- 🏭 **Industrial IoT**: Hands-free equipment inspection and inventory management
- 🏥 **Healthcare**: Medical device identification and medication verification with audio feedback
- 🎓 **Education**: Interactive learning tools for object recognition
- 🏠 **Smart Home**: Voice-controlled home automation and object tracking

### Design Philosophy

The system follows an **event-driven architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                     Design Principles                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Modularity      │ Independent components with clear APIs │
│ 2. Scalability     │ Event bus enables easy feature addition│
│ 3. Reliability     │ Auto-reconnection and error recovery   │
│ 4. Real-Time       │ WebSocket-based low-latency comms      │
│ 5. Security        │ Zero-trust: API keys only on backend   │
│ 6. Testability     │ Property-based testing for correctness │
│ 7. Accessibility   │ Audio feedback for visually impaired   │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**

- **WebSocket Communication**: Chosen for bidirectional real-time data streaming (audio, control commands, images, events)
- **Event Bus Pattern**: Decouples components and enables flexible event routing and history tracking
- **State Machine**: Ensures predictable behavior through well-defined states (LISTENING → TRIGGERED → CAPTURING → ANALYZING → TTS → PLAYBACK → DONE)
- **Request Correlation**: Unique `req_id` tracks each trigger-to-result flow across all components
- **Cooldown Mechanism**: 3-second cooldown prevents duplicate triggers from rapid speech
- **Timeout Protection**: Configurable timeouts (5s capture, 8s vision, 5s TTS) prevent indefinite waiting
- **Ring Buffer**: Memory-efficient event history (last 100 events) for debugging and UI display
- **Audio Buffering**: 16KB ring buffer on ESP32 for smooth audio playback

### System Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Complete System Flow                          │
└─────────────────────────────────────────────────────────────────┘

1. 🎤 CONTINUOUS LISTENING
   └─> ESP32 streams PCM16 audio (16kHz mono) via WebSocket
       └─> Backend forwards to Qwen3-ASR service
           └─> ASR returns real-time transcription

2. 🎯 QUESTION DETECTION (NEW!)
   └─> Question Trigger Engine monitors ASR final text
       └─> Detects questions: "describe the view", "what do I see", etc.
           └─> Generates unique req_id
               └─> Broadcasts question_detected event

3. 📸 IMAGE CAPTURE
   └─> Backend sends CAPTURE command to ESP32
       └─> ESP32 captures JPEG (max 800x600 with 8MB PSRAM, 200KB)
           └─> Uploads image with req_id
               └─> Backend validates and stores

4. 🤖 AI ANALYSIS
   └─> Backend calls Qwen Omni Flash vision model
       └─> Sends: JPEG + user's question as context
           └─> Receives: Object description text
               └─> Broadcasts vision_result event

5. 🔊 TEXT-TO-SPEECH (NEW!)
   └─> TTS Adapter converts description to speech
       └─> Uses Qwen TTS service (Chinese language)
           └─> Generates PCM16 audio at 16kHz
               └─> Broadcasts audio_ready event

6. 📢 AUDIO PLAYBACK (NEW!)
   └─> Audio Playback Coordinator streams audio to ESP32
       └─> Sends 4KB chunks via WebSocket
           └─> ESP32 buffers and plays through I2S speaker
               └─> User hears the description

7. 🌐 UI UPDATE
   └─> Web UI receives all events via WebSocket
       └─> Displays: Transcription → Trigger → Image → AI Result
           └─> User sees complete flow in <10 seconds

6. ⏱️ COOLDOWN
   └─> System enters 3-second cooldown
       └─> Prevents duplicate triggers
           └─> Returns to LISTENING state
```

### Technical Specifications

| Component | Specification | Rationale |
|-----------|--------------|-----------|
| **Hardware** | ESP32-CAM with OV3660 camera, 8MB PSRAM | High-quality image capture with sufficient memory buffer |
| **Audio Format** | PCM16, 16kHz, Mono | Standard format for ASR, balances quality and bandwidth |
| **Image Format** | JPEG, max 800x600, <200KB | Sufficient for object recognition, fast transmission |
| **Trigger Keywords** | 4 Chinese phrases + 4 English questions | Natural language commands for diverse users |
| **Cooldown Period** | 3 seconds | Prevents accidental double-triggers from speech patterns |
| **Capture Timeout** | 5 seconds | Reasonable time for ESP32 to capture and upload |
| **Vision Timeout** | 8 seconds | Accounts for API latency and processing time |
| **TTS Timeout** | 5 seconds | Quick audio generation for responsive feedback |
| **Event Buffer** | 100 events (ring buffer) | Balances memory usage and debugging capability |
| **Audio Buffer** | 16KB ring buffer on ESP32 | Smooth audio playback without stuttering |
| **Concurrent Requests** | 1 (MVP) | Simplifies state management, expandable later |
| **Target Latency** | <10 seconds end-to-end | From trigger speech to audio playback completion |

### Architecture Highlights

**Backend Components:**

- **WebSocket Gateway**: Manages 4 endpoints (`/ws_audio`, `/ws_ctrl`, `/ws_camera`, `/ws_ui`) with heartbeat monitoring
- **Event Bus**: Central message broker using asyncio queues for pub/sub pattern
- **ASR Bridge**: Maintains persistent connection to Qwen3-ASR with auto-reconnection
- **Trigger Engine**: Keyword detection with cooldown and state management
- **Capture Coordinator**: Orchestrates image capture with timeout handling
- **Vision Adapter**: Abstraction layer for vision models (currently Qwen Omni Flash)
- **App Coordinator**: Main orchestrator coordinating all components

**Communication Protocols:**

- **Audio Stream**: Binary WebSocket (PCM16 chunks, 100ms/chunk = 3.2KB)
- **Control Commands**: JSON over WebSocket (`{"type": "CAPTURE", "req_id": "..."}`)
- **Image Upload**: JSON header + binary JPEG payload
- **UI Events**: JSON over WebSocket (typed events with timestamps)
- **HTTP API**: REST endpoints for health checks, history, and manual testing

**Error Handling Strategy:**

| Error Type | Recovery Strategy | Max Retries | Backoff |
|------------|------------------|-------------|---------|
| Connection Timeout | Auto-reconnect | Infinite | Exponential (3s → 60s) |
| ASR Connection Failed | Auto-reconnect | 3 | 5s fixed |
| ASR Auth Failed | Stop service | 0 | N/A |
| Capture Timeout | Mark failed, continue | 0 | N/A |
| Vision Timeout | Retry once | 1 | 5s |
| Invalid Image | Reject and log | 0 | N/A |

---

## 🌟 Features

- **🎤 Continuous Audio Streaming**: ESP32 captures audio via I2S microphone and streams to backend
- **🗣️ Voice-Activated Triggers**: ASR detects Chinese trigger phrases to initiate image capture
- **❓ Question Detection**: NEW! Detects voice questions like "describe the view", "what do I see" (English & Chinese)
- **📸 On-Demand Image Capture**: ESP32-CAM captures JPEG images only when triggered (OV3660 camera, 8MB PSRAM)
- **🤖 AI-Powered Vision**: Qwen Omni Flash vision model identifies objects in captured images with question context
- **🔊 Text-to-Speech**: NEW! Converts AI descriptions to natural Chinese speech using Qwen TTS
- **📢 Audio Playback**: NEW! Streams audio back to ESP32 and plays through I2S speaker for visually impaired users
- **🌐 Real-Time Web UI**: Live dashboard showing ASR transcripts, images, and AI responses
- **🔄 Auto-Reconnection**: Robust WebSocket connections with automatic recovery
- **🔒 Secure API Management**: All API keys stored securely on backend server
- **☁️ Cloud-Ready**: Designed for AWS EC2 deployment with easy scaling
- **⚡ Low Latency**: Complete flow in <10 seconds (target: <5 seconds)
- **🛡️ Error Recovery**: Comprehensive error handling with retry logic and spoken error messages
- **🎯 Resource Management**: Concurrent request control and memory monitoring

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ESP32 Device                            │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ I2S Mic      │              │ ESP32-CAM    │                │
│  │ (16kHz PCM)  │              │ (JPEG)       │                │
│  └──────┬───────┘              └──────┬───────┘                │
│         │                             │                         │
│         └─────────────┬───────────────┘                         │
└───────────────────────┼─────────────────────────────────────────┘
                        │ WebSocket (ws_audio, ws_ctrl, ws_camera)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AWS EC2 Backend (FastAPI)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Event Bus    │  │ ASR Bridge   │  │ Trigger      │         │
│  │              │◄─┤ (Qwen3-ASR)  │─►│ Engine       │         │
│  └──────┬───────┘  └──────────────┘  └──────┬───────┘         │
│         │                                    │                  │
│  ┌──────▼───────┐  ┌──────────────┐  ┌──────▼───────┐         │
│  │ Capture      │  │ Vision       │  │ App          │         │
│  │ Coordinator  │─►│ Adapter      │◄─┤ Coordinator  │         │
│  └──────────────┘  │ (Qwen Omni)  │  └──────────────┘         │
│                    └──────────────┘                             │
└───────────────────────────────────────────────────────────────┬─┘
                        │ WebSocket (ws_ui)                      │
                        ▼                                        │
┌─────────────────────────────────────────────────────────────┐ │
│                      Web UI (Browser)                        │ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │ │
│  │ ASR Display  │  │ Image Viewer │  │ AI Response  │      │ │
│  │ (Real-time)  │  │ (Captured)   │  │ (Text)       │      │ │
│  └──────────────┘  └──────────────┘  └──────────────┘      │ │
└─────────────────────────────────────────────────────────────┘ │
                                                                 │
                        HTTP API (history, health)  ◄────────────┘
```

### Component Overview

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **ESP32 Device** | ESP32 + I2S Mic + ESP32-CAM | Audio/image capture and streaming |
| **Backend Server** | FastAPI + Python 3.8+ | WebSocket gateway, event coordination |
| **ASR Service** | Qwen3-ASR-Flash-Realtime | Real-time speech-to-text transcription |
| **Vision Model** | Qwen Omni Flash | Object recognition and description |
| **Web UI** | HTML5 + JavaScript + WebSocket | Real-time monitoring dashboard |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** installed
- **Git** installed
- **AWS EC2 instance** (Ubuntu 20.04+ recommended) or local machine
- **DashScope API Key** (required for ASR; in Omni mode this is the only required API key)
- **ESP32 device** with microphone and camera (optional for testing)

### 1️⃣ Clone Repository

```bash
git clone https://github.com/Lokch777/EE3070-Design-Project.git
cd EE3070-Design-Project
```

### 2️⃣ Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
nano .env  # Edit and add your API keys
```

**Required Environment Variables** (`.env` file):

```env
# Omni Realtime Mode
OMNI_MODE=true
OMNI_MODEL=qwen3.5-omni-plus-realtime-2026-03-15
OMNI_VOICE=Cherry

# Required API key (DashScope)
ASR_API_KEY=your_dashscope_api_key_here

# Optional API keys (used when not in Omni mode)
VISION_API_KEY=your_vision_api_key_here
TTS_API_KEY=your_tts_api_key_here

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
LOG_LEVEL=INFO

# Endpoints
ASR_ENDPOINT=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
VISION_ENDPOINT=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
TTS_ENDPOINT=wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime
```

### 3️⃣ Start Backend Server

```bash
# Development mode (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000
```

Server will start at: `http://localhost:8000`

### 4️⃣ Access Web UI

Open your browser and navigate to:
- **Local**: `http://localhost:8000/web/index.html`
- **AWS EC2**: `http://your-ec2-public-ip:8000/web/index.html`

### 5️⃣ Configure ESP32 (Optional)

Update the firmware configuration in `device/esp32_full_firmware.ino`:

```cpp
// WiFi Configuration
const char* WIFI_SSID = "your-wifi-ssid";
const char* WIFI_PASSWORD = "your-wifi-password";

// WebSocket Server Configuration
const char* WS_HOST = "your-ec2-public-ip";  // or "localhost" for local testing
const int WS_PORT = 8000;
const bool USE_SSL = false;  // Set to true for production with SSL
```

Flash the firmware to your ESP32 device using Arduino IDE.

---

## ☁️ AWS EC2 Deployment

### Step 1: Launch EC2 Instance

1. **Choose AMI**: 
   - Amazon Linux 2 (recommended - AWS optimized)
   - Amazon Linux 2023 (latest version)
   - Ubuntu Server 20.04 LTS or 22.04 LTS
2. **Instance Type**: t2.micro (free tier) or t2.small (recommended)
3. **Storage**: 8GB minimum, 16GB recommended
4. **Key Pair**: Create or use existing SSH key pair

### Step 2: Configure Security Group

Open the following ports in your EC2 security group:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH access |
| 8000 | TCP | 0.0.0.0/0 | Backend API & WebSocket |
| 80 | TCP | 0.0.0.0/0 | HTTP (optional, for Nginx) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (optional, for SSL) |

### Step 3: Connect to EC2

```bash
ssh -i your-key.pem ubuntu@your-ec2-public-ip
```

### Step 4: Install Dependencies (Ubuntu)

**For Ubuntu 20.04/22.04:**

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.9+ and pip
sudo apt install python3 python3-pip python3-venv git -y

# Install additional tools
sudo apt install htop curl wget -y

# Verify Python version
python3 --version  # Should be 3.8 or higher
```

**For Amazon Linux 2:**

```bash
# Update system packages
sudo yum update -y

# Install Python 3.9+ and pip
sudo yum install python3 python3-pip git -y

# Install additional tools
sudo yum install htop curl wget gcc python3-devel -y

# Verify Python version
python3 --version  # Should be 3.7 or higher
```

**For Amazon Linux 2023:**

```bash
# Update system packages
sudo dnf update -y

# Install Python 3.11+ and pip (pre-installed)
sudo dnf install python3 python3-pip git -y

# Install additional tools
sudo dnf install htop curl wget gcc python3-devel -y

# Verify Python version
python3 --version  # Should be 3.11 or higher
```

### Step 5: Deploy Application

```bash
# Clone repository
git clone https://github.com/Lokch777/EE3070-Design-Project.git
cd EE3070-Design-Project/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Add your API keys
```

### Step 6: Run as Background Service

#### Option A: Using `nohup` (Quick & Simple)

```bash
# Start server in background
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &

# Check if running
ps aux | grep uvicorn

# View logs
tail -f server.log

# Stop server
pkill -f uvicorn
```

#### Option B: Using `systemd` (Production Recommended)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/esp32-asr.service
```

Add the following content (adjust paths based on your OS):

**For Ubuntu:**

```ini
[Unit]
Description=ESP32 ASR Capture Vision Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/EE3070-Design-Project/backend
Environment="PATH=/home/ubuntu/EE3070-Design-Project/backend/venv/bin"
ExecStart=/home/ubuntu/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**For Amazon Linux 2/2023:**

```ini
[Unit]
Description=ESP32 ASR Capture Vision Backend
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/EE3070-Design-Project/backend
Environment="PATH=/home/ec2-user/EE3070-Design-Project/backend/venv/bin"
ExecStart=/home/ec2-user/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable esp32-asr

# Start service
sudo systemctl start esp32-asr

# Check status
sudo systemctl status esp32-asr

# View logs
sudo journalctl -u esp32-asr -f

# Restart service
sudo systemctl restart esp32-asr

# Stop service
sudo systemctl stop esp32-asr
```

### Step 7: Verify Deployment

```bash
# Check if server is running
curl http://localhost:8000/api/health

# Expected response:
# {"status":"healthy","timestamp":"2024-02-11T..."}
```

Access from browser: `http://your-ec2-public-ip:8000/web/index.html`

### Step 8: (Optional) Setup Nginx Reverse Proxy

For production with SSL/HTTPS:

```bash
# Install Nginx
sudo apt install nginx -y

# Create Nginx configuration
sudo nano /etc/nginx/sites-available/esp32-asr
```

Add configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # or EC2 public IP

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and restart Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/esp32-asr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 📁 Project Structure

```
EE3070-Design-Project/
├── 📂 backend/                    # Python backend server
│   ├── 📄 main.py                # FastAPI application entry point
│   ├── 📄 event_bus.py           # Event distribution system
│   ├── 📄 asr_bridge.py          # ASR service integration
│   ├── 📄 trigger_engine.py      # Keyword detection & trigger logic
│   ├── 📄 capture_coordinator.py # Image capture coordination
│   ├── 📄 vision_adapter.py      # Vision model integration
│   ├── 📄 app_coordinator.py     # Main application coordinator
│   ├── 📄 models.py              # Data models (Pydantic)
│   ├── 📄 config.py              # Configuration management
│   ├── 📄 requirements.txt       # Python dependencies
│   ├── 📄 .env.example           # Environment variables template
│   └── 📄 __init__.py
├── 📂 web/                        # Web UI frontend
│   ├── 📄 index.html             # Main HTML page
│   ├── 📄 style.css              # Styling
│   └── 📄 app.js                 # Frontend JavaScript logic
├── 📂 device/                     # ESP32 firmware
│   ├── 📄 esp32_full_firmware.ino    # Complete ESP32 firmware
│   ├── 📄 esp32_camera_test.ino      # Camera testing firmware
│   └── 📄 esp32_simulator.py         # Python ESP32 simulator
├── 📂 tests/                      # Unit tests
│   ├── 📄 conftest.py            # Pytest configuration
│   ├── 📄 test_models.py         # Model tests
│   └── 📄 __init__.py
├── 📂 .kiro/specs/                # Project specifications
│   └── 📂 esp32-asr-capture-vision-mvp/
│       ├── 📄 requirements.md    # Requirements document
│       ├── 📄 design.md          # Design document
│       └── 📄 tasks.md           # Implementation tasks
├── 📄 README.md                   # This file
├── 📄 QUICKSTART.md              # Quick start guide
├── 📄 DEPLOYMENT.md              # Deployment guide
├── 📄 API.md                     # API documentation
├── 📄 TESTING.md                 # Testing guide
├── 📄 PROJECT_SUMMARY.md         # Project summary
├── 📄 BACKUP_GUIDE.md            # Backup instructions
├── 📄 GITHUB_UPLOAD_GUIDE.md     # GitHub upload guide
├── 📄 test_upload.py             # Image upload test script
├── 📄 start_server.sh            # Server startup script
├── 📄 package_for_backup.sh      # Backup packaging script
├── 📄 pytest.ini                 # Pytest configuration
└── 📄 .gitignore                 # Git ignore rules
```

---

## 🔌 API Endpoints

### HTTP REST API

| Method | Endpoint | Description | Response |
|--------|----------|-------------|----------|
| `GET` | `/` | Health check | `{"status": "ok"}` |
| `GET` | `/api/health` | System health status | `{"status": "healthy", "timestamp": "..."}` |
| `GET` | `/api/history?limit=20` | Get recent events | `[{event}, ...]` |
| `GET` | `/api/images` | List captured images | `["img1.jpg", ...]` |
| `POST` | `/api/upload` | Upload test image | `{"status": "ok", "filename": "..."}` |

### WebSocket Endpoints

| Endpoint | Direction | Purpose | Data Format |
|----------|-----------|---------|-------------|
| `/ws_audio` | ESP32 → Server | Audio streaming | Binary (PCM16, 16kHz mono) |
| `/ws_ctrl` | Server → ESP32 | Control commands | JSON: `{"type": "CAPTURE", "req_id": "..."}` |
| `/ws_camera` | ESP32 → Server | Image upload | Binary (JPEG) with JSON header |
| `/ws_ui` | Server → Browser | Event notifications | JSON: `{"type": "...", "data": {...}}` |

### WebSocket Event Types

**From Server to UI** (`/ws_ui`):

```json
{
  "type": "asr_partial",
  "data": {"text": "請你幫我...", "timestamp": "..."}
}

{
  "type": "asr_final",
  "data": {"text": "請你幫我識別物品", "timestamp": "..."}
}

{
  "type": "trigger_fired",
  "data": {"req_id": "abc123", "trigger_text": "識別物品", "timestamp": "..."}
}

{
  "type": "capture_received",
  "data": {"req_id": "abc123", "image_url": "/images/abc123.jpg", "timestamp": "..."}
}

{
  "type": "vision_result",
  "data": {"req_id": "abc123", "result": "This is a red apple...", "timestamp": "..."}
}

{
  "type": "error",
  "data": {"message": "...", "timestamp": "..."}
}
```

---

## 🎯 Trigger Keywords & Questions

The system recognizes two types of voice commands:

### Object Identification Triggers (Original MVP)

| Trigger Phrase | Pinyin | English Translation |
|----------------|--------|---------------------|
| 識別物品 | shí bié wù pǐn | Identify object |
| 認下呢個係咩 | rèn xià nǐ gè xì miē | Recognize what this is |
| 幫我認 | bāng wǒ rèn | Help me recognize |
| 睇下呢個 | dì xià nǐ gè | Look at this |

### Voice Questions (NEW - TTS Feature)

**English Questions:**
- "describe the view" - Get a spoken description of what's in front
- "what do I see" - Hear what objects are visible
- "what's in front of me" - Identify objects ahead
- "tell me what you see" - Request a detailed description

**Chinese Questions:**
- "描述一下景象" (miáo shù yī xià jǐng xiàng) - Describe the scene
- "我看到什麼" (wǒ kàn dào shén me) - What do I see
- "前面是什麼" (qián miàn shì shén me) - What's in front
- "告訴我你看到什麼" (gào sù wǒ nǐ kàn dào shén me) - Tell me what you see

**Cooldown**: 3 seconds between triggers to prevent duplicate captures.

**Response**: Questions trigger image capture + AI analysis + spoken audio response through ESP32 speaker!

---

## 🧪 Testing

### Run Unit Tests

```bash
cd backend
pytest tests/ -v
```

### Test with ESP32 Simulator

```bash
# Simulate ESP32 device (audio + camera)
python device/esp32_simulator.py --host localhost --port 8000
```

### Test Image Upload

```bash
# Upload a test image
python test_upload.py --image path/to/image.jpg --host localhost --port 8000
```

### Manual Testing Checklist

- [ ] Backend starts without errors
- [ ] Web UI loads and connects via WebSocket
- [ ] ASR transcription appears in real-time
- [ ] Trigger keyword detection works
- [ ] Image capture and upload successful
- [ ] Vision model returns object description
- [ ] Auto-reconnection works after disconnect

---

## 🛠️ Development

### Code Style

```bash
# Install development tools
pip install black flake8 mypy

# Format code
black backend/

# Lint code
flake8 backend/

# Type checking
mypy backend/
```

### Environment Variables

All sensitive configuration is stored in `.env` file (never commit this file):

```env
# Required (Omni mode)
ASR_API_KEY=sk-xxxxx

# Required in non-Omni mode
VISION_API_KEY=sk-xxxxx
TTS_API_KEY=sk-xxxxx

# Optional (with defaults)
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
LOG_LEVEL=INFO
OMNI_MODE=true
OMNI_MODEL=qwen3.5-omni-plus-realtime-2026-03-15
```

---

## 🐛 Troubleshooting

### Backend Won't Start

**Problem**: `ModuleNotFoundError` or import errors

**Solution**:
```bash
# Ensure virtual environment is activated
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Reinstall dependencies
pip install -r requirements.txt
```

**Problem**: `Port 8000 already in use`

**Solution**:
```bash
# Find process using port 8000
lsof -i :8000  # Linux/Mac
netstat -ano | findstr :8000  # Windows

# Kill the process
kill -9 <PID>  # Linux/Mac
taskkill /PID <PID> /F  # Windows
```

### ESP32 Connection Issues

**Problem**: ESP32 can't connect to server

**Solution**:
1. Check EC2 security group allows port 8000
2. Verify ESP32 firmware has correct IP address
3. Ensure WiFi credentials are correct
4. Check server logs: `tail -f server.log`

**Problem**: WebSocket connection drops frequently

**Solution**:
1. Increase WebSocket timeout in firmware
2. Check network stability
3. Enable auto-reconnection (already implemented)

### Web UI Issues

**Problem**: UI shows "Disconnected"

**Solution**:
1. Verify backend is running: `curl http://localhost:8000/api/health`
2. Check browser console for errors (F12)
3. Ensure WebSocket URL is correct in `app.js`

**Problem**: No ASR transcription appearing

**Solution**:
1. Verify `ASR_API_KEY` is set correctly (`VISION_API_KEY` and `TTS_API_KEY` are also required when `OMNI_MODE=false`)
2. Check backend logs for ASR errors
3. Ensure ESP32 is streaming audio

### AWS EC2 Specific

**Problem**: Can't access EC2 from browser

**Solution**:
1. Check security group allows inbound on port 8000
2. Verify server is listening on `0.0.0.0` not `127.0.0.1`
3. Use public IP, not private IP

**Problem**: Server stops after SSH disconnect

**Solution**:
Use `nohup` or `systemd` service (see deployment section)

---

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Quick start guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Detailed deployment instructions
- **[API.md](API.md)** - Complete API reference
- **[TESTING.md](TESTING.md)** - Testing guide
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Project overview
- **[BACKUP_GUIDE.md](BACKUP_GUIDE.md)** - Backup and recovery
- **[GITHUB_UPLOAD_GUIDE.md](GITHUB_UPLOAD_GUIDE.md)** - GitHub upload instructions

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

### Contribution Guidelines

- Follow PEP 8 style guide for Python code
- Add unit tests for new features
- Update documentation as needed
- Ensure all tests pass before submitting PR

---

## 🙏 Acknowledgments

- **Alibaba Cloud** - DashScope API for ASR and Vision models
- **Qwen Team** - Qwen3-ASR and Qwen Omni Flash models
- **FastAPI** - Modern web framework for Python
- **ESP32 Community** - Hardware and firmware support

---

## 📞 Support

For issues, questions, or suggestions:

- **GitHub Issues**: [Create an issue](https://github.com/Lokch777/EE3070-Design-Project/issues)
- **Email**: your-email@example.com
- **Documentation**: Check the `docs/` folder

---

<div align="center">

**Made with ❤️ for EE3070 Design Project**

⭐ Star this repo if you find it helpful!

</div>
