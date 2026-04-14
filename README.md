# 🎙️ ESP32 ASR Capture Vision MVP + Real-Time AI Assistant

<div align="center">

![ESP32](https://img.shields.io/badge/ESP32--S3-CAM-blue?style=for-the-badge&logo=espressif)
![Python](https://img.shields.io/badge/Python-3.10+-green?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal?style=for-the-badge&logo=fastapi)
![Version](https://img.shields.io/badge/Version-3.0.0-orange?style=for-the-badge)
![Phase](https://img.shields.io/badge/Phase-3%20Omni%20Realtime-purple?style=for-the-badge)

**Continuous Multimodal AI Assistant — Omni Realtime · Edge AI**

A real-time IoT system that streams audio and camera frames continuously from an ESP32-S3 to a FastAPI backend, then bridges to the **Qwen Omni Realtime API** (`qwen3.5-omni-plus-realtime`) for low-latency, always-on audio + vision responses — designed as an assistive technology for visually impaired users.

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-system-architecture) • [Deployment](#-aws-ec2-deployment) • [Documentation](#-documentation)

</div>

---

## 📖 Project Overview

### Phase History

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Drop-in `OmniCoordinator` alongside batch pipeline; `OMNI_MODE` env flag toggle | ✅ Complete |
| **Phase 2** | Full audio duplex + continuous QVGA camera streaming | ✅ Complete |
| **Phase 3** | Full Omni production migration — batch pipeline removed, firmware cleaned, frontend v3.0.0 | ✅ **Current** |

### Objectives

This project implements an **always-on continuous multimodal AI assistant** designed for wearable devices (smart glasses) or IoT applications. The system enables hands-free interaction where users can speak naturally while the ESP32-S3 simultaneously streams audio and camera frames to a real-time AI model.

**Primary Goals:**

1. **Continuous Audio + Vision Streaming**: Duplex audio (16kHz PCM) and QVGA camera frames (1 FPS JPEG) streamed simultaneously from ESP32-S3
2. **Omni Realtime AI**: `qwen3.5-omni-plus-realtime` processes audio and vision jointly with low latency
3. **Spoken Responses**: AI audio responses streamed back to ESP32-S3 and played via I2S speaker
4. **Degraded Mode Resilience**: Automatic 5× exponential-backoff retry with 30-second recovery loop
5. **Real-Time Dashboard**: Web UI v3.0.0 showing Omni metrics, degraded mode banner, and system events
6. **Security First**: API keys exclusively on the backend; web search hardcoded OFF at three layers

**Target Use Cases:**

- 🕶️ **Smart Glasses for Visually Impaired**: Hear continuous AI descriptions of the environment in real time
- 🏭 **Industrial IoT**: Hands-free equipment inspection with always-on visual awareness
- 🏥 **Healthcare**: Medical device identification and medication verification with spoken feedback
- 🎓 **Education**: Interactive learning tools for real-time object recognition
- 🏠 **Smart Home**: Voice-controlled home automation with visual context

### Design Philosophy

```
┌─────────────────────────────────────────────────────────────┐
│                     Design Principles                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Modularity      │ Independent components with clear APIs │
│ 2. Scalability     │ Event bus enables easy feature addition│
│ 3. Reliability     │ Degraded mode + exponential backoff    │
│ 4. Real-Time       │ WebSocket duplex — no polling          │
│ 5. Security        │ Zero-trust: API keys only on backend   │
│ 6. Testability     │ Property-based testing for correctness │
│ 7. Accessibility   │ Audio feedback for visually impaired   │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions (Phase 3):**

- **Omni Realtime WS**: Single persistent WebSocket to Dashscope replaces the five-step batch pipeline
- **No Web Search**: `enable_search` removed from session payload entirely — never sent to Dashscope
- **Degraded Mode**: On WS exhaustion, audio is silently dropped; no batch fallback; UI shows amber banner
- **QVGA @ 1 FPS**: 320×240 JPEG ~10KB — within Omni API's ≤500KB / ≤1 FPS image cap
- **Ring Buffer**: Memory-efficient event history (last 100 events) for debugging and UI display
- **Audio Buffering**: 16KB ring buffer on ESP32 for smooth I2S playback

### System Workflow (Phase 3 — Omni Realtime)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Complete System Flow (v3.0.0)                 │
└─────────────────────────────────────────────────────────────────┘

1. 🎤 CONTINUOUS AUDIO STREAM
   └─> ESP32-S3 streams PCM16 audio (16kHz mono) via WebSocket
       └─> OmniStreamAdapter forwards frames to Qwen Omni Realtime WS
           └─> Omni API processes audio with barge-in VAD

2. 📷 CONTINUOUS CAMERA STREAM
   └─> ESP32-S3 sends QVGA JPEG (~10KB) @ 1 FPS
       └─> OmniStreamAdapter includes frames in Omni session
           └─> Omni API sees live visual context alongside audio

3. 🤖 OMNI REALTIME RESPONSE
   └─> Omni API generates audio + text response jointly
       └─> OmniCoordinator receives audio chunks
           └─> Streams PCM16 audio back to ESP32-S3 speaker
               └─> Publishes vision_result / asr_final events to dashboard

4. 📊 DASHBOARD UPDATE
   └─> Web UI (v3.0.0) receives events via /ws_ui
       └─> Displays: ASR transcript → Vision result → TTS status
           └─> Omni metrics: latency, audio bytes, images sent, error count

5. 🛡️ DEGRADED MODE (if Omni WS fails)
   └─> 5× exponential backoff + jitter retries
       └─> On exhaustion → SYSTEM_DEGRADED event → amber banner on UI
           └─> Recovery loop retries every 30s
               └─> On success → SYSTEM_RECOVERED → banner clears
```

### Technical Specifications

| Component | Specification | Rationale |
|-----------|--------------|-----------|
| **Hardware** | ESP32-S3 with I2S mic + OV camera | PSRAM supports QVGA buffer + audio ring buffer |
| **Audio Format** | PCM16, 16kHz, Mono | Standard for Omni API realtime audio |
| **Image Format** | JPEG QVGA 320×240, ~10KB @ 1 FPS | Within Omni ≤500KB / ≤1 FPS cap |
| **AI Model** | `qwen3.5-omni-plus-realtime` (Dashscope) | Joint audio + vision realtime model |
| **Web Search** | **Hardcoded OFF** (3 layers) | Session payload never includes search block |
| **Duplex Bandwidth** | ~620 kbps (QVGA + 16kHz audio) | Well within 2–4 Mbps WiFi headroom |
| **Session Refresh** | Configurable (default 30 min) | Prevents Omni WS timeout on long sessions |
| **Degraded Retries** | 5× exponential backoff + jitter | Robust recovery without hammering API |
| **Recovery Loop** | Every 30 seconds | Auto-heals after transient API outages |
| **LED Indicator** | GPIO 48 (off / solid / fast-blink) | Visual feedback: idle / processing / error |
| **Event Buffer** | 100 events (ring buffer) | Balances memory and debugging capability |
| **Audio Buffer** | 16KB ring buffer on ESP32 | Smooth I2S playback without stuttering |

---

## 🌟 Features

- **🎤 Continuous Audio Streaming**: ESP32-S3 streams PCM16 audio (16kHz mono) in full duplex via WebSocket
- **📷 Continuous Camera Streaming**: QVGA JPEG @ 1 FPS sent alongside audio to Omni API for joint multimodal context
- **🤖 Qwen Omni Realtime**: `qwen3.5-omni-plus-realtime` replaces the entire batch pipeline with a single always-on WS session
- **🔊 Spoken Responses**: AI-generated audio streamed back to ESP32-S3 and played via I2S speaker
- **🛡️ Degraded Mode**: 5× exponential backoff retries → amber banner in UI → 30s auto-recovery loop
- **💡 LED State Indicator**: GPIO 48 — off (idle), solid ON (processing), fast blink (error)
- **🌐 Web Dashboard v3.0.0**: Pipeline: ASR → Vision → TTS; Omni metrics; degraded mode banner; dark/light mode
- **🔄 Auto-Reconnection**: Robust WS management with jitter-based exponential backoff
- **🔒 Secure API Management**: All API keys on backend only; web search disabled at three code layers
- **⚡ Low Latency**: Continuous session eliminates per-request cold start overhead
- **☁️ Cloud-Ready**: Designed for AWS EC2 deployment

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ESP32-S3 Device                          │
│  ┌──────────────┐              ┌──────────────┐  ┌──────────┐  │
│  │ I2S Mic      │              │ OV Camera    │  │ LED      │  │
│  │ (16kHz PCM)  │              │ (QVGA JPEG)  │  │ GPIO 48  │  │
│  └──────┬───────┘              └──────┬───────┘  └──────────┘  │
│         └─────────────┬───────────────┘                         │
└───────────────────────┼─────────────────────────────────────────┘
                        │ WebSocket (/ws_audio, /ws_camera)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AWS EC2 Backend (FastAPI)                    │
│  ┌──────────────────┐     ┌────────────────────────────────┐   │
│  │  OmniCoordinator │────►│  OmniStreamAdapter             │   │
│  │  (session mgr,   │     │  (Dashscope Realtime WS bridge)│   │
│  │   degraded mode) │◄────│                                │   │
│  └────────┬─────────┘     └────────────────────────────────┘   │
│           │ publishes events                                     │
│  ┌────────▼─────────┐     ┌──────────────┐                     │
│  │  Event Bus       │────►│  /health     │ (status, latency,   │
│  │  (asyncio queue) │     │  /ws_ui      │  audio bytes, etc.) │
│  └──────────────────┘     └──────────────┘                     │
└───────────────────────────────────────────────────────────────┬─┘
                        │ WebSocket (/ws_ui)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Web UI v3.0.0 (Browser)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ASR Display  │  │ Vision Result│  │ Degraded Mode Banner │  │
│  │ (Real-time)  │  │ (Omni)       │  │ (amber, dismissible) │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Overview (Phase 3)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **ESP32-S3 Device** | ESP32-S3 + I2S Mic + OV Camera + GPIO 48 LED | Audio/camera streaming, audio playback, LED status |
| **OmniCoordinator** | Python (rewritten Phase 3) | Manages Omni session lifecycle + degraded mode |
| **OmniConfig** | Python (rewritten Phase 3) | Config with `enable_search=False` hardcoded |
| **OmniStreamAdapter** | Python (unchanged from Phase 2) | Dashscope Realtime WS bridge |
| **Backend Server** | FastAPI + Python 3.10+ | WS gateway, event coordination, health endpoint |
| **AI Model** | `qwen3.5-omni-plus-realtime` (Dashscope) | Joint audio + vision realtime model |
| **Web UI** | HTML5 + JS + WebSocket (v3.0.0) | Real-time monitoring dashboard |

### Degraded Mode Behaviour

| Situation | Behaviour |
|-----------|-----------|
| Initial connect fails | Enter degraded mode immediately, keep retrying |
| Omni WS dies mid-session | 5× retries with exponential backoff + jitter |
| All retries exhausted | `SYSTEM_DEGRADED` event → UI shows amber banner |
| Audio during degraded mode | **Silently dropped** — no batch pipeline fallback |
| Recovery (every 30s) | On success → `SYSTEM_RECOVERED` → banner clears |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** installed
- **Git** installed
- **AWS EC2 instance** (Ubuntu 20.04+ recommended) or local machine
- **DashScope API Key** (for Qwen Omni Realtime model)
- **ESP32-S3 device** with I2S microphone, OV camera, and speaker (optional for testing)

### 1️⃣ Clone Repository

```bash
git clone https://github.com/Lokch777/EE3070-Design-Project.git
cd EE3070-Design-Project
```

### 2️⃣ Backend Setup

```bash
cd backend

python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
nano .env   # Add your API key and Omni settings
```

**Required Environment Variables** (`.env` file):

```env
# Dashscope API Key
DASHSCOPE_API_KEY=your_dashscope_api_key_here

# Omni Realtime Configuration
OMNI_MODEL=qwen3.5-omni-plus-realtime
OMNI_VOICE=default
OMNI_VAD_THRESHOLD=0.5
OMNI_VAD_SILENCE_MS=600
OMNI_SESSION_REFRESH_MIN=30
OMNI_ENABLE_TRANSCRIPTION=true

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# Note: OMNI_MODE is always ON in Phase 3 — batch pipeline removed.
# Note: Web search is hardcoded OFF and cannot be enabled via .env.
```

### 3️⃣ Start Backend Server

```bash
# Development mode (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000
```

Mount the web frontend (already wired in `main.py`):

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="web", html=True), name="web")
```

### 4️⃣ Access Web UI (v3.0.0)

- **Local**: `http://localhost:8000`
- **AWS EC2**: `http://your-ec2-public-ip:8000`

### 5️⃣ Configure ESP32-S3 (Optional)

Update firmware in `device/esp32_full_firmware.ino`:

```cpp
// WiFi Configuration
const char* WIFI_SSID     = "your-wifi-ssid";
const char* WIFI_PASSWORD = "your-wifi-password";

// WebSocket Server Configuration
const char* WS_HOST = "your-ec2-public-ip";
const int   WS_PORT = 8000;
const bool  USE_SSL = false;  // Set true for production SSL
```

Flash the firmware using Arduino IDE or ESP-IDF.

---

## ☁️ AWS EC2 Deployment

### Step 1: Launch EC2 Instance

1. **Choose AMI**: Ubuntu Server 22.04 LTS (recommended), Amazon Linux 2023, or Amazon Linux 2
2. **Instance Type**: t2.micro (free tier) or t2.small (recommended)
3. **Storage**: 16GB recommended
4. **Key Pair**: Create or use existing SSH key pair

### Step 2: Configure Security Group

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH access |
| 8000 | TCP | 0.0.0.0/0 | Backend API & WebSocket |
| 80 | TCP | 0.0.0.0/0 | HTTP (optional, for Nginx) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (optional, for SSL) |

### Step 3: Connect and Install

```bash
ssh -i your-key.pem ubuntu@your-ec2-public-ip

# Ubuntu 22.04
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git htop curl wget -y
python3 --version   # Should be 3.10+
```

### Step 4: Deploy Application

```bash
git clone https://github.com/Lokch777/EE3070-Design-Project.git
cd EE3070-Design-Project/backend

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
nano .env   # Add your DASHSCOPE_API_KEY
```

### Step 5: Run as Background Service (systemd — Recommended)

```bash
sudo nano /etc/systemd/system/esp32-asr.service
```

```ini
[Unit]
Description=ESP32 ASR Capture Vision Backend (Phase 3 Omni)
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

```bash
sudo systemctl daemon-reload
sudo systemctl enable esp32-asr
sudo systemctl start esp32-asr
sudo systemctl status esp32-asr
sudo journalctl -u esp32-asr -f   # Live logs
```

### Step 6: Verify Deployment

```bash
curl http://localhost:8000/health
# Expected:
# {"status":"healthy","session_id":"xxx","uptime_seconds":...,"last_latency_ms":...}
```

### Step 7: (Optional) Nginx Reverse Proxy

```bash
sudo apt install nginx -y
sudo nano /etc/nginx/sites-available/esp32-asr
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/esp32-asr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 📁 Project Structure

```
EE3070-Design-Project/
├── 📂 backend/                      # Python backend server
│   ├── 📄 main.py                  # FastAPI entry point
│   ├── 📄 omni_coordinator.py      # ★ Rewritten Phase 3 — session mgr + degraded mode
│   ├── 📄 omni_config.py           # ★ Rewritten Phase 3 — enable_search=False hardcoded
│   ├── 📄 omni_stream_adapter.py   # Dashscope Realtime WS adapter (unchanged)
│   ├── 📄 event_bus.py             # Event distribution system
│   ├── 📄 models.py                # Data models (Pydantic)
│   ├── 📄 config.py                # Configuration management
│   ├── 📄 requirements.txt         # Python dependencies
│   └── 📄 .env.example             # Environment variables template
│
│   # ── Deleted in Phase 3 ──────────────────────────────────────
│   # asr_bridge.py, trigger_engine.py, question_trigger_engine.py
│   # vision_adapter.py, tts_client.py  (batch pipeline removed)
│
├── 📂 web/                          # Web frontend v3.0.0
│   ├── 📄 index.html               # Main dashboard (Omni Realtime · Edge AI)
│   ├── 📄 style.css                # Styles incl. degraded-banner + toast--warning
│   ├── 📄 app.js                   # Frontend JS — reactive state store
│   ├── 📄 manifest.json            # PWA metadata
│   └── 📄 sw.js                    # Service worker (cache-first statics)
├── 📂 device/                       # ESP32-S3 firmware
│   ├── 📄 esp32_full_firmware.ino  # Full firmware (Phase 3 — batch code removed)
│   ├── 📄 esp32_camera_test.ino    # Camera testing firmware
│   └── 📄 esp32_simulator.py       # Python ESP32 simulator
├── 📂 tests/                        # Unit tests
│   ├── 📄 conftest.py
│   ├── 📄 test_models.py
│   └── 📄 __init__.py
├── 📄 README.md
├── 📄 QUICKSTART.md
├── 📄 DEPLOYMENT.md
├── 📄 API.md
├── 📄 TESTING.md
├── 📄 pytest.ini
├── 📄 start_server.sh
└── 📄 .gitignore
```

---

## 🔌 API Endpoints

### HTTP REST API

| Method | Endpoint | Description | Response |
|--------|----------|-------------|----------|
| `GET` | `/` | Root health check | `{"status": "ok"}` |
| `GET` | `/health` | Full Omni system health | See schema below |
| `GET` | `/api/history?limit=20` | Get recent events | `[{event}, ...]` |

**`GET /health` Response Schema:**

```json
{
  "status": "healthy | degraded | error",
  "session_id": "xxx",
  "uptime_seconds": 3600,
  "last_latency_ms": 245,
  "audio_in_bytes": 123456,
  "audio_out_bytes": 789012,
  "images_sent": 120,
  "error_count": 0,
  "last_error": null
}
```

### WebSocket Endpoints

| Endpoint | Direction | Purpose | Data Format |
|----------|-----------|---------|-------------|
| `/ws_audio` | ESP32 → Server | Audio streaming | Binary (PCM16, 16kHz mono) |
| `/ws_camera` | ESP32 → Server | QVGA frame upload | Binary (JPEG ~10KB) |
| `/ws_ui` | Server → Browser | Event notifications | JSON typed events |

> **Note:** `/ws_ctrl` has been **removed** in Phase 3 — the batch capture command channel is no longer needed.

### WebSocket Event Types (`/ws_ui`)

| Event | Description |
|-------|-------------|
| `asr_partial` | Partial speech transcript from Omni |
| `asr_final` | Final speech transcript |
| `trigger_fired` | Wake/trigger detected |
| `capture_requested` | Camera frame requested |
| `capture_received` | Frame received by backend |
| `vision_started` | Vision processing started |
| `vision_result` | Vision analysis result text |
| `question_detected` | Question pattern identified |
| `tts_started` | TTS audio playback started |
| `error` | Error event |
| `SYSTEM_DEGRADED` | Omni WS exhausted — degraded mode entered |
| `SYSTEM_RECOVERED` | Omni WS reconnected — normal mode restored |

---

## 💡 ESP32-S3 LED State Indicator (GPIO 48)

| LED State | Pattern | Meaning |
|-----------|---------|---------|
| Off | — | Idle / standby |
| Solid ON | Constant | Processing (audio/vision active) |
| Fast Blink | Rapid flash | Error condition |

---

## 🧪 Testing

### Run Unit Tests

```bash
cd backend
pytest tests/ -v --cov=. --cov-report=html
```

### Test with ESP32 Simulator

```bash
python device/esp32_simulator.py --host localhost --port 8000
```

### Manual Testing Checklist

- [ ] Backend starts and `/health` returns `"status": "healthy"`
- [ ] Web UI loads and dashboard shows `Omni Realtime · Edge AI`
- [ ] ASR transcription appears in real-time
- [ ] Vision result appears alongside audio response
- [ ] Degraded mode banner shows on WS failure, clears on recovery
- [ ] LED GPIO 48 cycles correctly (idle → processing → error)
- [ ] Auto-reconnection works after disconnect

---

## 🛠️ Development

### Code Style

```bash
pip install black flake8 mypy

black backend/
flake8 backend/
mypy backend/
```

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production — Phase 3 Omni Realtime |
| `phase2` | Archived — Audio duplex + QVGA streaming |
| `phase1` | Archived — Batch pipeline with OMNI_MODE flag |

---

## 🐛 Troubleshooting

### Backend Won't Start

**`ModuleNotFoundError`:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**Port 8000 in use:**
```bash
lsof -i :8000          # Linux/Mac
kill -9 <PID>
```

### Omni WS / Degraded Mode

**Dashboard shows degraded banner persistently:**
1. Check `DASHSCOPE_API_KEY` is valid and has Omni Realtime access
2. Inspect backend logs: `sudo journalctl -u esp32-asr -f`
3. Verify `OMNI_MODEL=qwen3.5-omni-plus-realtime` in `.env`
4. The recovery loop retries every 30s automatically — wait and monitor logs

**High latency (`last_latency_ms` > 500):**
1. Check EC2 region — use a region geographically close to Dashscope endpoints
2. Reduce `OMNI_SESSION_REFRESH_MIN` to refresh the session more often

### ESP32 Connection Issues

1. Check EC2 security group allows port 8000
2. Verify correct IP in firmware (`WS_HOST`)
3. Confirm WiFi credentials
4. Check LED: solid = connected; fast blink = error

### Web UI Issues

**UI shows "Disconnected":**
1. `curl http://localhost:8000/health` — verify backend is running
2. Open browser console (F12) for WebSocket errors
3. Confirm `/ws_ui` is not blocked by firewall

---

## 📦 Python Dependencies

| Category | Packages |
|---|---|
| Web Framework | `fastapi 0.104.1`, `uvicorn[standard] 0.24.0` |
| WebSocket | `websockets 12.0`, `python-socketio 5.10.0` |
| Async | `asyncio 3.4.3`, `aiofiles 23.2.1` |
| HTTP Client | `httpx 0.25.1`, `aiohttp 3.9.1`, `requests 2.31.0` |
| Validation | `pydantic 2.5.0`, `pydantic-settings 2.1.0` |
| Config | `python-dotenv 1.0.0` |
| Image | `Pillow 10.1.0` |
| Audio | `numpy 1.26.2` |
| Fuzzy Match | `fuzzywuzzy 0.18.0`, `python-Levenshtein 0.23.0` |
| Testing | `pytest 7.4.3`, `pytest-asyncio 0.21.1`, `pytest-cov 4.1.0`, `hypothesis 6.92.1` |
| Logging | `structlog 23.2.0` |

See [`requirements.txt`](./backend/requirements.txt) for all pinned versions.

---

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** — Quick start guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — Detailed deployment instructions
- **[API.md](API.md)** — Complete API reference
- **[TESTING.md](TESTING.md)** — Testing guide

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

Follow PEP 8 style, add unit tests for new features, and ensure all tests pass.

---

## 🙏 Acknowledgments

- **Alibaba Cloud / DashScope** — Qwen Omni Realtime API
- **Qwen Team** — `qwen3.5-omni-plus-realtime` model
- **FastAPI** — Modern async web framework for Python
- **ESP32 Community** — Hardware and firmware support

---

## 📞 Support

- **GitHub Issues**: [Create an issue](https://github.com/Lokch777/EE3070-Design-Project/issues)
- **Documentation**: See the `docs/` folder

---

<div align="center">

**Made with ❤️ for EE3070 Design Project**

⭐ Star this repo if you find it helpful!

</div>
