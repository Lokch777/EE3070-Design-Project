# 🎙️ ESP32 ASR Capture Vision MVP + Real-Time AI Assistant (Phase 2)

<div align="center">

![ESP32](https://img.shields.io/badge/ESP32-CAM-blue?style=for-the-badge&logo=espressif)
![Python](https://img.shields.io/badge/Python-3.8+-green?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal?style=for-the-badge&logo=fastapi)
![Phase](https://img.shields.io/badge/Phase-2-purple?style=for-the-badge)

**Voice-Controlled Object Recognition with Continuous Visual Context & Real-Time Audio Feedback**

A real-time IoT system that uses ESP32 devices for continuous audio streaming, **continuous 1 FPS camera streaming**, and unified Qwen Omni AI processing for hands-free object identification with spoken responses.

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-system-architecture) • [Deployment](#-aws-ec2-deployment) • [Documentation](#-documentation)

</div>

---

## 📖 Project Overview

### Objectives

This project implements an **always-listening, always-watching voice-controlled AI assistant** designed for wearable devices (smart glasses) or IoT applications. The system enables natural hands-free interaction where users can simply speak questions while the AI continuously observes the environment through both audio and visual streams.

**Primary Goals:**

1. **Continuous Audio Streaming**: 24/7 PCM audio streaming from ESP32 with real-time ASR via Qwen Omni
2. **Continuous Visual Context**: NEW! 1 FPS QVGA camera streaming for persistent scene understanding
3. **Unified AI Processing**: Single Qwen Omni Realtime model handles ASR + Vision + TTS in one duplex stream
4. **Natural Conversation**: Server-side VAD enables trigger-free dialogue with barge-in support
5. **Spoken Responses**: Real-time TTS with audio playback through ESP32 speaker for accessibility
6. **Real-Time Feedback**: Web dashboard with live stream indicator, pipeline latency tracking, and event history
7. **Robust Connectivity**: Auto-reconnection, session refresh, and graceful fallback to batch mode
8. **Security First**: Zero-trust architecture with API keys exclusively on backend

**Target Use Cases:**

- 🕶️ **Smart Glasses for Visually Impaired**: Continuous scene description with voice Q&A and spoken answers
- 🏭 **Industrial IoT**: Hands-free equipment monitoring with live visual context and voice commands
- 🏥 **Healthcare**: Medication verification with continuous visual monitoring and audio confirmation
- 🎓 **Education**: Interactive learning with real-time object identification and spoken explanations
- 🏠 **Smart Home**: Voice-controlled automation with persistent environmental awareness

### Design Philosophy

The system follows an **event-driven, dual-mode architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                    Design Principles                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Modularity      │ Independent components with clear APIs │
│ 2. Scalability     │ Event bus enables easy feature addition│
│ 3. Reliability     │ Auto-reconnection and error recovery   │
│ 4. Real-Time       │ WebSocket-based low-latency comms      │
│ 5. Security        │ Zero-trust: API keys only on backend   │
│ 6. Testability     │ Property-based testing for correctness │
│ 7. Accessibility   │ Audio feedback for visually impaired   │
│ 8. Dual-Mode       │ Omni mode + fallback batch pipeline    │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**

- **Unified Omni Stream**: Single WebSocket connection to Qwen Omni handles ASR + Vision + TTS, reducing latency from 4-8s to 0.7-1.5s
- **Continuous Camera Streaming**: 1 FPS QVGA (320×240) JPEG streaming provides persistent visual context without overwhelming bandwidth
- **Event Bus Pattern**: Decouples components and enables flexible event routing, history tracking, and UI updates
- **State Machine**: Well-defined states (IDLE → LISTENING → PROCESSING → RESPONDING → INTERRUPTED) ensure predictable behavior
- **Barge-in Support**: Server-side VAD detects user interruptions and cancels ongoing responses for natural conversation
- **Dual-Mode Architecture**: `OMNI_MODE` flag enables seamless switching between new Omni pipeline and legacy batch pipeline
- **Resource Efficiency**: QVGA resolution + 1 FPS streaming stays within ESP32 bandwidth/PSRAM limits while providing useful visual context

### System Workflow (Phase 2 - Omni Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                 Complete System Flow (Omni Mode)                │
└─────────────────────────────────────────────────────────────────┘

1. 🎤 CONTINUOUS AUDIO + 📷 CONTINUOUS VIDEO
   └─> ESP32 streams PCM16 audio (16kHz mono) via /ws_audio
   └─> ESP32 streams QVGA JPEG (1 FPS) via /ws_camera
       └─> Backend forwards both streams to Qwen Omni Realtime

2. 🧠 UNIFIED AI PROCESSING
   └─> Qwen Omni processes audio + visual context together
       └─> Server-side VAD detects speech boundaries
           └─> Model generates text + audio response in one stream

3. 🔊 REAL-TIME AUDIO STREAMING
   └─> Omni streams audio deltas (24kHz PCM) to backend
       └─> Backend resamples to 16kHz and forwards to ESP32
           └─> ESP32 plays through I2S speaker with <100ms latency

4. 🛑 BARGE-IN SUPPORT (Natural Interruption)
   └─> User speaks while AI is responding
       └─> Omni detects new speech → cancels current response
           └─> Backend sends stop_playback to ESP32
               └─> Speaker stops immediately, MIC continues streaming

5. 🌐 LIVE UI UPDATES
   └─> Web UI receives events via /ws_ui:
       • camera_stream_started/stopped → Live stream indicator
       • camera_frame_received → Snapshot updates every ~1s
       • asr_partial/final → Real-time transcription
       • tts_started → TTS progress animation
       • error → Toast notifications

6. ⚙️ SESSION MANAGEMENT
   └─> Auto-refresh at 110 minutes (before 120-min API limit)
   └─> Graceful fallback to batch mode if Omni fails
```

### System Workflow (Batch Mode - Fallback)

```
┌─────────────────────────────────────────────────────────────────┐
│              Complete System Flow (Batch Mode)                  │
└─────────────────────────────────────────────────────────────────┘

1. 🎤 CONTINUOUS LISTENING
   └─> ESP32 streams PCM16 audio via /ws_audio
       └─> Backend forwards to Qwen3-ASR service
           └─> ASR returns real-time transcription

2. 🎯 QUESTION DETECTION
   └─> Question Trigger Engine monitors ASR final text
       └─> Detects questions: "describe the view", "what do I see", etc.
           └─> Generates unique req_id → broadcasts question_detected

3. 📸 ON-DEMAND IMAGE CAPTURE
   └─> Backend sends CAPTURE command via /ws_ctrl
       └─> ESP32 captures single JPEG (VGA, on-demand)
           └─> Uploads image with req_id via /ws_camera

4. 🤖 AI ANALYSIS + 🔊 TTS
   └─> Backend calls Qwen Omni Flash vision model
       └─> Receives object description → converts to speech via Qwen TTS
           └─> Streams audio chunks to ESP32 for playback

5. 🌐 UI UPDATE
   └─> Web UI displays: Transcription → Trigger → Image → AI Result
       └─> Complete flow in <10 seconds
```

### Technical Specifications (Phase 2)

| Component | Specification | Rationale |
|-----------|--------------|-----------|
| **Hardware** | ESP32-S3 with OV3660 camera, 8MB PSRAM | Sufficient for QVGA streaming + audio duplex |
| **Audio Format** | PCM16, 16kHz, Mono | Standard for ASR/TTS, balances quality and bandwidth |
| **Camera Resolution** | QVGA 320×240 (Phase 2), VGA 640×480 (Batch fallback) | QVGA provides useful context while staying within bandwidth limits |
| **Camera Frame Rate** | 1 FPS continuous (Phase 2), on-demand (Batch) | Omni API accepts ≤1 FPS; higher rates waste bandwidth |
| **Image Format** | JPEG, quality=15, ~10KB/frame (QVGA) | Small enough for continuous streaming, sufficient for recognition |
| **Trigger Keywords** | 4 Chinese + 4 English phrases (Batch mode only) | Natural language commands; Omni mode uses continuous VAD |
| **Voice Questions** | "describe the view", "前面是什麼", etc. | Works in both modes; Omni mode doesn't require exact phrases |
| **Cooldown Period** | 3 seconds (Batch mode), none (Omni mode) | Prevents duplicates in batch; Omni uses natural turn-taking |
| **Capture Timeout** | 5 seconds (Batch), N/A (Omni continuous) | Reasonable for on-demand capture |
| **Vision Timeout** | 8 seconds (Batch), N/A (Omni integrated) | Accounts for API latency in batch mode |
| **TTS Timeout** | 5 seconds (Batch), N/A (Omni streaming) | Quick audio generation for responsive feedback |
| **Event Buffer** | 100 events (ring buffer) | Balances memory usage and debugging capability |
| **Audio Buffer** | 1MB ring buffer on ESP32 | Smooth playback with 30+ seconds of pre-buffered audio |
| **Concurrent Requests** | 1 (MVP) | Simplifies state management, expandable later |
| **Target Latency** | <1.5s end-to-end (Omni), <10s (Batch) | From speech end to audio start |
| **Bandwidth Usage** | ~620 kbps total (Omni mode) | Well within ESP32-S3 WiFi capabilities (2-4 Mbps) |
| **PSRAM Usage** | ~1.8 MB (Omni mode) | Leaves ~6.2 MB free for future features |

### Architecture Highlights

**Backend Components:**

- **WebSocket Gateway**: Manages 4 endpoints (`/ws_audio`, `/ws_ctrl`, `/ws_camera`, `/ws_ui`) with heartbeat monitoring
- **Event Bus**: Central message broker using asyncio queues for pub/sub pattern and UI updates
- **OmniCoordinator** (NEW): Replaces AppCoordinator in Omni mode; handles unified audio+vision+TTS stream
- **OmniStreamAdapter** (NEW): Single WebSocket connection to Qwen Omni Realtime API
- **AudioPlaybackCoordinator**: Reused for ESP32 audio streaming; handles chunking, pacing, and error recovery
- **AppCoordinator** (Legacy): Full batch pipeline for fallback mode; remains fully functional
- **Dual-Mode Router**: `OMNI_MODE` flag dynamically selects coordinator at startup

**Communication Protocols:**

- **Audio Stream**: Binary WebSocket (PCM16 chunks, 100ms/chunk = 3.2KB)
- **Camera Stream** (Phase 2): Binary WebSocket (QVGA JPEG, ~10KB/frame @ 1 FPS)
- **Control Commands**: JSON over WebSocket (`{"type": "CAPTURE", "req_id": "..."}`)
- **UI Events**: JSON over WebSocket (typed events with timestamps and optional data)
- **HTTP API**: REST endpoints for health checks, history, images, and Omni status

**Error Handling Strategy:**

| Error Type | Recovery Strategy | Max Retries | Backoff |
|------------|------------------|-------------|---------|
| Omni Connection Failed | Auto-reconnect + fallback to batch | 3 | Exponential (3s → 60s) |
| Session Timeout (120min) | Proactive refresh at 110min | 1 | N/A |
| WebSocket Drop | Auto-reconnect on both ESP32 and backend | Infinite | Exponential |
| Omni API Error | Log + continue streaming; fallback if persistent | 0 | N/A |
| Camera Frame Too Large | Skip frame + log warning | 0 | N/A |
| Audio Buffer Overflow | Drop oldest frames + log warning | 0 | N/A |

---

## 🌟 Features

### Core Features (Both Modes)
- **🎤 Continuous Audio Streaming**: ESP32 captures audio via I2S microphone and streams to backend
- **🔊 Text-to-Speech**: Converts AI descriptions to natural Chinese speech using Qwen TTS
- **📢 Audio Playback**: Streams audio back to ESP32 and plays through I2S speaker for accessibility
- **🌐 Real-Time Web UI**: Live dashboard showing transcriptions, images, and AI responses
- **🔄 Auto-Reconnection**: Robust WebSocket connections with automatic recovery
- **🔒 Secure API Management**: All API keys stored securely on backend server
- **☁️ Cloud-Ready**: Designed for AWS EC2 deployment with easy scaling

### Phase 2 New Features (Omni Mode)
- **🎯 Unified AI Processing**: Single Qwen Omni model handles ASR + Vision + TTS in one stream
- **📷 Continuous Visual Context**: 1 FPS QVGA camera streaming for persistent scene understanding
- **💬 Natural Conversation**: Server-side VAD enables trigger-free dialogue with barge-in support
- **⚡ Ultra-Low Latency**: End-to-end latency reduced from 4-8s to 0.7-1.5s
- **🛑 Barge-in Support**: Speak while AI is responding → AI stops immediately and listens
- **🔄 Dual-Mode Architecture**: `OMNI_MODE` flag enables seamless switching between Omni and batch pipelines
- **📊 Live Stream Indicator**: Web UI shows pulsing green indicator when camera is streaming
- **🔍 Session Management**: Auto-refresh at 110 minutes to avoid 120-min API limit

### Batch Mode Features (Fallback)
- **🗣️ Voice-Activated Triggers**: ASR detects Chinese/English trigger phrases to initiate capture
- **❓ Question Detection**: Detects voice questions like "describe the view", "what do I see"
- **📸 On-Demand Image Capture**: ESP32-CAM captures VGA JPEG images only when triggered
- **🤖 AI-Powered Vision**: Qwen Omni Flash vision model identifies objects with question context
- **⚡ Reliable Fallback**: Full batch pipeline remains available if Omni mode fails

---

## 🏗️ System Architecture

### Omni Mode Architecture (Phase 2)

```
┌─────────────────────────────────────────────────────────────────┐
│                        ESP32 Device                             │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ I2S Mic      │              │ ESP32-CAM    │                │
│  │ (16kHz PCM)  │              │ (QVGA 1FPS)  │                │
│  └──────┬───────┘              └──────┬───────┘                │
│         │                             │                         │
│         └─────────────┬───────────────┘                         │
└───────────────────────┼─────────────────────────────────────────┘
                        │ WebSocket (ws_audio, ws_camera)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  AWS EC2 Backend (FastAPI)                      │
│  ┌─────────────────────────────────────────┐                   │
│  │           OmniCoordinator               │                   │
│  │  ┌──────────────┐  ┌─────────────────┐  │                   │
│  │  │ Event Bus    │  │ OmniStream      │  │                   │
│  │  │              │◄─┤ Adapter         │  │                   │
│  │  └──────┬───────┘  │ (Qwen Omni)     │  │                   │
│  │         │          └────────┬────────┘  │                   │
│  │  ┌──────▼───────┐           │            │                   │
│  │  │ AudioPlayback│◄──────────┘            │                   │
│  │  │ Coordinator  │                        │                   │
│  │  └──────────────┘                        │                   │
│  └─────────────────────────────────────────┘                   │
└───────────────────────────────────────────────────────────────┬─┘
                        │ WebSocket (ws_ui)                      │
                        ▼                                        │
┌─────────────────────────────────────────────────────────────┐ │
│                    Web UI (Browser)                         │ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │ │
│  │ Live Stream  │  │ ASR Display  │  │ AI Response  │       │ │
│  │ Indicator 🟢 │  │ (Real-time)  │  │ (Text+Audio) │       │ │
│  └──────────────┘  └──────────────┘  └──────────────┘       │ │
└─────────────────────────────────────────────────────────────┘ │
                        │ HTTP API (history, health, omni_status)│
                        └────────────────────────────────────────┘
```

### Batch Mode Architecture (Fallback)

```
┌─────────────────────────────────────────────────────────────────┐
│                        ESP32 Device                             │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ I2S Mic      │              │ ESP32-CAM    │                │
│  │ (16kHz PCM)  │              │ (VGA on-demand)│              │
│  └──────┬───────┘              └──────┬───────┘                │
│         │                             │                         │
│         └─────────────┬───────────────┘                         │
└───────────────────────┼─────────────────────────────────────────┘
                        │ WebSocket (ws_audio, ws_ctrl, ws_camera)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  AWS EC2 Backend (FastAPI)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Event Bus    │  │ ASR Bridge   │  │ Trigger      │          │
│  │              │◄─┤ (Qwen3-ASR)  │─►│ Engine       │          │
│  └──────┬───────┘  └──────────────┘  └──────┬───────┘          │
│         │                                   │                   │
│  ┌──────▼───────┐  ┌──────────────┐  ┌──────▼───────┐          │
│  │ Capture      │  │ Vision       │  │ App          │          │
│  │ Coordinator  │─►│ Adapter      │◄─┤ Coordinator  │          │
│  └──────────────┘  │ (Qwen Omni)  │  └──────────────┘          │
│                    └──────┬───────┘                           │
│  ┌──────────────┐         │                                   │
│  │ TTS Adapter  │◄────────┘                                   │
│  │ (Qwen TTS)   │                                             │
│  └──────┬───────┘                                             │
│         │                                                     │
│  ┌──────▼───────┐                                             │
│  │ AudioPlayback│                                             │
│  │ Coordinator  │                                             │
│  └──────────────┘                                             │
└───────────────────────────────────────────────────────────────┬─┘
                        │ WebSocket (ws_ui)                      │
                        ▼                                        │
┌─────────────────────────────────────────────────────────────┐ │
│                    Web UI (Browser)                         │ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │ │
│  │ ASR Display  │  │ Image Viewer │  │ AI Response  │       │ │
│  │ (Real-time)  │  │ (Captured)   │  │ (Text+Audio) │       │ │
│  └──────────────┘  └──────────────┘  └──────────────┘       │ │
└─────────────────────────────────────────────────────────────┘ │
                        │ HTTP API (history, health)             │
                        └────────────────────────────────────────┘
```

### Component Overview

| Component | Technology | Purpose | Mode |
|-----------|-----------|---------|------|
| **ESP32 Device** | ESP32-S3 + I2S Mic + ESP32-CAM | Audio/image capture and streaming | Both |
| **Backend Server** | FastAPI + Python 3.8+ | WebSocket gateway, event coordination | Both |
| **OmniCoordinator** | Python + websockets | Unified audio+vision+TTS stream handling | Omni only |
| **OmniStreamAdapter** | Python + DashScope SDK | Single WebSocket to Qwen Omni Realtime | Omni only |
| **AppCoordinator** | Python + asyncio | Full batch pipeline orchestration | Batch only |
| **AudioPlaybackCoordinator** | Python + asyncio | ESP32 audio streaming with chunking/pacing | Both |
| **Web UI** | HTML5 + JavaScript + WebSocket | Real-time monitoring dashboard with live stream indicator | Both |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** installed
- **Git** installed
- **AWS EC2 instance** (Ubuntu 20.04+ recommended) or local machine
- **DashScope API Key** (required for Omni mode; also used for ASR/Vision/TTS in batch mode)
- **ESP32-S3 device** with microphone and camera (optional for testing)

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
# Omni Realtime Mode Configuration
OMNI_MODE=true                          # Set to false for batch mode fallback
OMNI_MODEL=qwen3.5-omni-plus-realtime
OMNI_VOICE=Cherry
OMNI_INSTRUCTIONS=你是一個配戴在眼鏡上的智能助手。用繁體中文回答，語句簡短自然。
OMNI_VAD_THRESHOLD=0.5                  # Higher (0.6-0.7) for noisy environments
OMNI_VAD_SILENCE_MS=800                 # Silence duration to detect speech end
OMNI_ENABLE_SEARCH=false                # Enable web search (Phase 3)
OMNI_ENABLE_TRANSCRIPTION=true          # Enable user transcription in responses
OMNI_SESSION_REFRESH_MIN=110            # Refresh session before 120-min limit

# Required API key (DashScope - used for all modes)
ASR_API_KEY=your_dashscope_api_key_here

# Optional API keys (only used when OMNI_MODE=false)
VISION_API_KEY=your_vision_api_key_here
TTS_API_KEY=your_tts_api_key_here

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
LOG_LEVEL=INFO

# Endpoints (auto-selected based on mode)
ASR_ENDPOINT=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
VISION_ENDPOINT=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
TTS_ENDPOINT=wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime
```

### 3️⃣ Start Backend Server

```bash
# Development mode (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8080
```

Server will start at: `http://localhost:8080`

**Expected startup logs:**
```
INFO:     Uvicorn running on http://0.0.0.0:8080
INFO:     ═══ OMNI MODE ENABLED ═══ Using OmniCoordinator
INFO:     Omni WS connected to wss://dashscope-intl.aliyuncs.com/...
INFO:     Omni session created: <session_id>
```

### 4️⃣ Access Web UI

Open your browser and navigate to:
- **Local**: `http://localhost:8080/web/index.html`
- **AWS EC2**: `http://your-ec2-public-ip:8080/web/index.html`

**Expected UI indicators:**
- Connection badge: 🟢 "已連線" (Connected)
- Camera chip: "Live Stream" with pulsing green indicator (Omni mode)
- Pipeline stages: ASR and TTS light up during conversation

### 5️⃣ Configure ESP32 (Optional)

Update the firmware configuration in `device/esp32_s3_smooth_v3-6-4.ino`:

```cpp
// WiFi Configuration
const char* WIFI_SSID = "your-wifi-ssid";
const char* WIFI_PASSWORD = "your-wifi-password";

// WebSocket Server Configuration
const char* WS_HOST = "your-ec2-public-ip";  // or "localhost" for local testing
const int WS_PORT = 8080;
const bool USE_SSL = false;  // Set to true for production with SSL

// Camera Configuration (Phase 2)
#define CAMERA_STREAM_INTERVAL_MS  1000   // 1 FPS for Omni mode
#define CAMERA_STREAM_MAX_BYTES    (80*1024)  // 80KB budget for QVGA JPEG
```

Flash the firmware to your ESP32-S3 device using Arduino IDE or PlatformIO.

---

## ☁️ AWS EC2 Deployment

### Step 1: Launch EC2 Instance

1. **Choose AMI**: 
   - Amazon Linux 2023 (latest, recommended)
   - Ubuntu Server 22.04 LTS
2. **Instance Type**: t2.micro (free tier) or t3.small (recommended for better performance)
3. **Storage**: 16GB minimum (8GB for OS + app, 8GB for logs/images)
4. **Key Pair**: Create or use existing SSH key pair

### Step 2: Configure Security Group

Open the following ports in your EC2 security group:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH access |
| 8080 | TCP | 0.0.0.0/0 | Backend API & WebSocket |
| 80 | TCP | 0.0.0.0/0 | HTTP (optional, for Nginx) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (optional, for SSL) |

### Step 3: Connect to EC2

```bash
ssh -i your-key.pem ubuntu@your-ec2-public-ip
```

### Step 4: Install Dependencies

**For Ubuntu 22.04:**
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.10+ and pip
sudo apt install python3 python3-pip python3-venv git -y

# Install additional tools
sudo apt install htop curl wget -y

# Verify Python version
python3 --version  # Should be 3.10 or higher
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
nano .env  # Add your API keys and set OMNI_MODE=true
```

### Step 6: Run as Background Service

#### Option A: Using `nohup` (Quick & Simple)

```bash
# Start server in background
nohup uvicorn main:app --host 0.0.0.0 --port 8080 > server.log 2>&1 &

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
Description=ESP32 ASR Capture Vision Backend (Phase 2)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/EE3070-Design-Project/backend
Environment="PATH=/home/ubuntu/EE3070-Design-Project/backend/venv/bin"
Environment="OMNI_MODE=true"
ExecStart=/home/ubuntu/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**For Amazon Linux 2023:**
```ini
[Unit]
Description=ESP32 ASR Capture Vision Backend (Phase 2)
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/EE3070-Design-Project/backend
Environment="PATH=/home/ec2-user/EE3070-Design-Project/backend/venv/bin"
Environment="OMNI_MODE=true"
ExecStart=/home/ec2-user/EE3070-Design-Project/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
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
curl http://localhost:8080/api/health

# Expected response:
# {"status":"healthy","esp32_audio_connected":false,"esp32_camera_connected":false,"web_ui_connected":false,...}

# Check Omni status (only in Omni mode)
curl http://localhost:8080/api/omni_status

# Expected response (if Omni mode active):
# {"session_id":"...","state":"connected","last_response_latency_ms":245,...}
```

Access from browser: `http://your-ec2-public-ip:8080/web/index.html`

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
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket timeout settings
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
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
│   ├── 📄 main.py                 # FastAPI entry point with dual-mode routing
│   ├── 📄 omni_coordinator.py     # NEW: Omni mode coordinator (audio+vision+TTS)
│   ├── 📄 omni_stream_adapter.py  # NEW: Qwen Omni Realtime WebSocket adapter
│   ├── 📄 app_coordinator.py      # Legacy: Batch mode coordinator
│   ├── 📄 event_bus.py            # Event distribution system
│   ├── 📄 asr_bridge.py           # Legacy: ASR service integration
│   ├── 📄 trigger_engine.py       # Legacy: Keyword detection & trigger logic
│   ├── 📄 capture_coordinator.py  # Legacy: Image capture coordination
│   ├── 📄 vision_adapter.py       # Legacy: Vision model integration
│   ├── 📄 tts_adapter.py          # Legacy: TTS service integration
│   ├── 📄 audio_playback_coordinator.py  # Audio streaming to ESP32 (reused)
│   ├── 📄 models.py               # Data models (Pydantic)
│   ├── 📄 config.py               # Configuration management with Omni settings
│   ├── 📄 requirements.txt        # Python dependencies
│   ├── 📄 .env.example            # Environment variables template
│   └── 📄 __init__.py
├── 📂 web/                        # Web UI frontend (Phase 2 updated)
│   ├── 📄 index.html              # Main HTML with live stream indicator
│   ├── 📄 style.css               # Styling with stream-status animations
│   ├── 📄 app.js                  # Frontend JS with camera_stream event handling
│   ├── 📄 manifest.json           # PWA manifest (v2.1.0)
│   └── 📄 sw.js                   # Service worker (cache-first statics)
├── 📂 device/                     # ESP32 firmware (Phase 2 updated)
│   ├── 📄 esp32_s3_smooth_v3-6-4.ino  # Complete firmware with cameraStreamTask
│   ├── 📄 esp32_camera_test.ino       # Camera testing firmware
│   └── 📄 esp32_simulator.py          # Python ESP32 simulator
├── 📂 tests/                      # Unit tests
│   ├── 📄 conftest.py             # Pytest configuration
│   ├── 📄 test_models.py          # Model tests
│   └── 📄 __init__.py
├── 📂 .kiro/specs/                # Project specifications
│   └── 📂 esp32-asr-capture-vision-mvp/
│       ├── 📄 requirements.md     # Requirements document
│       ├── 📄 design.md           # Design document
│       └── 📄 tasks.md            # Implementation tasks
├── 📄 README.md                   # This file (Phase 2)
├── 📄 QUICKSTART.md               # Quick start guide
├── 📄 DEPLOYMENT.md               # Deployment guide
├── 📄 API.md                      # API documentation
├── 📄 TESTING.md                  # Testing guide
├── 📄 PHASE1_MIGRATION_GUIDE.md   # Phase 1 migration instructions
├── 📄 OMNI_MIGRATION_ARCHITECTURE.md  # Full Omni migration architecture
├── 📄 pytest.ini                  # Pytest configuration
└── 📄 .gitignore                  # Git ignore rules
```

---

## 🔌 API Endpoints

### HTTP REST API

| Method | Endpoint | Description | Response | Mode |
|--------|----------|-------------|----------|------|
| `GET` | `/` | Health check | `{"status": "ok"}` | Both |
| `GET` | `/api/health` | System health status | `{"status": "healthy", "esp32_audio_connected": bool, ...}` | Both |
| `GET` | `/api/omni_status` | Omni session stats | `{"session_id": "...", "state": "connected", ...}` | Omni only |
| `GET` | `/api/history?limit=20` | Get recent events | `[{event}, ...]` | Both |
| `GET` | `/api/images` | List captured images | `["img1.jpg", ...]` | Both |
| `POST` | `/api/upload` | Upload test image | `{"status": "ok", "filename": "..."}` | Both |

### WebSocket Endpoints

| Endpoint | Direction | Purpose | Data Format | Mode |
|----------|-----------|---------|-------------|------|
| `/ws_audio` | ESP32 ↔ Server | Audio streaming + control | Binary (PCM16) + JSON control | Both |
| `/ws_ctrl` | Server → ESP32 | Control commands (batch) | JSON: `{"type": "CAPTURE", ...}` | Batch only |
| `/ws_camera` | ESP32 → Server | Image upload | Binary (JPEG) + JSON header (batch) / Binary only (Omni) | Both |
| `/ws_ui` | Server → Browser | Event notifications | JSON: `{"event_type": "...", "data": {...}}` | Both |

### WebSocket Event Types (Web UI)

**From Server to UI** (`/ws_ui`):

```json
// ASR Events (both modes)
{
  "event_type": "asr_partial",
  "data": {"text": "請你幫我...", "timestamp": 1712851234.567}
}

{
  "event_type": "asr_final",
  "data": {"text": "請你幫我識別物品", "timestamp": 1712851234.890}
}

// Trigger Events (batch mode only)
{
  "event_type": "trigger_fired",
  "data": {"req_id": "abc123", "trigger_text": "識別物品", "matched_keyword": "help me recognize"}
}

// Camera Events
{
  "event_type": "capture_received",  // Batch mode
  "data": {"req_id": "abc123", "filename": "abc123.jpg", "image_size": 45210}
}

{
  "event_type": "camera_stream_started",  // Phase 2 Omni mode
  "data": {"fps": 1, "resolution": "320x240", "device_id": "default"}
}

{
  "event_type": "camera_frame_received",  // Phase 2 Omni mode
  "data": {"filename": "stream_1712851234.jpg", "image_size": 10240}
}

// Vision/TTS Events
{
  "event_type": "vision_result",
  "data": {"req_id": "abc123", "text": "前方有一個白色馬克杯。", "confidence": 0.92}
}

{
  "event_type": "tts_started",
  "data": {"text": "前方有一個白色馬克杯。", "timestamp": 1712851235.123}
}

// Error Events
{
  "event_type": "error",
  "data": {"error_type": "capture_timeout", "message": "相機逾時，請重試"}
}
```

---

## 🎯 Trigger Keywords & Questions

### Omni Mode (Phase 2 - Default)
**No trigger keywords required!** The system uses continuous Server-side VAD for natural conversation:

- Simply speak naturally: "前面是什麼？" → AI responds immediately
- Interrupt anytime: Speak while AI is responding → AI stops and listens (barge-in)
- Ask follow-ups: "那個是什麼顏色？" → AI uses visual context from continuous stream

**Voice Questions (still recognized for compatibility):**
- English: "describe the view", "what do I see", "what's in front of me", "tell me what you see"
- Chinese: "描述一下景象", "我看到什麼", "前面是什麼", "告訴我你看到什麼"

### Batch Mode (Fallback - OMNI_MODE=false)
**Trigger Keywords** (required to initiate capture):

| Trigger Phrase | Pinyin | English Translation |
|----------------|--------|---------------------|
| 識別物品 | shí bié wù pǐn | Identify object |
| 認下呢個係咩 | rèn xià nǐ gè xì miē | Recognize what this is |
| 幫我認 | bāng wǒ rèn | Help me recognize |
| 睇下呢個 | dì xià nǐ gè | Look at this |

**Voice Questions** (trigger capture + AI analysis + spoken response):

| English | Chinese | Pinyin |
|---------|---------|--------|
| describe the view | 描述一下景象 | miáo shù yī xià jǐng xiàng |
| what do I see | 我看到什麼 | wǒ kàn dào shén me |
| what's in front of me | 前面是什麼 | qián miàn shì shén me |
| tell me what you see | 告訴我你看到什麼 | gào sù wǒ nǐ kàn dào shén me |

**Cooldown**: 3 seconds between triggers (batch mode only) to prevent duplicate captures.

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
python device/esp32_simulator.py --host localhost --port 8080 --mode omni
```

### Test Image Upload

```bash
# Upload a test image
python test_upload.py --image path/to/image.jpg --host localhost --port 8080
```

### Phase 2 Testing Checklist

#### Omni Mode Tests
- [ ] Backend starts with `OMNI_MODE=true` and logs "Omni WS connected"
- [ ] Web UI shows "Live Stream" indicator with pulsing green dot
- [ ] Speaking naturally triggers AI response within <2 seconds
- [ ] Interrupting AI mid-response stops playback immediately (barge-in)
- [ ] Camera frames update snapshot every ~1 second
- [ ] `/api/omni_status` returns session stats with low latency (<800ms)
- [ ] Session auto-refreshes at 110 minutes (test by setting `OMNI_SESSION_REFRESH_MIN=2`)

#### Batch Mode Tests (Fallback)
- [ ] Set `OMNI_MODE=false` and restart backend
- [ ] Web UI shows "Camera" chip (not "Live Stream")
- [ ] Trigger keyword detection works with Chinese phrases
- [ ] On-demand image capture and upload successful
- [ ] Vision model returns object description
- [ ] TTS converts description to speech and plays through ESP32

#### Cross-Mode Tests
- [ ] Switching `OMNI_MODE` flag and restarting switches pipelines seamlessly
- [ ] Web UI adapts to mode changes without code changes
- [ ] Error handling gracefully falls back to batch mode if Omni fails

### Manual Testing Checklist

- [ ] Backend starts without errors in selected mode
- [ ] Web UI loads and connects via WebSocket
- [ ] ASR transcription appears in real-time (Omni) or after trigger (batch)
- [ ] Camera streaming indicator shows correct state
- [ ] AI responses are spoken through ESP32 speaker
- [ ] Barge-in works: speak during response → response stops immediately
- [ ] Auto-reconnection works after disconnect
- [ ] Session refresh works without dropping connection

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
# Omni Realtime Mode Configuration
OMNI_MODE=true
OMNI_MODEL=qwen3.5-omni-plus-realtime
OMNI_VOICE=Cherry
OMNI_INSTRUCTIONS=你是一個配戴在眼鏡上的智能助手。用繁體中文回答，語句簡短自然。
OMNI_VAD_THRESHOLD=0.5
OMNI_VAD_SILENCE_MS=800
OMNI_ENABLE_SEARCH=false
OMNI_ENABLE_TRANSCRIPTION=true
OMNI_SESSION_REFRESH_MIN=110

# Required API key (DashScope - used for all modes)
ASR_API_KEY=sk-xxxxx

# Optional API keys (only used when OMNI_MODE=false)
VISION_API_KEY=sk-xxxxx
TTS_API_KEY=sk-xxxxx

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
LOG_LEVEL=INFO
```

### Adding New Event Types

To add a new event type for the Web UI:

1. Add to `models.py` EventType enum:
```python
class EventType(str, Enum):
    # ... existing ...
    CAMERA_STREAM_STARTED = "camera_stream_started"  # Example
```

2. Add case to `app.js` `handleEvent()` switch:
```javascript
case 'camera_stream_started':
  store.cameraStreaming = true;
  store.cameraFps = ev.data.fps || 1;
  appendLog('CAMERA', `Stream started @ ${store.cameraFps} FPS`, ev.timestamp);
  break;
```

3. Update `render()` function if UI changes needed:
```javascript
// In render() function
const streamStatus = $('streamStatus');
if (streamStatus && s.cameraStreaming) {
  streamStatus.style.display = 'flex';
  // ... update UI elements
}
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

**Problem**: `Port 8080 already in use`

**Solution**:
```bash
# Find process using port 8080
lsof -i :8080  # Linux/Mac
netstat -ano | findstr :8080  # Windows

# Kill the process
kill -9 <PID>  # Linux/Mac
taskkill /PID <PID> /F  # Windows
```

### Omni Mode Connection Issues

**Problem**: "Omni WS connection failed" in logs

**Solution**:
1. Verify `ASR_API_KEY` is valid and has Omni Realtime access
2. Check network connectivity to `dashscope-intl.aliyuncs.com`
3. Ensure `OMNI_MODEL` value is correct and available in your region
4. Check DashScope console for API quota/limits

**Problem**: High latency (>3s) in Omni responses

**Solution**:
1. Check `/api/omni_status` for `last_response_latency_ms`
2. Try switching to CN endpoint if in mainland China
3. Reduce `OMNI_VAD_THRESHOLD` if VAD is too sensitive
4. Check ESP32 WiFi signal strength and reduce camera quality if needed

### Camera Streaming Issues

**Problem**: "Live Stream" indicator not showing

**Solution**:
1. Verify ESP32 firmware has `cameraStreamTask` enabled
2. Check `/ws_camera` WebSocket connection in browser DevTools
3. Ensure `OMNI_MODE=true` and backend is using `OmniCoordinator`
4. Check backend logs for `camera_stream_started` event publication

**Problem**: Camera frames not updating snapshot

**Solution**:
1. Verify `camera_frame_received` events are being published
2. Check browser Console for JavaScript errors in `app.js`
3. Ensure snapshot image URL includes cache-busting timestamp
4. Verify ESP32 camera initialization with `CAMERA_GRAB_LATEST`

### Web UI Issues

**Problem**: UI shows "Disconnected"

**Solution**:
1. Verify backend is running: `curl http://localhost:8080/api/health`
2. Check browser console for errors (F12)
3. Ensure WebSocket URL is correct in `app.js`
4. Verify security group allows port 8080 on EC2

**Problem**: No ASR transcription appearing

**Solution**:
1. Verify `ASR_API_KEY` is set correctly
2. Check backend logs for ASR/Omni errors
3. Ensure ESP32 is streaming audio (check Serial Monitor)
4. In Omni mode, ensure Server VAD is detecting speech (adjust `OMNI_VAD_THRESHOLD`)

### AWS EC2 Specific

**Problem**: Can't access EC2 from browser

**Solution**:
1. Check security group allows inbound on port 8080
2. Verify server is listening on `0.0.0.0` not `127.0.0.1`
3. Use public IP, not private IP
4. Check Nginx configuration if using reverse proxy

**Problem**: Server stops after SSH disconnect

**Solution**:
Use `nohup` or `systemd` service (see deployment section)

---

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Quick start guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Detailed deployment instructions
- **[API.md](API.md)** - Complete API reference
- **[TESTING.md](TESTING.md)** - Testing guide
- **[PHASE1_MIGRATION_GUIDE.md](PHASE1_MIGRATION_GUIDE.md)** - Phase 1 migration instructions
- **[OMNI_MIGRATION_ARCHITECTURE.md](OMNI_MIGRATION_ARCHITECTURE.md)** - Full Omni migration architecture
- **[TTS_TRUNCATION_FIX.md](TTS_TRUNCATION_FIX.md)** - TTS audio truncation fixes
- **[MIC_AUDIO_FIX.md](MIC_AUDIO_FIX.md)** - Microphone audio quality fixes

---

## 🔄 Migration Guide: Batch → Omni (Phase 2)

### Step 1: Update Environment
```bash
# Edit .env
OMNI_MODE=true
OMNI_MODEL=qwen3.5-omni-plus-realtime
# Keep ASR_API_KEY (used for Omni authentication)
```

### Step 2: Update Backend
```bash
# No code changes needed! Dual-mode routing is already in main.py
# Just restart the server:
pkill -f uvicorn
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Step 3: Update ESP32 Firmware
```cpp
// In esp32_s3_smooth_v3-6-4.ino:
// 1. Ensure cameraStreamTask is enabled (already in Phase 2 firmware)
// 2. Ensure stop_playback handler is added to wsAudio.onMessage
// 3. Flash updated firmware to ESP32
```

### Step 4: Verify
```bash
# Check backend logs for:
# "═══ OMNI MODE ENABLED ═══ Using OmniCoordinator"
# "Omni WS connected to wss://dashscope-intl.aliyuncs.com/..."

# Check Web UI for:
# - "Live Stream" indicator with pulsing green dot
# - Sub-2s response latency
# - Barge-in functionality
```

### Rollback (If Needed)
```bash
# Edit .env
OMNI_MODE=false

# Restart backend
pkill -f uvicorn
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# System returns to full batch pipeline with no code changes
```

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
- For Omni-related changes, ensure backward compatibility with batch mode

---

## 🙏 Acknowledgments

- **Alibaba Cloud** - DashScope API for Qwen Omni Realtime and legacy models
- **Qwen Team** - Qwen3.5-Omni-Plus-Realtime unified model
- **FastAPI** - Modern web framework for Python
- **ESP32 Community** - Hardware and firmware support
- **Open Source Community** - WebSocket libraries, Pydantic, and more

---

## 📞 Support

For issues, questions, or suggestions:

- **GitHub Issues**: [Create an issue](https://github.com/Lokch777/EE3070-Design-Project/issues)
- **Documentation**: Check the `docs/` folder and markdown guides in root
- **Phase 2 Specific**: See `OMNI_MIGRATION_ARCHITECTURE.md` for detailed architecture

---

<div align="center">

**Made with ❤️ for EE3070 Design Project - Phase 2**

⭐ Star this repo if you find it helpful!

🔄 **Dual-Mode Architecture**: Omni mode for cutting-edge performance, batch mode for reliable fallback

</div>
