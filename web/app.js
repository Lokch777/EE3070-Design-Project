// ESP32 ASR Vision MVP - Frontend JavaScript

class ESP32ASRClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectDelay = 30000; // 30 seconds
        this.events = [];
        this.startTime = Date.now();
        this.stats = {
            asrPartial: 0,
            asrFinal: 0,
            triggers: 0,
            vision: 0,
            images: 0,
            totalEvents: 0,
            imagesStored: 0
        };
        this.last = {
            eventTime: '--',
            reqId: '--',
            asrText: '--',
            triggerText: '--',
            triggerKeyword: '--',
            triggerTime: '--',
            visionText: '--',
            visionTime: '--',
            visionReq: '--',
            visionConf: '--',
            imageSize: '--',
            imageTime: '--',
            imageFilename: '--'
        };
        this.init();
    }

    init() {
        this.connectWebSocket();
        this.loadHistory();
        this.refreshHealth();
        this.loadLatestImage();
        setInterval(() => this.refreshHealth(), 30000);
    }

    getBaseUrl() {
        const protocol = window.location.protocol;
        const host = window.location.host || 'localhost:8000';
        return `${protocol}//${host}`;
    }

    connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host || 'localhost:8000';
        const wsUrl = `${wsProtocol}//${host}/ws_ui`;

        console.log('Connecting to WebSocket:', wsUrl);
        this.updateConnectionStatus('connecting');
        this.appendLog('STATUS', 'Connecting to WebSocket...', Date.now() / 1000, true);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.reconnectAttempts = 0;
                this.updateConnectionStatus('connected');
                this.appendLog('STATUS', 'WebSocket connected', Date.now() / 1000, true);
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleEvent(data);
                } catch (error) {
                    console.error('Failed to parse message:', error);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('error');
                this.appendLog('ERROR', 'WebSocket error', Date.now() / 1000, true);
            };

            this.ws.onclose = () => {
                console.log('WebSocket closed');
                this.updateConnectionStatus('disconnected');
                this.appendLog('STATUS', 'WebSocket disconnected', Date.now() / 1000, true);
                this.scheduleReconnect();
            };
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.updateConnectionStatus('error');
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
        this.reconnectAttempts++;

        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connectWebSocket(), delay);
    }

    updateConnectionStatus(status) {
        const indicator = document.getElementById('statusIndicator');
        const text = document.getElementById('statusText');

        indicator.className = 'status-indicator';

        let statValue = '連線中';
        switch (status) {
            case 'connected':
                indicator.classList.add('connected');
                text.textContent = '已連線';
                statValue = '已連線';
                break;
            case 'connecting':
                text.textContent = '連線中...';
                statValue = '連線中';
                break;
            case 'disconnected':
                indicator.classList.add('disconnected');
                text.textContent = '已斷線';
                statValue = '已斷線';
                break;
            case 'error':
                indicator.classList.add('disconnected');
                text.textContent = '連線錯誤';
                statValue = '連線錯誤';
                break;
        }

        this.setText('statWs', statValue);
    }

    handleEvent(event, options = {}) {
        console.log('Received event:', event);
        const isHistory = Boolean(options.isHistory);

        this.stats.totalEvents += 1;
        this.last.eventTime = this.formatTime(event.timestamp);
        this.last.reqId = event.req_id || '--';

        switch (event.event_type) {
            case 'asr_partial':
                this.stats.asrPartial += 1;
                this.last.asrText = this.truncateText(event.data.text || '--', 18);
                this.updateASRText(event.data.text, true);
                this.appendLog('ASR', `Partial: ${this.truncateText(event.data.text || '', 48)}`, event.timestamp, true);
                break;
            case 'asr_final':
                this.stats.asrFinal += 1;
                this.last.asrText = this.truncateText(event.data.text || '--', 18);
                this.updateASRText(event.data.text, false);
                this.appendLog('ASR', `Final: ${this.truncateText(event.data.text || '', 48)}`, event.timestamp, true);
                break;
            case 'trigger_fired':
                this.stats.triggers += 1;
                this.last.triggerText = this.truncateText(event.data.trigger_text || '--', 18);
                this.last.triggerKeyword = event.data.matched_keyword || '--';
                this.last.triggerTime = this.formatTime(event.timestamp);
                this.addTriggerEvent(event);
                this.appendLog('TRIGGER', this.truncateText(event.data.trigger_text || '', 60), event.timestamp, true);
                break;
            case 'capture_received':
                this.stats.images += 1;
                this.last.imageSize = this.formatBytes(event.data.image_size || 0);
                this.last.imageTime = this.formatTime(event.timestamp);
                this.last.imageFilename = event.data.filename || '--';
                this.displayImage(event);
                this.appendLog('IMAGE', `${event.data.filename || 'capture'} (${this.formatBytes(event.data.image_size || 0)})`, event.timestamp, true);
                break;
            case 'vision_result':
                this.stats.vision += 1;
                this.last.visionText = this.truncateText(event.data.text || '--', 18);
                this.last.visionTime = this.formatTime(event.timestamp);
                this.last.visionReq = event.req_id || '--';
                this.last.visionConf = event.data.confidence ? `${(event.data.confidence * 100).toFixed(1)}%` : '--';
                this.displayVisionResult(event);
                this.appendLog('VISION', this.truncateText(event.data.text || '', 60), event.timestamp, true);
                break;
            case 'vision_started':
                this.appendLog('VISION', '分析開始', event.timestamp, true);
                break;
            case 'capture_requested':
                this.appendLog('CAPTURE', '請求拍照', event.timestamp, true);
                break;
            case 'question_detected':
                this.appendLog('QUESTION', this.truncateText(event.data.question_text || '', 60), event.timestamp, true);
                break;
            case 'tts_started':
                this.appendLog('TTS', this.truncateText(event.data.text || '', 60), event.timestamp, true);
                break;
            case 'error':
                this.displayError(event);
                this.appendLog('ERROR', this.truncateText(event.data?.message || 'Unknown error', 60), event.timestamp, true);
                break;
            default:
                this.appendLog('EVENT', event.event_type, event.timestamp, true);
                break;
        }

        this.updateInfoCards();

        if (!isHistory) {
            this.events.unshift(event);
            if (this.events.length > 20) {
                this.events.pop();
            }
        }
    }

    updateASRText(text, isPartial) {
        const asrText = document.getElementById('asrText');
        asrText.textContent = text;
        asrText.style.opacity = isPartial ? '0.7' : '1';
    }

    addTriggerEvent(event) {
        const eventsList = document.getElementById('eventsList');

        const noEvents = eventsList.querySelector('.no-events');
        if (noEvents) {
            noEvents.remove();
        }

        const eventItem = document.createElement('div');
        eventItem.className = 'event-item';

        const time = this.formatTime(event.timestamp);

        eventItem.innerHTML = `
            <div class="event-time">${time}</div>
            <div class="event-text">${event.data.trigger_text}</div>
            <div class="event-req-id">ID: ${event.req_id}</div>
        `;

        eventsList.insertBefore(eventItem, eventsList.firstChild);

        while (eventsList.children.length > 10) {
            eventsList.removeChild(eventsList.lastChild);
        }
    }

    displayImage(event) {
        const imageDisplay = document.getElementById('imageDisplay');
        const filename = event.data.filename;
        const baseUrl = this.getBaseUrl();

        if (filename) {
            const imageUrl = `${baseUrl}/images/${encodeURIComponent(filename)}?t=${Date.now()}`;
            imageDisplay.innerHTML = `<img src="${imageUrl}" alt="Latest capture">`;
            this.setText('imageFilename', filename);
            this.setText('imageSize', this.formatBytes(event.data.image_size || 0));
            this.setText('imageTime', this.formatTime(event.timestamp));
            return;
        }

        if (event.data.image_base64) {
            imageDisplay.innerHTML = `<img src="data:image/jpeg;base64,${event.data.image_base64}" alt="Latest capture">`;
            this.setText('imageFilename', 'base64');
            this.setText('imageSize', this.formatBytes(event.data.image_size || 0));
            this.setText('imageTime', this.formatTime(event.timestamp));
            return;
        }

        imageDisplay.innerHTML = `
            <div>
                <p>已接收影像 (${event.data.image_size || 0} bytes)</p>
                <p class="event-req-id">ID: ${event.req_id}</p>
            </div>
        `;
    }

    displayVisionResult(event) {
        const visionResult = document.getElementById('visionResult');

        visionResult.innerHTML = `
            <div class="result-text">${event.data.text}</div>
            ${event.data.confidence ? `<p style="margin-top: 10px; color: #666;">信心度: ${(event.data.confidence * 100).toFixed(1)}%</p>` : ''}
            <p class="event-req-id" style="margin-top: 10px;">ID: ${event.req_id}</p>
        `;
    }

    displayError(event) {
        console.error('System error:', event.data);
    }

    updateInfoCards() {
        this.setText('statLastEvent', this.last.eventTime);
        this.setText('statLastReq', this.last.reqId);
        this.setText('statTotalEvents', this.stats.totalEvents.toString());
        this.setText('statImagesStored', this.stats.imagesStored.toString());
        this.setText('statAsrPartial', this.stats.asrPartial.toString());
        this.setText('statAsrFinal', this.stats.asrFinal.toString());
        this.setText('statLastAsr', this.last.asrText);
        this.setText('statTriggers', this.stats.triggers.toString());
        this.setText('statVision', this.stats.vision.toString());
        this.setText('statVisionConf', this.last.visionConf);
        this.setText('statImages', this.stats.images.toString());
        this.setText('statImageSize', this.last.imageSize);
        this.setText('statImageTime', this.last.imageTime);
        this.setText('statLastTrigger', this.last.triggerText);
        this.setText('statTriggerKeyword', this.last.triggerKeyword);
        this.setText('statTriggerTime', this.last.triggerTime);
        this.setText('statLastVision', this.last.visionText);
        this.setText('statVisionReq', this.last.visionReq);
        this.setText('statVisionTime', this.last.visionTime);
    }

    formatTime(timestampSeconds) {
        if (!timestampSeconds) {
            return '--';
        }
        const date = new Date(timestampSeconds * 1000);
        return date.toLocaleTimeString('zh-TW');
    }

    formatBytes(bytes) {
        if (!bytes || bytes <= 0) {
            return '0 B';
        }
        const units = ['B', 'KB', 'MB'];
        let size = bytes;
        let unitIndex = 0;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex += 1;
        }
        return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
    }

    truncateText(text, maxLength) {
        if (!text) {
            return '--';
        }
        if (text.length <= maxLength) {
            return text;
        }
        return `${text.slice(0, maxLength - 1)}…`;
    }

    setText(id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    }

    appendLog(tag, message, timestamp, prepend) {
        const logList = document.getElementById('logList');
        if (!logList) {
            return;
        }

        const noLog = logList.querySelector('.no-log');
        if (noLog) {
            noLog.remove();
        }

        const line = document.createElement('div');
        line.className = 'log-line';
        line.innerHTML = `
            <span class="log-time">${this.formatTime(timestamp)}</span>
            <span class="log-tag">${tag}</span>
            <span class="log-msg">${message}</span>
        `;

        if (prepend) {
            logList.insertBefore(line, logList.firstChild);
        } else {
            logList.appendChild(line);
        }

        while (logList.children.length > 20) {
            logList.removeChild(logList.lastChild);
        }
    }

    async loadHistory() {
        try {
            const apiUrl = `${this.getBaseUrl()}/api/history?limit=40`;
            const response = await fetch(apiUrl);
            if (response.ok) {
                const data = await response.json();
                console.log('Loaded history:', data);
                if (Array.isArray(data.events)) {
                    const ordered = [...data.events].reverse();
                    ordered.forEach((event) => this.handleEvent(event, { isHistory: true }));
                }
            }
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    }

    async refreshHealth() {
        try {
            const response = await fetch(`${this.getBaseUrl()}/api/health`);
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            this.stats.imagesStored = data.images_stored || 0;
            this.setText('statHealth', data.status || '--');
            this.setText('statAudio', data.esp32_audio_connected ? 'ONLINE' : 'OFF');
            this.setText('statCamera', data.esp32_camera_connected ? 'ONLINE' : 'OFF');
            this.updateInfoCards();
        } catch (error) {
            console.error('Failed to load health:', error);
        }
    }

    async loadLatestImage() {
        try {
            const response = await fetch(`${this.getBaseUrl()}/api/images`);
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            if (!Array.isArray(data.images) || data.images.length === 0) {
                return;
            }
            const latest = data.images[0];
            const imageDisplay = document.getElementById('imageDisplay');
            const imageUrl = `${this.getBaseUrl()}/images/${encodeURIComponent(latest.filename)}?t=${Date.now()}`;
            imageDisplay.innerHTML = `<img src="${imageUrl}" alt="Latest capture">`;
            this.setText('imageFilename', latest.filename);
            this.setText('imageSize', this.formatBytes(latest.size || 0));
            this.setText('imageTime', latest.created ? new Date(latest.created * 1000).toLocaleTimeString('zh-TW') : '--');
        } catch (error) {
            console.error('Failed to load latest image:', error);
        }
    }
}

// Initialize client when page loads
document.addEventListener('DOMContentLoaded', () => {
    window.asrClient = new ESP32ASRClient();
});
