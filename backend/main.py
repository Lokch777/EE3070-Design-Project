# ESP32 ASR Capture Vision MVP - Backend Entry Point
# FIXES:
#   1. on_event → lifespan (deprecation removed)
#   2. unregister_audio_device passes websocket object (stale unregister fix)
#   3. Duplicate del in ws_camera finally removed

from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import logging
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Optional

from backend.models import Event, EventType, ConnectionState, ConnectionType
from backend.app_coordinator import AppCoordinator
from backend.config import load_settings, validate_api_keys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    settings = load_settings()
    if not validate_api_keys(settings):
        logger.warning("API keys not configured - using mock adapters")
except Exception as e:
    logger.error(f"Failed to load settings: {e}")
    raise

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

app_coordinator = AppCoordinator(settings)
event_bus = app_coordinator.get_event_bus()

connected_clients: Dict[str, ConnectionState] = {}
ctrl_clients: Dict[str, WebSocket] = {}
capture_forward_task: Optional[asyncio.Task] = None

HEARTBEAT_INTERVAL = 30
HEARTBEAT_TIMEOUT  = 60


# ✅ FIX 1: lifespan replaces deprecated on_event
@asynccontextmanager
async def lifespan(app: FastAPI):
    global capture_forward_task
    logger.info("Starting ESP32 ASR Capture Vision MVP...")
    await app_coordinator.start()
    capture_forward_task = asyncio.create_task(forward_capture_requests_to_ctrl())
    logger.info("Application started successfully")
    yield
    logger.info("Shutting down...")
    if capture_forward_task:
        capture_forward_task.cancel()
        with suppress(asyncio.CancelledError):
            await capture_forward_task
        capture_forward_task = None
    await app_coordinator.stop()
    logger.info("Application stopped")


app = FastAPI(
    title="ESP32 ASR Capture Vision MVP",
    description="Backend service for voice-controlled object recognition",
    version="0.1.0",
    lifespan=lifespan,   # ← replaces @app.on_event
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "ESP32 ASR Capture Vision MVP Backend", "status": "running"}


@app.get("/api/health")
async def health_check():
    esp32_audio  = any(c.conn_type == ConnectionType.ESP32_AUDIO.value  for c in connected_clients.values())
    esp32_camera = any(c.conn_type == ConnectionType.ESP32_CAMERA.value for c in connected_clients.values())
    web_ui       = any(c.conn_type == ConnectionType.WEB_UI.value       for c in connected_clients.values())
    return {
        "status": "healthy",
        "esp32_audio_connected":  esp32_audio,
        "esp32_camera_connected": esp32_camera,
        "web_ui_connected":       web_ui,
        "total_connections":      len(connected_clients),
        "images_stored":          len(list(IMAGES_DIR.glob("*.jpg"))),
        "event_bus_stats":        event_bus.get_stats(),
    }


@app.get("/api/history")
async def get_history(limit: int = 20, event_type: Optional[str] = None):
    events = event_bus.get_history(limit=limit, event_type=event_type)
    return {"events": [e.to_dict() for e in events], "count": len(events)}


@app.post("/api/upload_image")
async def upload_image(file: UploadFile = File(...), req_id: str = Form(None)):
    try:
        timestamp  = int(time.time() * 1000)
        req_id_str = req_id or f"test-{timestamp}"
        filename   = f"{req_id_str}_{timestamp}.jpg"
        filepath   = IMAGES_DIR / filename

        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)

        logger.info(f"Image saved: {filename} ({len(content)} bytes)")

        event = Event(
            event_type=EventType.CAPTURE_RECEIVED.value,
            timestamp=time.time(),
            req_id=req_id_str,
            data={"filename": filename, "image_size": len(content), "format": "jpeg"},
        )
        await event_bus.publish(event)
        return {"success": True, "filename": filename, "size": len(content), "path": str(filepath)}

    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/images")
async def list_images():
    images = []
    for img_path in sorted(IMAGES_DIR.glob("*.jpg"), reverse=True):
        stat = img_path.stat()
        images.append({"filename": img_path.name, "size": stat.st_size, "created": stat.st_mtime})
    return {"images": images, "count": len(images)}


