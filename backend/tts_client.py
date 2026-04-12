import asyncio
import io
import logging
import threading
import base64
from dataclasses import dataclass
from typing import Optional

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    QwenTtsRealtime,
    QwenTtsRealtimeCallback,
)
from gtts import gTTS
from pydub import AudioSegment

logger = logging.getLogger(__name__)

QWEN_TTS_WSS_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"


@dataclass
class TTSConfig:
    api_key: str
    endpoint: str
    model: str         = "qwen3-tts-flash-realtime-2025-11-27"
    voice: str         = "Cherry"
    language: str      = "Chinese"
    sample_rate: int   = 16000
    timeout_seconds: float = 30.0
    speed: float       = 1.0
    pitch: float       = 1.0
    audio_format: str  = "pcm"
    fallback_max_chars: int = 0
    # [FIX B] Trailing silence in ms — small safety pad for I2S DMA drain.
    # FIX 11/12/13 on ESP32 now properly handle DMA drain timing, so we
    # no longer need the massive 5000ms (160KB!) pad. 500ms is sufficient
    # to cover any edge cases and keeps the audio payload ~10x smaller.
    # 500ms = 16000 * 2 * 0.5 = 16000 bytes of zero-padding.
    trailing_silence_ms: int = 500


class TTSError(Exception):
    pass


# ── Callback（跑在 SDK 背景執行緒）─────────────────────────
class _AudioCollector(QwenTtsRealtimeCallback):
    def __init__(self):
        self.audio_chunks: list[bytes] = []
        self.done_event  = threading.Event()
        self.error: Optional[str] = None

    def on_open(self) -> None:
        logger.debug("[TTS] WebSocket opened")

    def on_event(self, response) -> None:
        try:
            event_type = response.get("type", "")
            logger.debug(f"[TTS] event={event_type}")

            if event_type == "response.audio.delta":
                audio_b64 = response.get("delta", "")
                if audio_b64:
                    self.audio_chunks.append(base64.b64decode(audio_b64))

            elif event_type == "response.done":
                logger.debug("[TTS] response.done → set done")
                self.done_event.set()

            elif event_type == "session.finished":
                logger.debug("[TTS] session.finished")
                self.done_event.set()

            elif event_type == "error" or "error" in event_type:
                self.error = str(response)
                logger.error(f"[TTS] Error event: {response}")
                self.done_event.set()

        except Exception as e:
            logger.error(f"[TTS] on_event error: {e}, raw={response}")

    def on_close(self, close_status_code, close_msg) -> None:
        logger.debug(f"[TTS] closed: {close_status_code} {close_msg}")
        self.done_event.set()

    def wait_for_done(self, timeout: float) -> bool:
        result = self.done_event.wait(timeout=timeout)
        if not result:
            logger.error(f"[TTS] Timeout {timeout}s, chunks={len(self.audio_chunks)}")
        return result


# ── TTS Client ─────────────────────────────────────────────
class TTSClient:
    """Qwen3 TTS Realtime (16kHz PCM) + gTTS fallback"""

    def __init__(self, config: TTSConfig):
        self.config = config
        if config.api_key and config.api_key != "test":
            dashscope.api_key = config.api_key
            logger.info(f"[TTS] API key: {config.api_key[:8]}...")
        else:
            logger.warning("[TTS] No valid API key → gTTS only")

    async def connect(self):
        logger.info(f"[TTS] Ready: model={self.config.model} voice={self.config.voice}")

    async def convert_to_speech(self, text: str) -> bytes:
        """
        Convert text to PCM bytes.
        [FIX B] Appends trailing_silence_ms of silence at the end so the
        ESP32 I2S DMA fully drains before playback_complete fires.
        Without this, the last 2-4 syllables are cut off by i2s_zero_dma_buffer().
        """
        if "qwen" in self.config.model.lower():
            try:
                pcm = await self._convert_qwen_realtime(text)
            except Exception as e:
                logger.error(
                    f"[TTS] Qwen failed ({type(e).__name__}: {e}), fallback gTTS",
                    exc_info=True,
                )
                pcm = await self._convert_gtts(text)
        else:
            pcm = await self._convert_gtts(text)

        # [FIX B] Append trailing silence
        # Prevents I2S DMA from being zeroed while still playing last words.
        # Formula: sample_rate × 2 bytes × (ms / 1000)
        if self.config.trailing_silence_ms > 0:
            silence_bytes = int(
                self.config.sample_rate * self.config.trailing_silence_ms / 1000
            ) * 2  # 16-bit = 2 bytes per sample
            pcm = pcm + bytes(silence_bytes)
            logger.debug(
                f"[TTS] Appended {self.config.trailing_silence_ms}ms trailing silence "
                f"({silence_bytes} bytes)"
            )

        return pcm

    async def _convert_qwen_realtime(self, text: str) -> bytes:
        logger.info(f"[TTS Qwen] voice={self.config.voice}: {text[:40]}...")

        def _run_sync():
            collector = _AudioCollector()

            client = QwenTtsRealtime(
                model=self.config.model,
                callback=collector,
                url=QWEN_TTS_WSS_URL,
            )
            client.connect()

            client.update_session(
                voice=self.config.voice,
                sample_rate=self.config.sample_rate,
                mode="commit",
                language_type=self.config.language,
            )

            client.append_text(text)
            client.commit()

            completed = collector.wait_for_done(timeout=self.config.timeout_seconds)

            try:
                client.finish()
                client.close()
            except Exception as e:
                logger.debug(f"[TTS] Ignored client close error: {e}")

            if not completed:
                raise TTSError("Qwen TTS timeout")
            if collector.error:
                raise TTSError(f"Qwen TTS error: {collector.error}")
            if not collector.audio_chunks:
                raise TTSError("Qwen TTS returned no audio")

            return b"".join(collector.audio_chunks)

        pcm_bytes = await asyncio.to_thread(_run_sync)
        logger.info(
            f"[TTS Qwen] ✅ {len(pcm_bytes)} bytes "
            f"({len(pcm_bytes) / 2 / self.config.sample_rate:.2f}s)"
        )
        return pcm_bytes

    async def _convert_gtts(self, text: str) -> bytes:
        trimmed = (text or "").strip()
        if self.config.fallback_max_chars > 0 and len(trimmed) > self.config.fallback_max_chars:
            trimmed = trimmed[: self.config.fallback_max_chars]
        if trimmed and trimmed[-1] not in "。！？!?":
            trimmed += "。"

        logger.info(f"[TTS gTTS] {trimmed[:40]}...")

        def _generate():
            tts = gTTS(text=trimmed, lang="zh-TW", slow=False)
            mp3_buf = io.BytesIO()
            tts.write_to_fp(mp3_buf)
            mp3_buf.seek(0)
            audio = (
                AudioSegment.from_file(mp3_buf, format="mp3")
                .set_channels(1)
                .set_frame_rate(self.config.sample_rate)
                .set_sample_width(2)
            )
            pcm_buf = io.BytesIO()
            audio.export(pcm_buf, format="s16le")
            return pcm_buf.getvalue()

        return await asyncio.to_thread(_generate)

    async def disconnect(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── Mock TTS Client ────────────────────────────────────────
class MockTTSClient:
    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config
        self._sample_rate = config.sample_rate if config else 16000

    async def connect(self):
        logger.info("[MockTTS] Ready")

    async def convert_to_speech(self, text: str) -> bytes:
        logger.info(f"[MockTTS] Skip: {text[:40]}...")
        duration_sec = max(1.0, len(text) * 0.05)
        return bytes(int(self._sample_rate * 2 * duration_sec))

    async def disconnect(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
