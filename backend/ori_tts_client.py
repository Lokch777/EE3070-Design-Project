import logging
import asyncio
import io
from typing import Optional
from dataclasses import dataclass
from gtts import gTTS
from pydub import AudioSegment

logger = logging.getLogger(__name__)

@dataclass
class TTSConfig:
    api_key: str
    endpoint: str
    model: str = "gtts"
    voice: str = "kiki"
    language: str = "zh-tw"  # 使用繁體中文發音
    speed: float = 1.0
    pitch: float = 1.0
    audio_format: str = "pcm"
    sample_rate: int = 16000
    timeout_seconds: float = 15.0

class TTSError(Exception):
    pass

class TTSClient:
    """Fallback TTS Client using Google Translate TTS (gTTS)"""
    
    def __init__(self, config: TTSConfig):
        self.config = config
        
    async def connect(self):
        logger.info("Initialized gTTS Fallback Client (No API Key required)")
    
    async def disconnect(self):
        pass
    
    async def convert_to_speech(self, text: str) -> bytes:
        #Remove the later on
        #logger.info(f"TTS 已暫時關閉，AI 回覆文字: {text}")
       # return b""


        logger.info(f"Using gTTS to convert text: {text[:50]}...")
        
        try:
            # 由於 gTTS 是同步的，我們使用 asyncio.to_thread 避免阻塞主迴圈
            def generate_audio():
                # 1. 生成 mp3
                tts = gTTS(text=text, lang=self.config.language, slow=False)
                mp3_fp = io.BytesIO()
                tts.write_to_fp(mp3_fp)
                mp3_fp.seek(0)
                
                # 2. 轉換為 ESP32 需要的格式 (16kHz, 16-bit PCM Mono)
                audio = AudioSegment.from_file(mp3_fp, format="mp3")
                audio = audio.set_frame_rate(self.config.sample_rate).set_channels(1).set_sample_width(2)
                
                # 3. 匯出 PCM 資料
                pcm_fp = io.BytesIO()
                audio.export(pcm_fp, format="s16le") # s16le 就是 PCM16
                return pcm_fp.getvalue()

            audio_data = await asyncio.to_thread(generate_audio)
            logger.info(f"gTTS conversion successful! Generated {len(audio_data)} bytes of PCM audio.")
            return audio_data

        except Exception as e:
            logger.error(f"gTTS conversion failed: {e}")
            raise TTSError(f"gTTS Conversion failed: {e}")

    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

class MockTTSClient:
    def __init__(self, config: TTSConfig): self.config = config
    async def connect(self): pass
    async def disconnect(self): pass
    async def convert_to_speech(self, text: str) -> bytes: return b"\x00\x00" * 16000
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc_val, exc_tb): pass