@app.websocket("/ws_audio")
async def websocket_audio(websocket: WebSocket):
    await websocket.accept()
    client_id = f"esp32_audio_{id(websocket)}"
    device_id = websocket.query_params.get("device_id", "default")

    conn_state = ConnectionState(
        conn_id=client_id,
        conn_type=ConnectionType.ESP32_AUDIO.value,
        connected_at=time.time(),
        last_heartbeat=time.time(),
        metadata={"device_id": device_id},
    )
    connected_clients[client_id] = conn_state
    app_coordinator.register_audio_device(device_id, websocket)
    logger.info(f"ESP32 audio connected: {client_id}, device_id={device_id}")

    heartbeat_task = asyncio.create_task(send_heartbeat(websocket, client_id))

    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                logger.info(f"ESP32 audio disconnect frame received: {client_id}")
                break

            if "bytes" in data:
                conn_state.last_heartbeat = time.time()
                await app_coordinator.handle_audio_chunk(data["bytes"], device_id=device_id)

            elif "text" in data:
                try:
                    message = json.loads(data["text"])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON on /ws_audio from {device_id}: {data['text']}")
                    continue

                if message.get("type") == "pong":
                    conn_state.last_heartbeat = time.time()
                else:
                    await app_coordinator.on_audio_control_message(device_id, message)

    except WebSocketDisconnect:
        logger.info(f"ESP32 audio disconnected: {client_id}")
    except RuntimeError as e:
        if "disconnect message has been received" in str(e):
            logger.info(f"ESP32 audio disconnected (runtime): {client_id}")
        else:
            logger.error(f"WebSocket audio runtime error: {e}")
    except Exception as e:
        logger.error(f"WebSocket audio error: {e}")
    finally:
        heartbeat_task.cancel()
        # ✅ FIX 2: pass websocket so coordinator ignores stale unregisters
        app_coordinator.unregister_audio_device(device_id, websocket=websocket)
        connected_clients.pop(client_id, None)


@app.websocket("/ws_ctrl")
async def websocket_ctrl(websocket: WebSocket):
    await websocket.accept()
    client_id = f"esp32_ctrl_{id(websocket)}"
    device_id = websocket.query_params.get("device_id", "default")

    conn_state = ConnectionState(
        conn_id=client_id,
        conn_type=ConnectionType.ESP32_CTRL.value,
        connected_at=time.time(),
        last_heartbeat=time.time(),
        metadata={"device_id": device_id},
    )
    connected_clients[client_id] = conn_state
    ctrl_clients[client_id] = websocket
    logger.info(f"ESP32 control connected: {client_id}, device_id={device_id}")

    heartbeat_task = asyncio.create_task(send_heartbeat(websocket, client_id))

    try:
        while True:
            data    = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "pong":
                conn_state.last_heartbeat = time.time()
            else:
                logger.debug(f"Received control message: {message}")

    except WebSocketDisconnect:
        logger.info(f"ESP32 control disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket control error: {e}")
    finally:
        heartbeat_task.cancel()
        ctrl_clients.pop(client_id, None)
        connected_clients.pop(client_id, None)


@app.websocket("/ws_camera")
async def websocket_camera(websocket: WebSocket):
    await websocket.accept()
    client_id = f"esp32_camera_{id(websocket)}"

    conn_state = ConnectionState(
        conn_id=client_id,
        conn_type=ConnectionType.ESP32_CAMERA.value,
        connected_at=time.time(),
        last_heartbeat=time.time(),
        metadata={},
    )
    connected_clients[client_id] = conn_state
    logger.info(f"ESP32 camera connected: {client_id}")

    try:
        while True:
            try:
                header_data = await websocket.receive_text()
                header      = json.loads(header_data)
                req_id      = header.get("req_id", f"unknown-{int(time.time())}")
                expected_size = header.get("size", 0)

                conn_state.last_heartbeat = time.time()
                logger.info(f"Receiving image: req_id={req_id}, size={expected_size}")
                app_coordinator.capture_coordinator.mark_capture_started(req_id, expected_size)

                image_data = await websocket.receive_bytes()

                timestamp = int(time.time() * 1000)
                filename  = f"{req_id}_{timestamp}.jpg"
                filepath  = IMAGES_DIR / filename

                with open(filepath, "wb") as f:
                    f.write(image_data)

                logger.info(f"Image saved: {filename} ({len(image_data)} bytes)")

                event = Event(
                    event_type=EventType.CAPTURE_RECEIVED.value,
                    timestamp=time.time(),
                    req_id=req_id,
                    data={"filename": filename, "image_size": len(image_data), "format": "jpeg"},
                )
                await event_bus.publish(event)

                try:
                    await websocket.send_json({
                        "status": "success", "req_id": req_id,
                        "filename": filename, "size": len(image_data),
                    })
                except Exception as ack_err:
                    logger.debug(f"Camera ack skipped for req_id={req_id}: {ack_err}")

            except json.JSONDecodeError:
                logger.error("Invalid JSON header")
                await websocket.send_json({"status": "error", "message": "Invalid JSON header"})

    except WebSocketDisconnect:
        logger.info(f"ESP32 camera disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket camera error: {e}")
    finally:
        # ✅ FIX 3: removed duplicate del that existed in original
        connected_clients.pop(client_id, None)


