import asyncio
import logging
import wave
from backend.tts_client import TTSClient, TTSConfig

logging.basicConfig(level=logging.INFO)

async def main():
    # 建立 TTS 設定 (gTTS 不需要 API key，隨便填即可)
    config = TTSConfig(
        api_key="test",
        endpoint="test",
        language="zh-tw",  # 繁體中文
        sample_rate=16000
    )
    
    # 啟動 TTS 客戶端
    client = TTSClient(config)
    
    test_text = "你好！這是一個語音合成測試。恭喜你成功搞定了麥克風的雜音問題！"
    print(f"🚀 準備轉換文字: {test_text}")
    
    try:
        # 執行文字轉語音
        pcm_audio_bytes = await client.convert_to_speech(test_text)
        
        if not pcm_audio_bytes or len(pcm_audio_bytes) == 0:
            print("❌ 轉換失敗，收到空白的音訊資料。")
            return
            
        print(f"✅ 轉換成功！產生了 {len(pcm_audio_bytes)} bytes 的 PCM 資料。")
        
        # 把轉換出來的 PCM 資料打包成 WAV 檔案，方便下載試聽
        output_filename = "test_tts_output.wav"
        with wave.open(output_filename, "wb") as wav_file:
            wav_file.setnchannels(1)      # 單聲道
            wav_file.setsampwidth(2)      # 16-bit
            wav_file.setframerate(16000)  # 16kHz
            wav_file.writeframes(pcm_audio_bytes)
            
        print(f"🎵 測試音檔已儲存為 {output_filename}，請下載下來試聽！")
        
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    asyncio.run(main())
