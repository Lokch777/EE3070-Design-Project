"""
Realtime Omni Gateway — bridges device WebSocket to Qwen realtime model.

Protocol (device → gateway):
  {"type":"audio_chunk",  "pcm16_b64":"<base64 PCM-16 mono 16kHz>"}
  {"type":"audio_commit"}          — end of speech segment, request response
  {"type":"image_frame",  "jpeg_b64":"<base64 JPEG>"}
  {"type":"user_text",    "text":"..."}   (optional text input)
  {"type":"ping"}

Protocol (gateway → device):
  {"type":"tts_audio_delta", "audio_b64":"<base64 PCM-16>"}
  {"type":"text_delta",      "text":"..."}
  {"type":"response_done"}
  {"type":"pong"}
  {"type":"error",           "message":"..."}

Environment variables:
  DASHSCOPE_API_KEY        — required
  QWEN_REALTIME_MODEL      — default: qwen3-omni-flash-realtime
  QWEN_REALTIME_REGION     — "intl" (default) or "cn"
  QWEN_REALTIME_VOICE      — default: Cherry
  REALTIME_HOST            — default: 0.0.0.0
  REALTIME_PORT            — default: 8765
  LOG_LEVEL                — default: INFO
"""

import os
import json
import asyncio
import logging
import websockets

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
REGION    = os.getenv("QWEN_REALTIME_REGION", "intl")
MODEL     = os.getenv("QWEN_REALTIME_MODEL",  "qwen3-omni-flash-realtime")
API_KEY   = os.getenv("DASHSCOPE_API_KEY",    "")
VOICE     = os.getenv("QWEN_REALTIME_VOICE",  "Cherry")
LOG_LEVEL = os.getenv("LOG_LEVEL",            "INFO")

_BASE_HOST = (
    "dashscope-intl.aliyuncs.com" if REGION == "intl"
    else "dashscope.aliyuncs.com"
)
QWEN_WS_URL = f"wss://{_BASE_HOST}/api-ws/v1/realtime?model={MODEL}"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger("realtime_gateway")

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Qwen Omni Realtime Gateway",
    description="WebSocket bridge between ESP32 device and Qwen realtime model",
    version="1.0.0",
)


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "model": MODEL, "region": REGION, "voice": VOICE})


@app.websocket("/ws/device")
async def ws_device(device_ws: WebSocket):
    """Single WebSocket endpoint.  Device connects here; gateway bridges to Qwen."""
    await device_ws.accept()
    logger.info("Device connected")

    if not API_KEY:
        await device_ws.send_text(
            json.dumps({"type": "error", "message": "Missing DASHSCOPE_API_KEY on server"})
        )
        await device_ws.close()
        return

    try:
        qwen_ws = await websockets.connect(
            QWEN_WS_URL,
            additional_headers={"Authorization": f"Bearer {API_KEY}"},
            ping_interval=20,
            ping_timeout=30,
        )
    except Exception as e:
        logger.error("Failed to connect to Qwen realtime: %s", e)
        await device_ws.send_text(
            json.dumps({"type": "error", "message": f"Cannot reach Qwen realtime: {e}"})
        )
        await device_ws.close()
        return

    logger.info("Connected to Qwen realtime: %s", QWEN_WS_URL)

    # Send session configuration to Qwen
    try:
        await qwen_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": VOICE,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "instructions": (
                    "You are a helpful assistant with real-time microphone and camera access. "
                    "Answer immediately and concisely. "
                    "If an image is provided, describe or use it in your answer."
                ),
            }
        }))
    except Exception as e:
        logger.warning("session.update failed (may not be supported): %s", e)

    async def device_to_qwen():
        """Forward device messages to the Qwen realtime WebSocket."""
        try:
            while True:
                raw = await device_ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from device: %.120s", raw)
                    continue

                msg_type = msg.get("type")

                if msg_type == "audio_chunk":
                    b64 = msg.get("pcm16_b64", "")
                    if b64:
                        await qwen_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": b64,
                        }))

                elif msg_type == "audio_commit":
                    await qwen_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await qwen_ws.send(json.dumps({
                        "type": "response.create",
                        "response": {
                            "modalities": ["audio", "text"],
                            "voice": VOICE,
                        },
                    }))

                elif msg_type == "image_frame":
                    jpeg_b64 = msg.get("jpeg_b64", "")
                    if jpeg_b64:
                        await qwen_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_image",
                                        "image_base64": jpeg_b64,
                                    }
                                ],
                            },
                        }))

                elif msg_type == "user_text":
                    text = msg.get("text", "").strip()
                    if text:
                        await qwen_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": text}],
                            },
                        }))

                elif msg_type == "ping":
                    await device_ws.send_text(json.dumps({"type": "pong"}))

                else:
                    logger.debug("Unknown device message type: %s", msg_type)

        except WebSocketDisconnect:
            logger.info("Device disconnected")
        except Exception as e:
            logger.error("device_to_qwen error: %s", e)
        finally:
            await qwen_ws.close()

    async def qwen_to_device():
        """Forward Qwen realtime events to the device WebSocket."""
        try:
            async for raw in qwen_ws:
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                evt_type = evt.get("type", "")
                logger.debug("Qwen event: %s", evt_type)

                # Audio delta — PCM-16 base64
                if "audio.delta" in evt_type:
                    delta = evt.get("delta", "")
                    if delta:
                        await device_ws.send_text(json.dumps({
                            "type": "tts_audio_delta",
                            "audio_b64": delta,
                        }))

                # Text delta
                elif "text.delta" in evt_type:
                    delta = evt.get("delta", "")
                    if delta:
                        await device_ws.send_text(json.dumps({
                            "type": "text_delta",
                            "text": delta,
                        }))

                # Response complete
                elif evt_type in ("response.done", "response.audio.done"):
                    await device_ws.send_text(json.dumps({"type": "response_done"}))

                # Error events
                elif "error" in evt_type:
                    logger.error("Qwen error event: %s", evt)
                    await device_ws.send_text(json.dumps({
                        "type": "error",
                        "message": evt.get("error", {}).get("message", str(evt)),
                    }))

        except Exception as e:
            logger.error("qwen_to_device error: %s", e)
        finally:
            try:
                await device_ws.close()
            except Exception:
                pass

    await asyncio.gather(device_to_qwen(), qwen_to_device())
    logger.info("Session ended")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("REALTIME_HOST", "0.0.0.0")
    port = int(os.getenv("REALTIME_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level=LOG_LEVEL.lower())
