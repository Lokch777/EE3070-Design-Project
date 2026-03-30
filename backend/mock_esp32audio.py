import asyncio
import websockets
import wave
import json
import time
import os

# 伺服器位址 (請確保 main.py 正在運行)
WS_AUDIO_URL = "ws://localhost:8080/ws_audio?device_id=virtual_esp32"

async def mock_esp32_client():
    print("🤖 啟動虛擬 ESP32...")
    
    try:
        async with websockets.connect(WS_AUDIO_URL) as ws:
            print("✅ 成功連線到伺服器 /ws_audio！")

            # 任務 1：接收伺服器傳來的 TTS 音訊 (Output Audio)
            async def receive_audio():
                audio_buffer = bytearray()
                print("🎧 開始監聽伺服器回傳的音訊...")
                while True:
                    try:
                        msg = await ws.recv()
                        if isinstance(msg, bytes):
                            print(f"📥 [Output Audio] 收到 TTS 音訊資料: {len(msg)} bytes")
                            audio_buffer.extend(msg)
                            
                            # 把收到的音訊存成檔案，你可以打開來聽聽看！
                            with open("test_output.raw", "wb") as f:
                                f.write(audio_buffer)
                        else:
                            print(f"📩 [Control Message] 收到伺服器指令: {msg}")
                    except websockets.exceptions.ConnectionClosed:
                        print("❌ 連線已關閉")
                        break

            # 任務 2：模擬麥克風發送音訊 (Input Audio)
            async def send_audio():
                print("🎤 準備發送測試音訊給伺服器...")
                await asyncio.sleep(1) # 等待一下讓連線穩定
                
                if os.path.exists("test_input.wav"):
                    print("📁 找到 test_input.wav，開始模擬講話...")
                    with wave.open("test_input.wav", "rb") as wf:
                        data = wf.readframes(1600) # 每次讀取一小塊 (模擬真實串流)
                        while data:
                            await ws.send(data)
                            await asyncio.sleep(0.1) # 模擬 0.1 秒的真實時間間隔
                            data = wf.readframes(1600)
                    print("✅ 模擬講話完畢！")
                else:
                    print("⚠️ 找不到 test_input.wav，發送 3 秒的『空白環境音』測試連線...")
                    empty_chunk = b'\x00' * 3200
                    for _ in range(30):
                        await ws.send(empty_chunk)
                        await asyncio.sleep(0.1)
                    print("✅ 空白音訊發送完畢！")

            # 同時執行收音與發音任務
            await asyncio.gather(receive_audio(), send_audio())

    except ConnectionRefusedError:
        print("❌ 無法連線！請確認你的 main.py 伺服器有開著喔！")

if __name__ == "__main__":
    # 需要安裝 websockets 套件：pip install websockets
    asyncio.run(mock_esp32_client())
