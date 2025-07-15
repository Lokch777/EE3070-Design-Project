import azure.functions as func
import logging
import os
import json
import requests
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

# 初始化 Function App，我們將在每個函式內部單獨定義授權等級
app = func.FunctionApp() 

# --- 從環境變數讀取設定 (這部分不變) ---
PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")
APP_ID = os.environ.get("DISCORD_APP_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")
RESOURCE_GROUP_NAME = os.environ.get("RESOURCE_GROUP_NAME")
VM_NAME = os.environ.get("VM_NAME")

# 檢查是否有任何必要的環境變數未設定
if not all([PUBLIC_KEY, APP_ID, BOT_TOKEN, SUBSCRIPTION_ID, RESOURCE_GROUP_NAME, VM_NAME]):
    logging.warning("One or more environment variables are not set. The application might not function correctly.")

# 只有在 Public Key 存在時才初始化驗證器，以避免啟動時崩潰
if PUBLIC_KEY:
    verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
else:
    verify_key = None

# --- 函式 1: 處理來自 Discord 的互動 (已整合詳細日誌) ---
@app.route(route="discord-interactions", auth_level=func.AuthLevel.ANONYMOUS)
def discord_interactions(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Discord interaction function triggered.')
    
    # 驗證請求
    if not verify_key:
        logging.error("DISCORD_PUBLIC_KEY is not set. Cannot verify request.")
        return func.HttpResponse("Configuration error", status_code=500)
        
    signature = req.headers.get('X-Signature-Ed25519')
    timestamp = req.headers.get('X-Signature-Timestamp')
    body = req.get_body()
    try:
        verify_key.verify(f'{timestamp}{body.decode("utf-8")}'.encode(), bytes.fromhex(signature))
    except Exception as e:
        logging.error(f"Invalid request signature: {e}")
        return func.HttpResponse("Invalid request signature", status_code=401)
    
    data = req.get_json()
    # 處理 Discord 的 PING 請求
    if data.get('type') == 1:
        return func.HttpResponse(json.dumps({'type': 1}), mimetype="application/json")
    
    # 處理斜線指令
    if data.get('type') == 2 and data['data']['name'] == 'start-mc-server':
        logging.info("'/start-mc-server' command received. Responding with DEFERRED.")
        deferred_response = {'type': 5}
        
        message_content = ""
        try:
            logging.info("Calling start_vm function...")
            start_vm()
            message_content = f"✅ **請求已收到！**\n正在啟動 Minecraft 伺服器 `{VM_NAME}`，請稍候..."
            logging.info("start_vm function completed successfully.")
        except Exception as e:
            logging.error(f"An error occurred in start_vm: {e}")
            message_content = f"❌ **啟動失敗！**\n無法啟動伺服器。\n錯誤: {str(e)[:1000]}"
        
        # 使用後續訊息更新 Discord 上的 "正在思考..."
        interaction_token = data['token']
        followup_url = f"https://discord.com/api/v10/webhooks/{APP_ID}/{interaction_token}"
        
        logging.info(f"Preparing to send followup message to Discord.")
        try:
            response = requests.post(followup_url, json={'content': message_content})
            logging.info(f"Followup message sent. Status code: {response.status_code}")
            if response.status_code >= 400:
                logging.error(f"Discord API returned an error: {response.text}")
        except Exception as e:
            logging.error(f"Failed to send followup message: {e}")

        return func.HttpResponse(json.dumps(deferred_response), mimetype="application/json")

    return func.HttpResponse("Request processed.", status_code=200)

# --- 函式 2: 專門用來被 Azure 警示呼叫以關閉 VM ---
@app.route(route="stop-vm", auth_level=func.AuthLevel.FUNCTION)
def stop_interactions(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Stop VM function triggered by Azure Alert.')
    try:
        stop_vm()
        logging.info(f"Successfully triggered shutdown for VM '{VM_NAME}'.")
        return func.HttpResponse(f"Shutdown triggered for {VM_NAME}.", status_code=200)
    except Exception as e:
        logging.error(f"Failed to trigger shutdown for VM '{VM_NAME}': {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)

# --- 內部輔助函式 ---
def start_vm():
    logging.info(f"Attempting to start VM '{VM_NAME}'.")
    credential = DefaultAzureCredential()
    compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)
    async_start = compute_client.virtual_machines.begin_start(RESOURCE_GROUP_NAME, VM_NAME)
    async_start.wait(timeout=300) 
    logging.info(f"VM '{VM_NAME}' start process initiated.")
    
def stop_vm():
    """用來關閉並解除配置 VM 以停止計費的函式"""
    logging.info(f"Attempting to deallocate VM '{VM_NAME}'.")
    credential = DefaultAzureCredential()
    compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)
    async_stop = compute_client.virtual_machines.begin_deallocate(RESOURCE_GROUP_NAME, VM_NAME)
    async_stop.wait(timeout=300)
    logging.info(f"VM '{VM_NAME}' deallocation process initiated.")