@app.websocket("/ws_ui")
async def websocket_ui(websocket: WebSocket):
    await websocket.accept()
    client_id = f"web_ui_{id(websocket)}"

    conn_state = ConnectionState(
        conn_id=client_id,
        conn_type=ConnectionType.WEB_UI.value,
        connected_at=time.time(),
        last_heartbeat=time.time(),
        metadata={},
    )
    connected_clients[client_id] = conn_state
    logger.info(f"Web UI connected: {client_id}")

    heartbeat_task = asyncio.create_task(send_heartbeat(websocket, client_id))
    event_task     = asyncio.create_task(forward_events_to_ui(websocket, client_id))

    try:
        while True:
            data    = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "pong":
                conn_state.last_heartbeat = time.time()
            else:
                logger.debug(f"Received from Web UI: {message}")

    except WebSocketDisconnect:
        logger.info(f"Web UI disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket UI error: {e}")
    finally:
        heartbeat_task.cancel()
        event_task.cancel()
        connected_clients.pop(client_id, None)


async def send_heartbeat(websocket: WebSocket, client_id: str):
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if client_id not in connected_clients:
                break
            conn_state = connected_clients[client_id]
            if time.time() - conn_state.last_heartbeat > HEARTBEAT_TIMEOUT:
                logger.warning(f"Client {client_id} heartbeat timeout")
                await websocket.close()
                break
            try:
                await websocket.send_json({"type": "ping", "timestamp": time.time()})
            except Exception as e:
                logger.error(f"Failed to send heartbeat to {client_id}: {e}")
                break
    except asyncio.CancelledError:
        pass


async def forward_events_to_ui(websocket: WebSocket, client_id: str):
    try:
        async for event in event_bus.subscribe("*"):
            if client_id not in connected_clients:
                break
            try:
                event_dict = event.to_dict()
                if "data" in event_dict and isinstance(event_dict["data"], dict):
                    for key, value in list(event_dict["data"].items()):
                        if isinstance(value, bytes):
                            event_dict["data"][key] = "<binary>"
                await websocket.send_json(event_dict)
            except Exception as e:
                logger.error(f"Failed to forward event to {client_id}: {e}")
                if "close message has been sent" in str(e) or "disconnect" in str(e).lower():
                    break
                continue
    except asyncio.CancelledError:
        pass


async def forward_capture_requests_to_ctrl():
    try:
        async for event in event_bus.subscribe(EventType.CAPTURE_REQUESTED.value):
            target_device_id = event.data.get("device_id")
            message = {"type": "CAPTURE", "req_id": event.req_id, "timestamp": event.timestamp}
            if "trigger_text" in event.data:
                message["trigger_text"] = event.data["trigger_text"]
            if "retry_count" in event.data:
                message["retry_count"] = event.data["retry_count"]

            if not ctrl_clients:
                logger.warning("No /ws_ctrl client connected for CAPTURE request req_id=%s", event.req_id)
                continue

            disconnected = []
            sent = 0
            for client_id, ws in list(ctrl_clients.items()):
                if target_device_id:
                    conn = connected_clients.get(client_id)
                    conn_device_id = (conn.metadata or {}).get("device_id") if conn else None
                    if conn_device_id != target_device_id:
                        continue
                try:
                    await ws.send_json(message)
                    sent += 1
                    logger.info("Sent CAPTURE command to %s for req_id=%s", client_id, event.req_id)
                except Exception as e:
                    logger.error("Failed to send CAPTURE to %s: %s", client_id, e)
                    disconnected.append(client_id)

            for client_id in disconnected:
                ctrl_clients.pop(client_id, None)

            if target_device_id and sent == 0:
                logger.warning("No matching /ws_ctrl for device_id=%s req_id=%s", target_device_id, event.req_id)

    except asyncio.CancelledError:
        pass



# ── 靜態檔案掛載（順序很重要！）─────────────────────────

# 1️⃣ 先掛載 /images（避免被 /web 路由攔截）
if IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

# 2️⃣ 再掛載前端於 /web 子路徑（情況 A：web 在 backend 上層）
#    ✅ 加上 html=True 啟用 index.html 降級，支援前端路由
if Path("../web").exists():
    app.mount("/web", StaticFiles(directory="../web", html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
