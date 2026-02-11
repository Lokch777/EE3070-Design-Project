// ESP32 ASR Vision MVP - Frontend JavaScript

class ESP32ASRClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectDelay = 30000; // 30 seconds
        this.events = [];
        this.init();
    }

    init() {
        this.connectWebSocket();
        this.loadHistory();
    }

    connectWebSocket() {
        // Get WebSocket URL from current location
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host || 'localhost:8000';
        const wsUrl = `${protocol}//${host}/ws_ui`;

        console.log('Connecting to WebSocket:', wsUrl);
        this.updateConnectionStatus('connecting');

        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.reconnectAttempts = 0;
                this.updateConnectionStatus('connected');
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
            };

            this.ws.onclose = () => {
                console.log('WebSocket closed');
                this.updateConnectionStatus('disconnected');
                this.scheduleReconnect();
            };
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.updateConnectionStatus('error');
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        // Exponential backoff: 1s, 2s, 4s, 8s, ... max 30s
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
        this.reconnectAttempts++;
        
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connectWebSocket(), delay);
    }

    updateConnectionStatus(status) {
        const indicator = document.getElementById('statusIndicator');
        const text = document.getElementById('statusText');
        
        indicator.className = 'status-indicator';
        
        switch (status) {
            case 'connected':
                indicator.classList.add('connected');
                text.textContent = '已連線';
                break;
            case 'connecting':
                text.textContent = '連線中...';
                break;
            case 'disconnected':
                indicator.classList.add('disconnected');
                text.textContent = '已斷線';
                break;
            case 'error':
                indicator.classList.add('disconnected');
                text.textContent = '連線錯誤';
                break;
        }
    }

    handleEvent(event) {
        console.log('Received event:', event);
        
        switch (event.event_type) {
            case 'asr_partial':
                this.updateASRText(event.data.text, true);
                break;
            case 'asr_final':
                this.updateASRText(event.data.text, false);
                break;
            case 'trigger_fired':
                this.addTriggerEvent(event);
                break;
            case 'capture_received':
                this.displayImage(event);
                break;
            case 'vision_result':
                this.displayVisionResult(event);
                break;
            case 'error':
                this.displayError(event);
                break;
        }
        
        // Store event
        this.events.unshift(event);
        if (this.events.length > 20) {
            this.events.pop();
        }
    }

    updateASRText(text, isPartial) {
        const asrText = document.getElementById('asrText');
        asrText.textContent = text;
        asrText.style.opacity = isPartial ? '0.7' : '1';
    }

    addTriggerEvent(event) {
        const eventsList = document.getElementById('eventsList');
        
        // Remove "no events" message
        const noEvents = eventsList.querySelector('.no-events');
        if (noEvents) {
            noEvents.remove();
        }
        
        const eventItem = document.createElement('div');
        eventItem.className = 'event-item';
        
        const time = new Date(event.timestamp * 1000).toLocaleTimeString('zh-TW');
        
        eventItem.innerHTML = `
            <div class="event-time">${time}</div>
            <div class="event-text">${event.data.trigger_text}</div>
            <div class="event-req-id">ID: ${event.req_id}</div>
        `;
        
        eventsList.insertBefore(eventItem, eventsList.firstChild);
        
        // Keep only last 10 events
        while (eventsList.children.length > 10) {
            eventsList.removeChild(eventsList.lastChild);
        }
    }

    displayImage(event) {
        const imageDisplay = document.getElementById('imageDisplay');
        
        // TODO: Implement image display when backend sends image data
        imageDisplay.innerHTML = `
            <div>
                <p>已接收影像 (${event.data.image_size} bytes)</p>
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
        // TODO: Implement error display UI
    }

    async loadHistory() {
        try {
            const protocol = window.location.protocol;
            const host = window.location.host || 'localhost:8000';
            const apiUrl = `${protocol}//${host}/api/history?limit=20`;
            
            const response = await fetch(apiUrl);
            if (response.ok) {
                const data = await response.json();
                console.log('Loaded history:', data);
                // TODO: Display historical events
            }
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    }
}

// Initialize client when page loads
document.addEventListener('DOMContentLoaded', () => {
    window.asrClient = new ESP32ASRClient();
});
