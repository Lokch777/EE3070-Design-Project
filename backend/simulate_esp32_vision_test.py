import asyncio
import websockets
import wave
import json
import os
import base64

# ===== 虛擬 ESP32 參數設定 =====
WS_AUDIO_URI  = "ws://127.0.0.1:8080/ws_audio?device_id=simulator"
WS_CTRL_URI   = "ws://127.0.0.1:8080/ws_ctrl?device_id=simulator"
WS_CAMERA_URI = "ws://127.0.0.1:8080/ws_camera?device_id=simulator"

INPUT_WAV  = "test_input.wav"        
TEST_IMAGE = "test_image.jpg"        
OUTPUT_WAV = "simulated_ai_reply.wav"

CHUNK_FRAMES = 1600  
SLEEP_TIME   = 0.1   

async def simulate_vision_esp32():
    print(f"🔌 嘗試連線至伺服器...\n音訊: {WS_AUDIO_URI}\n控制: {WS_CTRL_URI}")
    
    if not os.path.exists(TEST_IMAGE): return print(f"❌ 找不到 {TEST_IMAGE}！")
    if not os.path.exists(INPUT_WAV): return print(f"❌ 找不到 {INPUT_WAV}！")

    # 🚀 新增狀態字典，用來記錄伺服器這次任務的流水號
    state = {"req_id": ""}

    try:
        async with websockets.connect(WS_AUDIO_URI) as ws_audio, \
                   websockets.connect(WS_CTRL_URI) as ws_ctrl:
            
            print("✅ 虛擬 ESP32 雙通道連線成功！")
            tts_audio_buffer = bytearray()

            # --- 任務 1：虛擬喇叭 (接收 TTS 拆解 JSON 並記錄 req_id) ---
            async def audio_receive_task():
                print("🎧 喇叭就緒，開始監聽 AI 的語音回覆...")
                try:
                    while True:
                        message = await ws_audio.recv()
                        if isinstance(message, bytes):
                            tts_audio_buffer.extend(message)
                        else:
                            try:
                                data = json.loads(message)
                                if data.get("type") == "ping":
                                    await ws_audio.send(json.dumps({"type": "pong"}))
                                else:
                                    # 偷偷記錄伺服器給的 req_id，等一下要用來解除鎖定
                                    if "req_id" in data: state["req_id"] = data["req_id"]
                                    if "request_id" in data: state["req_id"] = data["request_id"]
                                    
                                    msg_preview = str(data)[:80].replace('\n', '')
                                    print(f"💬 收到伺服器語音 JSON 封包: {msg_preview}...")
                                    
                                    # 從 JSON 裡抽出 Base64 音訊
                                    for key in ["audio_data", "data", "payload", "chunk", "audio"]:
                                        if key in data and isinstance(data[key], str) and len(data[key]) > 100:
                                            try:
                                                tts_audio_buffer.extend(base64.b64decode(data[key]))
                                                break
                                            except: pass
                            except Exception: pass
                except websockets.exceptions.ConnectionClosed:
                    print("🔌 音訊接收通道已正常關閉")

            # --- 任務 2：虛擬大腦 (相機上傳) ---
            async def ctrl_task():
                print(f"📷 控制中心待命中... 隨時準備拍攝 {TEST_IMAGE}")
                try:
                    while True:
                        msg = await ws_ctrl.recv()
                        if isinstance(msg, str):
                            try:
                                data = json.loads(msg)
                                if data.get("type") == "ping":
                                    await ws_ctrl.send(json.dumps({"type": "pong"}))
                                    continue
                                
                                json_str = json.dumps(data).lower()
                                if "req_id" in json_str or "capture" in json_str:
                                    req_id = data.get("req_id", "")
                                    print(f"\n🚨 伺服器要求拍照！指令內容: {data}")
                                    
                                    with open(TEST_IMAGE, "rb") as f:
                                        img_data = f.read()
                                        
                                    try:
                                        async with websockets.connect(WS_CAMERA_URI) as ws_cam:
                                            header = {"req_id": req_id, "size": len(img_data)}
                                            await ws_cam.send(json.dumps(header))
                                            await ws_cam.send(img_data)
                                            ack = await ws_cam.recv()
                                            print(f"✅ 照片上傳成功！等待 Qwen-VL 模型看圖說故事...")
                                    except Exception as e:
                                        print(f"❌ 相機通道上傳失敗: {e}")

                            except json.JSONDecodeError: pass
                except websockets.exceptions.ConnectionClosed:
                    print("🔌 控制通道已正常關閉")

            # --- 任務 3：虛擬麥克風 (發送 WAV -> 靜音觸發 -> 結束前發送解鎖通知) ---
            async def audio_send_task():
                print("🔔 傳送喚醒封包，等待後端 ASR 引擎熱機 (2 秒)...")
                await ws_audio.send(b'\x00' * (CHUNK_FRAMES * 2)) 
                await asyncio.sleep(2) 
                
                print(f"🎤 準備提問: {INPUT_WAV}")
                try:
                    with wave.open(INPUT_WAV, 'rb') as wf:
                        while True:
                            data = wf.readframes(CHUNK_FRAMES)
                            if not data: break
                            await ws_audio.send(data)
                            await asyncio.sleep(SLEEP_TIME)
                            
                    print("📤 語音發送完畢！發送 3 秒靜音觸發 ASR...")
                    silence_chunk = b'\x00' * (CHUNK_FRAMES * 2) 
                    for _ in range(30):
                        await ws_audio.send(silence_chunk)
                        await asyncio.sleep(SLEEP_TIME)

                    print("⏳ 靜音完畢。系統已觸發！等待 AI 思考與 TTS 傳輸 (等待 25 秒)...")
                    await asyncio.sleep(25) # 聽完 245 個封包大約需要一點時間
                    
                    # 🚀 終極修復：解開伺服器的死結！
                    if state["req_id"]:
                        print(f"\n🔓 正在向伺服器發送「播放完畢 (playback_complete)」解鎖訊號: {state['req_id']}")
                        unlock_msg = {
                            "type": "playback_complete",
                            "request_id": state["req_id"]
                        }
                        await ws_audio.send(json.dumps(unlock_msg))
                        await asyncio.sleep(1) # 給伺服器一秒鐘把鎖解開
                    
                    await ws_audio.close()
                    await ws_ctrl.close()
                except Exception as e:
                    print(f"❌ 語音發送錯誤: {e}")
                    await ws_audio.close()
                    await ws_ctrl.close()

            await asyncio.gather(audio_receive_task(), ctrl_task(), audio_send_task())

            # --- 存檔驗收 ---
            if len(tts_audio_buffer) > 0:
                with wave.open(OUTPUT_WAV, 'wb') as wf:
                    wf.setnchannels(1)            
                    wf.setsampwidth(2)            
                    wf.setframerate(16000)        
                    wf.writeframes(tts_audio_buffer)
                print(f"\n🎉 視覺語音全鏈路測試大滿貫！")
                print(f"👉 AI 的語音解說已成功解碼並存成: {OUTPUT_WAV}！")
                print(f"   (伺服器鎖定已解除，你可以隨時再跑一次！)")
            else:
                print("\n⚠️ 測試結束，沒有提取到語音資料。")

    except Exception as e:
        print(f"❌ 連線失敗: {e}")

if __name__ == "__main__":
    asyncio.run(simulate_vision_esp32())
