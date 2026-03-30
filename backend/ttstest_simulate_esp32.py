import asyncio
import websockets
import wave
import json

# ===== 虛擬 ESP32 參數設定 =====
WS_URI = "ws://127.0.0.1:8080/ws_audio?device_id=simulator"
# 🚀 使用我們剛剛確認 100% 健康且清晰的 TTS 測試音檔
INPUT_WAV = "test_input.wav"
OUTPUT_WAV = "simulated_ai_reply.wav"
CHUNK_FRAMES = 1600  # 1600 samples * 2 bytes = 3200 bytes (完美符合伺服器要求)
SLEEP_TIME = 0.1     # 模擬 ESP32 每 100ms 發送一次的節奏

async def simulate_esp32():
    print(f"🔌 嘗試連線至伺服器: {WS_URI}")
    try:
        async with websockets.connect(WS_URI) as websocket:
            print("✅ 虛擬 ESP32 連線成功！")
            
            tts_audio_buffer = bytearray()

            # --- 任務 1：虛擬喇叭 (接收 TTS 回覆) ---
            async def receive_audio():
                print("🎧 開始監聽 AI 的語音回覆...")
                try:
                    while True:
                        message = await websocket.recv()
                        if isinstance(message, bytes):
                            print(f"📥 收到 TTS 語音封包: {len(message)} bytes")
                            tts_audio_buffer.extend(message)
                        else:
                            # 處理伺服器的 Ping，乖乖回傳 Pong 保持連線
                            try:
                                data = json.loads(message)
                                if data.get("type") == "ping":
                                    await websocket.send(json.dumps({"type": "pong"}))
                            except:
                                pass
                except websockets.exceptions.ConnectionClosed:
                    print("🔌 接收通道已正常關閉")

            # --- 任務 2：虛擬麥克風 (發送 WAV + 結尾靜音) ---
            async def send_audio():
                print(f"🎤 準備發送模擬語音: {INPUT_WAV}")
                try:
                    with wave.open(INPUT_WAV, 'rb') as wf:
                        print(f"📊 音檔格式: {wf.getframerate()}Hz, {wf.getnchannels()} 聲道")
                        
                        while True:
                            # 每次讀取 1600 個 frames (剛好 3200 bytes)
                            data = wf.readframes(CHUNK_FRAMES)
                            if not data:
                                break
                            
                            await websocket.send(data)
                            await asyncio.sleep(SLEEP_TIME) 
                            
                    print("📤 語音發送完畢！開始發送『3 秒靜音封包』觸發 ASR 結尾...")
                    
                    # 🚀 關鍵修復：發送 3 秒鐘的「完全靜音 (Zeros)」
                    # 這是告訴阿里雲 ASR：「我講完話了，請開始翻譯並交給 LLM！」
                    silence_chunk = b'\x00' * (CHUNK_FRAMES * 2) # 3200 bytes 的靜音
                    for _ in range(30): # 30 次 * 100ms = 3 秒鐘
                        await websocket.send(silence_chunk)
                        await asyncio.sleep(SLEEP_TIME)

                    print("⏳ 靜音發送完畢，等待 AI 思考與講話 (等待 20 秒)...")
                    await asyncio.sleep(20) # 留充足的時間讓 LLM 生成文字，並讓 TTS 轉成語音
                    await websocket.close() # 測試完成，主動掛斷電話
                    
                except FileNotFoundError:
                    print(f"❌ 找不到 {INPUT_WAV}！請確認檔案跟這個腳本放在同一個目錄下。")
                    await websocket.close()

            # 同時啟動麥克風與喇叭任務 (並發執行)
            await asyncio.gather(receive_audio(), send_audio())

            # --- 測試結束，存檔驗收 ---
            if len(tts_audio_buffer) > 0:
                with wave.open(OUTPUT_WAV, 'wb') as wf:
                    wf.setnchannels(1)            # 單聲道
                    wf.setsampwidth(2)            # 16-bit
                    wf.setframerate(16000)        # 16kHz
                    wf.writeframes(tts_audio_buffer)
                print(f"\n🎉 測試大成功！AI 的回覆已存成: {OUTPUT_WAV}")
                print("👉 請把這個檔案下載到電腦裡，聽聽看 AI 說了什麼！")
            else:
                print("\n⚠️ 測試結束，但沒有收到任何 TTS 語音。請檢查主伺服器 (main.py) 的 Log。")

    except Exception as e:
        print(f"❌ 連線失敗: {e}")

if __name__ == "__main__":
    asyncio.run(simulate_esp32())
